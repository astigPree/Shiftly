from django import forms

from employees.models import Employee
from .models import Shift


class ShiftFilterForm(forms.Form):
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    employee = forms.ModelChoiceField(queryset=Employee.objects.none(), required=False)
    status = forms.ChoiceField(required=False, choices=[("", "All statuses"), *Shift.Status.choices])

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.filter(
            organization=organization
        ).order_by("last_name", "first_name")

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date must be on or after start date.")
        return cleaned
