from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from employees.models import Employee
from .statutory import AGENCIES, REGISTRATIONS, TREATMENTS

from .models import (
    EmployeeCompensationVersion,
    EmployeeComponentAssignment,
    EmployeePayProfile,
    EmployeePayRate,
    PayrollComponentDefinition,
    PayrollHoliday,
    PayrollLine,
    PayrollException,
    PayrollRuleAssignment,
    PayrollRuleProfile,
    PayrollRuleSet,
    PayrollRun,
    PayrollSettings,
    PayrollStatement,
    PayrollPeriodInput,
)


class PayrollSettingsForm(forms.ModelForm):
    class Meta:
        model = PayrollSettings
        fields = ["frequency"]


class PayrollRuleSetForm(forms.ModelForm):
    regular_day_minutes = forms.DecimalField(
        label="Regular workday",
        min_value=Decimal("0.25"),
        max_value=Decimal("24"),
        max_digits=4,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.25", "inputmode": "decimal"}),
        help_text="Enter hours. Use 15-minute increments.",
    )
    night_differential_rate = forms.DecimalField(
        label="Night differential",
        min_value=Decimal("0"),
        max_value=Decimal("999.99"),
        max_digits=6,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
        help_text="Enter a percentage with up to two decimal places, for example 10.00%.",
    )

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
        labels = {
            "effective_from": "Effective from",
            "effective_until": "Effective until",
            "overtime_multiplier": "Ordinary overtime",
            "rest_day_multiplier": "Rest-day work",
            "rest_day_overtime_multiplier": "Rest-day overtime",
            "night_start": "Night window starts",
            "night_end": "Night window ends",
            "source_references": "Source references",
            "reviewed_by": "Reviewed by",
        }

    def __init__(self, *args, organization, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        self.initial["regular_day_minutes"] = (
            Decimal(self.instance.regular_day_minutes) / Decimal("60")
        )
        self.initial["night_differential_rate"] = (
            (Decimal(self.instance.night_differential_rate) * Decimal("100")).quantize(Decimal("0.01"))
        )
        self.fields["overtime_multiplier"].help_text = "Multiplier applied to eligible ordinary overtime."
        self.fields["rest_day_multiplier"].help_text = "Multiplier applied to eligible work on the employee's rest day."
        self.fields["rest_day_overtime_multiplier"].help_text = "Multiplier applied to eligible rest-day overtime."
        self.fields["night_start"].help_text = "Start of the configured local night window."
        self.fields["night_end"].help_text = "End of the configured local night window."

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("effective_from"), cleaned.get("effective_until")
        if start and end and end < start:
            self.add_error("effective_until", "End date must be on or after the effective date.")
        workday_hours = cleaned.get("regular_day_minutes")
        if workday_hours is not None and (workday_hours * 60) % 15:
            self.add_error("regular_day_minutes", "Choose a workday length in 15-minute increments.")
        if self.instance.pk and self.instance.reviewed:
            original = PayrollRuleSet.objects.get(pk=self.instance.pk)
            changed = False
            for field in self.Meta.fields:
                if field == "reviewed_by":
                    continue
                submitted = cleaned.get(field)
                stored = getattr(original, field)
                if field == "regular_day_minutes":
                    stored = Decimal(stored) / Decimal("60")
                elif field == "night_differential_rate":
                    stored = Decimal(stored) * Decimal("100")
                if submitted != stored:
                    changed = True
                    break
            if changed:
                raise forms.ValidationError("Reviewed payroll rules are locked. Add a new effective-dated version.")
        return cleaned

    def _post_clean(self):
        # The form presents hours and percentages, while the model stores minutes
        # and fractional rates. Convert before ModelForm validates the instance,
        # then restore the display values used by save().
        display_workday = self.cleaned_data.get("regular_day_minutes")
        display_night_rate = self.cleaned_data.get("night_differential_rate")
        if display_workday is not None:
            self.cleaned_data["regular_day_minutes"] = int(display_workday * Decimal("60"))
        if display_night_rate is not None:
            self.cleaned_data["night_differential_rate"] = display_night_rate / Decimal("100")
        super()._post_clean()
        if display_workday is not None:
            self.cleaned_data["regular_day_minutes"] = display_workday
        if display_night_rate is not None:
            self.cleaned_data["night_differential_rate"] = display_night_rate

    def save(self, commit=True, *, actor=None):
        rule = super().save(commit=False)
        rule.regular_day_minutes = int(self.cleaned_data["regular_day_minutes"] * Decimal("60"))
        rule.night_differential_rate = self.cleaned_data["night_differential_rate"] / Decimal("100")
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


class PayrollRuleProfileForm(forms.ModelForm):
    class Meta:
        model = PayrollRuleProfile
        fields = ["code", "name", "description", "is_default", "active"]
        labels = {
            "code": "Profile code",
            "name": "Profile name",
            "description": "Description",
            "is_default": "Use as organization default",
            "active": "Available for assignments",
        }
        help_texts = {
            "code": "A short stable identifier, such as standard or union-a.",
            "description": "Describe which employees or agreement this profile covers.",
            "is_default": "Employees without an explicit assignment inherit this profile.",
            "active": "Inactive profiles cannot be newly assigned. A default profile is always available for assignments.",
        }
        widgets = {
            "description": forms.TextInput(attrs={"placeholder": "e.g. Standard hourly employees"}),
        }

    def __init__(self, *args, organization, actor, **kwargs):
        self.organization = organization
        self.actor = actor
        super().__init__(*args, **kwargs)

    def clean_code(self):
        return self.cleaned_data["code"].strip().lower()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_default") and not cleaned.get("active"):
            # A profile cannot be the organization fallback while unavailable for
            # assignments. Treat selecting the default checkbox as the user's
            # intent to enable the profile instead of rejecting the submission
            # with an error that used to look like a silent page reload.
            cleaned["active"] = True
        return cleaned

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.organization = self.organization
        if not profile.pk:
            profile.created_by = self.actor
        if commit:
            profile.save()
        return profile


class PayrollRuleAssignmentForm(forms.ModelForm):
    class Meta:
        model = PayrollRuleAssignment
        fields = ["rule_profile", "effective_from", "effective_until", "reason"]
        labels = {
            "rule_profile": "Payroll rule profile",
            "effective_from": "Effective from",
            "effective_until": "Effective until",
            "reason": "Assignment reason",
        }
        help_texts = {
            "rule_profile": "The employee uses this profile for matching local work dates.",
            "effective_from": "Dates are inclusive and use the employee's work timezone calendar.",
            "effective_until": "Leave blank for an open-ended assignment.",
            "reason": "Optional note for the audit history, such as a location or agreement change.",
        }
        widgets = {
            "effective_from": forms.DateInput(attrs={"type": "date"}),
            "effective_until": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, organization, employee, actor, **kwargs):
        self.organization = organization
        self.employee = employee
        self.actor = actor
        super().__init__(*args, **kwargs)
        self.fields["rule_profile"].queryset = PayrollRuleProfile.objects.filter(
            organization=organization, active=True,
        ).order_by("-is_default", "name")

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("effective_from"), cleaned.get("effective_until")
        if start and end and end < start:
            self.add_error("effective_until", "End date must be on or after the effective date.")
        if start and PayrollStatement.objects.filter(
            employee=self.employee,
            run__status=PayrollRun.Status.FINALIZED,
            run__period_end__gte=start,
        ).exists():
            self.add_error("effective_from", "This assignment could change finalized payroll. Use an off-cycle adjustment for a correction.")
        return cleaned

    def save(self, commit=True):
        assignment = super().save(commit=False)
        assignment.organization = self.organization
        assignment.employee = self.employee
        assignment.assigned_by = self.actor
        if commit:
            assignment.save()
        return assignment


class PayrollBulkRuleAssignmentForm(forms.Form):
    employees = forms.ModelMultipleChoiceField(
        queryset=Employee.objects.none(),
        widget=forms.MultipleHiddenInput,
        required=True,
    )
    rule_profile = forms.ModelChoiceField(queryset=PayrollRuleProfile.objects.none(), label="Payroll rule profile")
    effective_from = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Effective from")
    effective_until = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Effective until", required=False)
    reason = forms.CharField(max_length=255, required=False, label="Assignment reason")

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employees"].queryset = Employee.objects.filter(organization=organization)
        self.fields["rule_profile"].queryset = PayrollRuleProfile.objects.filter(
            organization=organization, active=True,
        ).order_by("-is_default", "name")

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("effective_from"), cleaned.get("effective_until")
        if start and end and end < start:
            self.add_error("effective_until", "End date must be on or after the effective date.")
        return cleaned


class EmployeePayProfileForm(forms.ModelForm):
    class Meta:
        model = EmployeePayProfile
        fields = ["employment_status", "pay_basis", "minimum_daily_rate", "work_location", "payroll_region", "payroll_timezone", "wage_order_reference", "minimum_wage_confirmed", "night_differential_eligible", "rest_day", "rank_and_file", "active_for_payroll"]
        labels = {
            "employment_status": "Employment status",
            "pay_basis": "Primary pay basis",
            "minimum_daily_rate": "Reviewed minimum daily base (PHP)",
            "work_location": "Work location",
            "payroll_region": "Payroll region",
            "minimum_wage_confirmed": "Hourly rate checked against the applicable wage order",
            "night_differential_eligible": "Eligibility for night differential confirmed",
            "rank_and_file": "Rank-and-file classification confirmed",
            "payroll_timezone": "Work location timezone",
            "rest_day": "Rest day",
            "wage_order_reference": "Wage order reference",
            "active_for_payroll": "Include this employee in payroll",
        }
        help_texts = {
            "employment_status": "Classification only; it does not infer statutory coverage.",
            "pay_basis": "Monthly and mixed bases remain reviewer-configured until conversion rules are approved.",
            "minimum_daily_rate": "Optional reviewer-entered statutory base for this employee's wage region.",
            "work_location": "The employee's usual work location.",
            "payroll_region": "The wage-order region for this work location.",
            "payroll_timezone": "Used to apply payroll rules by the employee's local work date. Blank uses the organization timezone.",
            "wage_order_reference": "Use the official wage order for this work location.",
            "minimum_wage_confirmed": "Confirm against the official wage order recorded here.",
            "night_differential_eligible": "Confirm coverage with your payroll adviser. Unconfirmed night work blocks run review.",
            "rank_and_file": "Confirm only after checking the employee's actual role.",
            "active_for_payroll": "When enabled, this employee can be included in eligible payroll runs.",
        }
        widgets = {
            "work_location": forms.TextInput(attrs={"autocomplete": "organization", "placeholder": "e.g. Cebu City"}),
            "payroll_region": forms.TextInput(attrs={"placeholder": "e.g. Region VII"}),
            "payroll_timezone": forms.TextInput(attrs={"placeholder": "e.g. Asia/Manila", "autocomplete": "off"}),
            "wage_order_reference": forms.Textarea(attrs={"rows": 2, "placeholder": "Region, order number, year, or official URL"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["active_for_payroll"].widget.attrs.update({"role": "switch"})

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
        labels = {
            "hourly_rate": "Hourly rate (PHP per hour)",
            "effective_from": "Effective from",
            "change_reason": "Reason for rate change",
        }
        help_texts = {
            "hourly_rate": "Enter the employee's gross base hourly rate in Philippine pesos.",
            "effective_from": "The rate applies by the employee's local work date.",
        }

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


class EmployeeCompensationForm(forms.ModelForm):
    class Meta:
        model = EmployeeCompensationVersion
        fields = ["basis", "amount", "effective_from", "regular_day_minutes", "source_reference", "reviewed_by"]
        widgets = {
            "effective_from": forms.DateInput(attrs={"type": "date"}),
            "regular_day_minutes": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "source_reference": forms.TextInput(attrs={"placeholder": "Contract, approved register, or wage-order reference"}),
        }
        labels = {
            "basis": "Pay basis",
            "amount": "Amount (PHP)",
            "effective_from": "Effective from",
            "regular_day_minutes": "Regular day length (minutes)",
            "source_reference": "Source reference",
            "reviewed_by": "Reviewed by",
        }
        help_texts = {
            "basis": "Hourly preserves the existing time-based flow. Daily uses reviewed period inputs.",
            "amount": "Hourly rate or daily rate, depending on the selected basis.",
            "regular_day_minutes": "Used to convert daily pay into undertime, overtime, and night differential amounts.",
            "source_reference": "Record the contract, approved register, or other reviewed source.",
        }

    def __init__(self, *args, employee, actor, organization, **kwargs):
        self.employee = employee
        self.actor = actor
        self.organization = organization
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("effective_from")
        if start and PayrollStatement.objects.filter(
            employee=self.employee,
            run__status=PayrollRun.Status.FINALIZED,
            run__period_end__gte=start,
        ).exists():
            self.add_error("effective_from", "This date could change finalized payroll. Use an off-cycle adjustment for a correction.")
        return cleaned

    def save(self, commit=True):
        compensation = super().save(commit=False)
        compensation.employee = self.employee
        compensation.organization = self.organization
        compensation.created_by = self.actor
        if compensation.source_reference.strip() and compensation.reviewed_by.strip():
            compensation.reviewed_at = timezone.now()
        if commit:
            compensation.save()
        return compensation


class PayrollComponentDefinitionForm(forms.ModelForm):
    class Meta:
        model = PayrollComponentDefinition
        fields = ["code", "label", "kind", "basis", "deduct_undertime", "description", "active"]
        widgets = {"description": forms.TextInput(attrs={"placeholder": "What this component represents"})}

    def __init__(self, *args, organization, actor, **kwargs):
        self.organization = organization
        self.actor = actor
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        component = super().save(commit=False)
        component.organization = self.organization
        if not component.pk:
            component.created_by = self.actor
        if commit:
            component.save()
        return component


class EmployeeComponentAssignmentForm(forms.ModelForm):
    class Meta:
        model = EmployeeComponentAssignment
        fields = ["component", "amount", "effective_from", "effective_until", "basis", "deduct_undertime", "source_reference"]
        widgets = {
            "effective_from": forms.DateInput(attrs={"type": "date"}),
            "effective_until": forms.DateInput(attrs={"type": "date"}),
        }
        help_texts = {
            "basis": "Leave blank to inherit the component definition's basis.",
            "deduct_undertime": "For per-day components, reduce the amount by reviewed undertime minutes.",
        }

    def __init__(self, *args, employee, actor, organization, **kwargs):
        self.employee = employee
        self.actor = actor
        self.organization = organization
        super().__init__(*args, **kwargs)
        self.fields["component"].queryset = PayrollComponentDefinition.objects.filter(
            organization=organization, active=True,
        ).order_by("label")

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("effective_from")
        if start and PayrollStatement.objects.filter(
            employee=self.employee,
            run__status=PayrollRun.Status.FINALIZED,
            run__period_end__gte=start,
        ).exists():
            self.add_error("effective_from", "This date could change finalized payroll. Use an off-cycle adjustment for a correction.")
        return cleaned

    def save(self, commit=True):
        assignment = super().save(commit=False)
        assignment.employee = self.employee
        assignment.organization = self.organization
        assignment.assigned_by = self.actor
        if commit:
            assignment.save()
        return assignment


class PayrollPeriodInputForm(forms.ModelForm):
    class Meta:
        model = PayrollPeriodInput
        fields = ["period_start", "period_end", "work_date", "worked_day_units", "planned_day_units", "undertime_minutes", "overtime_minutes", "night_minutes", "holiday_units", "mode", "source_reference", "reviewed_by"]
        widgets = {
            "period_start": forms.DateInput(attrs={"type": "date"}),
            "period_end": forms.DateInput(attrs={"type": "date"}),
            "work_date": forms.DateInput(attrs={"type": "date"}),
            "worked_day_units": forms.NumberInput(attrs={"min": "0", "step": "0.001"}),
            "planned_day_units": forms.NumberInput(attrs={"min": "0", "step": "0.001"}),
            "holiday_units": forms.NumberInput(attrs={"min": "0", "step": "0.001"}),
        }
        labels = {
            "worked_day_units": "Worked day units",
            "planned_day_units": "Planned day units",
            "undertime_minutes": "Undertime (minutes)",
            "overtime_minutes": "Overtime (minutes)",
            "night_minutes": "Night hours (minutes)",
            "holiday_units": "Holiday premium units",
        }

    def __init__(self, *args, employee, actor, organization, **kwargs):
        self.employee = employee
        self.actor = actor
        self.organization = organization
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        period_input = super().save(commit=False)
        period_input.employee = self.employee
        period_input.organization = self.organization
        period_input.created_by = self.actor
        period_input.reviewed_at = timezone.now()
        if commit:
            period_input.save()
        return period_input


class PayrollHolidayForm(forms.ModelForm):
    class Meta:
        model = PayrollHoliday
        fields = ["date", "name", "kind", "worked_multiplier", "overtime_multiplier", "source_reference", "reviewed_by"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}
        labels = {
            "date": "Date",
            "name": "Holiday name",
            "kind": "Classification",
            "worked_multiplier": "Worked rate",
            "overtime_multiplier": "Overtime rate",
            "source_reference": "Source reference",
            "reviewed_by": "Reviewed by",
        }

    def __init__(self, *args, organization, actor, **kwargs):
        self.organization = organization
        self.actor = actor
        super().__init__(*args, **kwargs)
        self.fields["worked_multiplier"].help_text = "Multiplier for eligible hours worked on this holiday."
        self.fields["overtime_multiplier"].help_text = "Multiplier for eligible overtime on this holiday."
        self.fields["source_reference"].help_text = "Use the official holiday proclamation or other approved source."

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
    employees = forms.ModelMultipleChoiceField(
        queryset=Employee.objects.none(), required=False,
        label="Employees in this run",
        help_text="Choose the employees for this period. Leave the scope as all active employees to include everyone configured for payroll.",
        widget=forms.SelectMultiple(attrs={"size": 6}),
    )

    class Meta:
        model = PayrollRun
        fields = ["run_type", "scope_mode", "period_start", "period_end", "pay_date", "parent_run"]
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
        self.fields["employees"].queryset = Employee.objects.filter(
            organization=organization, status=Employee.Status.ACTIVE,
        ).order_by("last_name", "first_name")
        self.fields["employees"].label_from_instance = lambda employee: f"{employee.full_name} · {employee.employee_code}"
        self.order_fields([
            "run_type", "scope_mode", "employees", "period_start", "period_end", "pay_date", "parent_run", "request_key",
        ])

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
        if cleaned.get("scope_mode") == PayrollRun.ScopeMode.SELECTED and not cleaned.get("employees"):
            self.add_error("employees", "Select at least one active employee for a selected run.")
        if cleaned.get("scope_mode") == PayrollRun.ScopeMode.ALL_ACTIVE and cleaned.get("employees"):
            self.add_error("employees", "Clear the employee list when using all active employees.")
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


class StatutoryReviewForm(forms.Form):
    agency = forms.ChoiceField(choices=[('', 'Choose statutory item'), *AGENCIES])
    registration = forms.ChoiceField(label='Registration status', choices=[('', 'Choose status'), *REGISTRATIONS])
    employee_treatment = forms.ChoiceField(label='Employee deduction treatment', choices=[('', 'Choose treatment'), *TREATMENTS])
    employee_line = forms.ModelChoiceField(label='Employee deduction line', queryset=PayrollLine.objects.none(), required=False,
        empty_label='No line selected', help_text='Add the manual deduction below first if an amount applies.')
    employer_treatment = forms.ChoiceField(label='Employer contribution treatment', choices=[('', 'Choose treatment'), *TREATMENTS],
        help_text='For withholding tax, choose Not applicable. Employer shares do not reduce employee net pay.')
    employer_line = forms.ModelChoiceField(label='Employer contribution line', queryset=PayrollLine.objects.none(), required=False,
        empty_label='No line selected')
    source_reference = forms.CharField(max_length=255, label='Calculation / source reference',
        help_text='Reference the reviewed calculation and applicable period. Do not enter government ID numbers.')
    review_note = forms.CharField(max_length=500, label='Review reason', widget=forms.Textarea(attrs={'rows': 2}),
        help_text='Explain any zero amount, exemption, or different cutoff. A missing number is not an exemption.')
    registration_follow_up = forms.CharField(max_length=500, required=False, label='Registration follow-up',
        widget=forms.Textarea(attrs={'rows': 2}), help_text='Required when a number or registration is pending.')

    def __init__(self, *args, statement, **kwargs):
        super().__init__(*args, **kwargs)
        for side, kind in (('employee', PayrollLine.Kind.DEDUCTION), ('employer', PayrollLine.Kind.EMPLOYER_CONTRIBUTION)):
            field = self.fields[f'{side}_line']
            field.queryset = statement.lines.filter(kind=kind, source='MANUAL')
            field.label_from_instance = lambda line: f'{line.label} — {statement.run.currency} {line.amount:.2f}'


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
