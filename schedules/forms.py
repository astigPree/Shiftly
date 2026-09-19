from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from employees.models import Employee
from .models import Shift
from .timeutils import local_datetime_to_utc


class ShiftForm(forms.Form):
    employee = forms.ModelChoiceField(queryset=Employee.objects.none())
    work_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    end_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    scheduled_break_minutes = forms.IntegerField(min_value=0, initial=0, label="Unpaid scheduled break allowance (minutes)")

    def __init__(self, *args, organization, instance=None, **kwargs):
        self.organization = organization
        self.instance = instance
        super().__init__(*args, **kwargs)
        employees = Employee.objects.filter(
            organization=organization,
            status=Employee.Status.ACTIVE,
        )
        if instance:
            employees = Employee.objects.filter(organization=organization).filter(
                Q(status=Employee.Status.ACTIVE) | Q(pk=instance.employee_id)
            )
        self.fields["employee"].queryset = employees.order_by("last_name", "first_name")
        if instance and not self.is_bound:
            self.initial.update(
                {
                    "employee": instance.employee_id,
                    "work_date": instance.work_date,
                    "start_time": instance.scheduled_start.astimezone(
                        ZoneInfo(organization.timezone)
                    ).time().replace(tzinfo=None),
                    "end_time": instance.scheduled_end.astimezone(
                        ZoneInfo(organization.timezone)
                    ).time().replace(tzinfo=None),
                    "scheduled_break_minutes": instance.scheduled_break_minutes,
                }
            )

    def clean(self):
        cleaned = super().clean()
        employee = cleaned.get("employee")
        work_date = cleaned.get("work_date")
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        break_minutes = cleaned.get("scheduled_break_minutes")
        if employee and employee.organization_id != self.organization.pk:
            self.add_error("employee", "Choose an employee from your organization.")
        if not all((work_date, start_time, end_time)):
            return cleaned
        if start_time == end_time:
            self.add_error("end_time", "Start and end times must be different.")
            return cleaned

        end_date = work_date + timedelta(days=1) if end_time < start_time else work_date
        start_local = datetime.combine(work_date, start_time)
        end_local = datetime.combine(end_date, end_time)
        try:
            start_utc = local_datetime_to_utc(start_local, self.organization.timezone)
        except ValidationError as error:
            self.add_error("start_time", error)
            start_utc = None
        try:
            end_utc = local_datetime_to_utc(end_local, self.organization.timezone)
        except ValidationError as error:
            self.add_error("end_time", error)
            end_utc = None
        if start_utc and end_utc:
            if end_utc <= start_utc:
                self.add_error("end_time", "The shift must have a positive elapsed duration.")
            elif break_minutes is not None and break_minutes * 60 > (end_utc - start_utc).total_seconds():
                self.add_error("scheduled_break_minutes", "The break allowance cannot exceed the shift duration.")
            else:
                cleaned["scheduled_start"] = start_utc
                cleaned["scheduled_end"] = end_utc
        return cleaned

    def save(self, commit=True):
        if not self.is_valid():
            raise ValueError("Cannot save an invalid shift form.")
        shift = self.instance or Shift()
        shift.organization = self.organization
        shift.employee = self.cleaned_data["employee"]
        shift.work_date = self.cleaned_data["work_date"]
        shift.scheduled_start = self.cleaned_data["scheduled_start"]
        shift.scheduled_end = self.cleaned_data["scheduled_end"]
        shift.scheduled_break_minutes = self.cleaned_data["scheduled_break_minutes"]
        if commit:
            shift.save()
        return shift
