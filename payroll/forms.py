from datetime import timedelta

from django import forms
from django.utils import timezone

from employees.models import Employee

from .models import (
    EmployeePayProfile,
    EmployeePayRate,
    PayrollHoliday,
    PayrollLine,
    PayrollException,
    PayrollRuleSet,
    PayrollRun,
    PayrollSettings,
    PayrollStatement,
)


class PayrollSettingsForm(forms.ModelForm):
    class Meta:
        model = PayrollSettings
        fields = ["frequency"]


class PayrollRuleSetForm(forms.ModelForm):
    class Meta:
        model = PayrollRuleSet
        fields = [
            "effective_from", "effective_until", "regular_day_minutes", "overtime_multiplier",
            "rest_day_multiplier", "rest_day_overtime_multiplier", "night_start", "night_end",
            "night_differential_rate", "source_references", "reviewed_by",
        ]
        widgets = {
            "effective_from": forms.DateInput(attrs={"type": "date"}),
            "effective_until": forms.DateInput(attrs={"type": "date"}),
            "night_start": forms.TimeInput(attrs={"type": "time"}),
            "night_end": forms.TimeInput(attrs={"type": "time"}),
            "source_references": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, organization, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("effective_from"), cleaned.get("effective_until")
        if start and end and end < start:
            self.add_error("effective_until", "End date must be on or after the effective date.")
        if self.instance.pk and self.instance.reviewed:
            original = PayrollRuleSet.objects.get(pk=self.instance.pk)
            changed = any(
                self.cleaned_data.get(field) != getattr(original, field)
                for field in self.Meta.fields
                if field != "reviewed_by"
            )
            if changed:
                raise forms.ValidationError("Reviewed payroll rules are locked. Add a new effective-dated version.")
        return cleaned

    def save(self, commit=True, *, actor=None):
        rule = super().save(commit=False)
        rule.organization = self.organization
        if actor and self.cleaned_data.get("reviewed_by") and self.cleaned_data.get("source_references"):
            if rule.reviewed_at is None:
                rule.reviewed_at = timezone.now()
        else:
            rule.reviewed_by = ""
            rule.reviewed_at = None
        if commit:
            rule.save()
            self.save_m2m()
        return rule


class EmployeePayProfileForm(forms.ModelForm):
    class Meta:
        model = EmployeePayProfile
        fields = ["work_location", "payroll_region", "payroll_timezone", "wage_order_reference", "minimum_wage_confirmed", "night_differential_eligible", "rest_day", "rank_and_file", "active_for_payroll"]
        labels = {
            "minimum_wage_confirmed": "Hourly rate checked against the applicable wage order",
            "night_differential_eligible": "Eligibility for night differential confirmed",
            "rank_and_file": "Rank-and-file classification confirmed",
            "active_for_payroll": "Include this employee in payroll setup",
            "payroll_timezone": "Work location timezone",
        }
        help_texts = {
            "minimum_wage_confirmed": "Use the official wage order for the employee's actual work location; store its reference above.",
            "night_differential_eligible": "Confirm statutory coverage with your payroll adviser. Unconfirmed night work blocks run review.",
            "rank_and_file": "Record this classification only after checking the employee's actual role.",
            "payroll_timezone": "Used to split overnight work and apply effective rules by local work date. Confirm this is the employee's actual work timezone. Blank uses the organization timezone.",
        }
        widgets = {"work_location": forms.TextInput(attrs={"autocomplete": "organization"})}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("minimum_wage_confirmed") and not cleaned.get("wage_order_reference", "").strip():
            self.add_error("wage_order_reference", "Add the applicable official wage-order source before confirming the hourly rate.")
        if cleaned.get("minimum_wage_confirmed") and not cleaned.get("work_location", "").strip():
            self.add_error("work_location", "Add the employee's work location before confirming the hourly rate.")
        current_timezone = (self.instance.payroll_timezone or "").strip()
        new_timezone = (cleaned.get("payroll_timezone") or "").strip()
        if self.instance.pk and new_timezone != current_timezone and PayrollStatement.objects.filter(
            employee_id=self.instance.employee_id,
            run__status=PayrollRun.Status.FINALIZED,
        ).exists():
            self.add_error("payroll_timezone", "Work timezone is locked after finalized payroll because effective-dated timezone history is not yet supported.")
        return cleaned


class EmployeePayRateForm(forms.ModelForm):
    class Meta:
        model = EmployeePayRate
        fields = ["hourly_rate", "effective_from", "change_reason"]
        widgets = {"effective_from": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, employee, actor, **kwargs):
        self.employee = employee
        self.actor = actor
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        rate = super().save(commit=False)
        rate.employee = self.employee
        rate.created_by = self.actor
        if commit:
            rate.save()
        return rate


class PayrollHolidayForm(forms.ModelForm):
    class Meta:
        model = PayrollHoliday
        fields = ["date", "name", "kind", "worked_multiplier", "overtime_multiplier", "source_reference", "reviewed_by"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, organization, actor, **kwargs):
        self.organization = organization
        self.actor = actor
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        holiday_date = cleaned.get("date")
        if holiday_date and PayrollHoliday.objects.filter(
            organization=self.organization,
            date=holiday_date,
        ).exclude(pk=self.instance.pk).exists():
            self.add_error("date", "A holiday is already recorded for this date.")
        return cleaned

    def save(self, commit=True):
        holiday = super().save(commit=False)
        holiday.organization = self.organization
        if not holiday.pk:
            holiday.created_by = self.actor
        if holiday.reviewed_by and holiday.source_reference:
            holiday.reviewed_at = timezone.now()
        else:
            holiday.reviewed_by = ""
            holiday.reviewed_at = None
        if commit:
            holiday.save()
        return holiday


class PayrollRunForm(forms.ModelForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput)

    class Meta:
        model = PayrollRun
        fields = ["run_type", "period_start", "period_end", "pay_date", "parent_run"]
        widgets = {
            "period_start": forms.DateInput(attrs={"type": "date"}),
            "period_end": forms.DateInput(attrs={"type": "date"}),
            "pay_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.fields["request_key"].initial = kwargs.get("initial", {}).get("request_key")
        self.fields["parent_run"].queryset = PayrollRun.objects.filter(
            organization=organization, status=PayrollRun.Status.FINALIZED
        )
        self.fields["parent_run"].required = False

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("period_start"), cleaned.get("period_end")
        if start and end and end < start:
            self.add_error("period_end", "Period end must be on or after period start.")
        if cleaned.get("run_type") == PayrollRun.RunType.OFF_CYCLE and not cleaned.get("parent_run"):
            self.add_error("parent_run", "Choose the finalized payroll run this correction relates to.")
        if cleaned.get("run_type") == PayrollRun.RunType.OFF_CYCLE and cleaned.get("parent_run") and start and end:
            if (start, end) != (cleaned["parent_run"].period_start, cleaned["parent_run"].period_end):
                self.add_error("period_start", "An off-cycle correction uses the linked run's original pay period.")
        if cleaned.get("run_type") == PayrollRun.RunType.REGULAR and cleaned.get("parent_run"):
            self.add_error("parent_run", "Only an off-cycle run can be linked to a prior run.")
        if cleaned.get("run_type") == PayrollRun.RunType.REGULAR and start and end:
            settings_row = PayrollSettings.objects.filter(organization=self.organization).first()
            frequency = settings_row.frequency if settings_row else PayrollSettings.Frequency.SEMI_MONTHLY
            if frequency == PayrollSettings.Frequency.WEEKLY:
                if start.weekday() != 0 or end != start + timedelta(days=6):
                    self.add_error("period_start", "Weekly payroll periods run Monday through Sunday.")
            elif frequency == PayrollSettings.Frequency.SEMI_MONTHLY:
                last_day = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                valid = (start.day == 1 and end == start.replace(day=15)) or (
                    start.day == 16 and end == last_day
                )
                if not valid:
                    self.add_error("period_start", "Semi-monthly periods run from the 1st–15th or 16th–month end.")
            elif frequency == PayrollSettings.Frequency.MONTHLY:
                last_day = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                if start.day != 1 or end != last_day:
                    self.add_error("period_start", "Monthly payroll periods run from the first through the last day of a month.")
        if start and end and cleaned.get("pay_date") and cleaned["pay_date"] < end:
            self.add_error("pay_date", "Pay date must be on or after the end of the payroll period.")
        return cleaned


class PayrollAdjustmentForm(forms.Form):
    employee = forms.ModelChoiceField(queryset=Employee.objects.none(), empty_label="Choose employee")
    kind = forms.ChoiceField(choices=[
        (PayrollLine.Kind.EARNING, "Earning / allowance / reimbursement"),
        (PayrollLine.Kind.DEDUCTION, "Employee deduction / withholding"),
        (PayrollLine.Kind.EMPLOYER_CONTRIBUTION, "Employer contribution"),
    ])
    label = forms.CharField(max_length=120, label="Line item")
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01)
    effective_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    note = forms.CharField(max_length=255, label="Reason / source", widget=forms.TextInput(attrs={"autocomplete": "off"}))

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.filter(organization=organization)


class FinalizePayrollForm(forms.Form):
    review_note = forms.CharField(
        label="Review evidence",
        help_text="Record who reconciled this run and the source/document reference used.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class VoidPayrollForm(forms.Form):
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}))


class PayrollExceptionResolutionForm(forms.Form):
    resolution_note = forms.CharField(max_length=500, label="Review evidence")
    resolution_line = forms.ModelChoiceField(
        queryset=PayrollLine.objects.none(), required=False,
        label="Manual earning line",
        help_text="Required for exceptions that need an independently reviewed premium calculation.",
    )

    def __init__(self, *args, run, exception, **kwargs):
        super().__init__(*args, **kwargs)
        self.exception = exception
        self.fields["resolution_line"].queryset = PayrollLine.objects.filter(
            statement__run=run,
            statement__employee=exception.employee,
            kind=PayrollLine.Kind.EARNING,
            source="MANUAL",
            effective_date=exception.work_date,
        )

    def clean(self):
        cleaned = super().clean()
        if self.exception.needs_manual_pay_line and not cleaned.get("resolution_line"):
            self.add_error("resolution_line", "Add a manual earning line for the affected work date before resolving this exception.")
        return cleaned
