from django import forms

from employees.models import Employee
from timesheets.models import Timesheet


class OrganizationEmployeeFilterForm(forms.Form):
    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        field_name = "daily_employee" if "daily_employee" in self.fields else "employee"
        self.fields[field_name].queryset = Employee.objects.filter(
            organization=organization
        ).order_by("last_name", "first_name", "employee_code")


class DailyAttendanceFilterForm(OrganizationEmployeeFilterForm):
    daily_date = forms.DateField(
        label="Work date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    daily_employee = forms.ModelChoiceField(
        queryset=Employee.objects.none(), required=False, empty_label="All employees"
    )
    daily_status = forms.ChoiceField(
        label="Attendance status",
        required=False,
        choices=[
            ("", "All statuses"),
            ("SCHEDULED", "Scheduled"),
            ("LATE", "Late"),
            ("ABSENT", "Absent"),
            ("WORKING", "Working"),
            ("ON_BREAK", "On break"),
            ("COMPLETED", "Completed"),
            ("CANCELLED", "Cancelled"),
        ],
    )

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, organization=organization, **kwargs)
        self.fields["daily_employee"].widget.attrs["aria-label"] = "Employee"


class WeekReportFilterForm(forms.Form):
    week_of = forms.DateField(
        label="Week containing",
        widget=forms.DateInput(attrs={"type": "date"}),
    )


class TimesheetReportFilterForm(OrganizationEmployeeFilterForm):
    start_date = forms.DateField(
        label="From date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        label="To date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    employee = forms.ModelChoiceField(
        queryset=Employee.objects.none(), required=False, empty_label="All employees"
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "All statuses"), *Timesheet.Status.choices],
    )

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "The end date must be on or after the start date.")
        return cleaned
