from django import forms

from employees.models import Employee
from .models import Timesheet, TimesheetApproval


class TimesheetFilterForm(forms.Form):
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    employee = forms.ModelChoiceField(queryset=Employee.objects.none(), required=False)
    status = forms.ChoiceField(
        required=False,
        choices=[("", "All statuses"), *Timesheet.Status.choices],
    )

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.filter(
            organization=organization
        ).order_by("last_name", "first_name")
        self.fields["employee"].empty_label = "All employees"

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date must be on or after start date.")
        return cleaned


class RejectTimesheetForm(forms.Form):
    comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Explain why this timesheet is rejected"}),
        label="Rejection comment",
    )

    def clean_comment(self):
        value = self.cleaned_data["comment"].strip()
        if not value:
            raise forms.ValidationError("A comment is required when rejecting a timesheet.")
        return value
