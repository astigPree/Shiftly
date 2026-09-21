from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from employees.models import Employee
from .models import Shift
from .timeutils import local_datetime_to_utc


class ShiftForm(forms.Form):
    employee = forms.ModelChoiceField(
        queryset=Employee.objects.none(),
        label="Employee",
        help_text="Choose an active employee in this organization.",
    )
    employees = forms.CharField(
        required=False,
        label="Employees",
        help_text="Choose one or more active employees for this shift.",
        widget=forms.HiddenInput(attrs={"data-employee-selection-input": ""}),
    )
    work_date = forms.DateField(
        label="Work date",
        help_text="The local calendar date the shift starts on.",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    start_time = forms.TimeField(
        label="Start time", widget=forms.TimeInput(attrs={"type": "time"})
    )
    end_time = forms.TimeField(
        label="End time",
        help_text="If this is earlier than the start time, the shift ends the next day. Example: 10:00 PM to 3:00 AM.",
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    scheduled_break_minutes = forms.IntegerField(
        min_value=0,
        initial=0,
        label="Unpaid break allowance (minutes)",
        help_text="Subtracted from scheduled minutes when the shift is calculated.",
    )

    def __init__(self, *args, organization, instance=None, **kwargs):
        self.organization = organization
        self.instance = instance
        super().__init__(*args, **kwargs)
        employees = Employee.objects.filter(
            organization=organization,
            status=Employee.Status.ACTIVE,
        )
        if instance:
            self.fields.pop("employees")
            employees = Employee.objects.filter(organization=organization).filter(
                Q(status=Employee.Status.ACTIVE) | Q(pk=instance.employee_id)
            )
            self.fields["employee"].queryset = employees.order_by("last_name", "first_name")
        else:
            self.fields.pop("employee")
            self.employee_queryset = employees.order_by("last_name", "first_name", "pk")
            self.employee_options = list(self.employee_queryset)
            if self.is_bound:
                try:
                    selected = json.loads(self.data.get(self.add_prefix("employees"), ""))
                    if not isinstance(selected, list):
                        selected = []
                except (TypeError, ValueError):
                    selected = []
            else:
                selected = self.initial.get("employees", [])
                if isinstance(selected, str):
                    try:
                        selected = json.loads(selected)
                    except ValueError:
                        selected = [selected]
                    if not isinstance(selected, (list, tuple, set)):
                        selected = [selected]
                elif not isinstance(selected, (list, tuple, set)):
                    selected = [selected]
            self.selected_employee_ids = {str(value) for value in selected if value}
            self.initial["employees"] = json.dumps(sorted(self.selected_employee_ids))
            for option in self.employee_options:
                option.is_selected = str(option.pk) in self.selected_employee_ids
            self.employee_conflicts = {}
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
        if self.instance:
            selected_employees = [employee] if employee else []
        else:
            raw_employee_ids = cleaned.get("employees", "")
            try:
                employee_ids = json.loads(raw_employee_ids or "[]")
            except (TypeError, ValueError):
                employee_ids = None
            if not isinstance(employee_ids, list) or any(
                not isinstance(value, (str, int)) for value in employee_ids
            ):
                self.add_error("employees", "Choose employees from the list.")
                selected_employees = []
            else:
                employee_ids = list(dict.fromkeys(str(value) for value in employee_ids))
                if not employee_ids:
                    self.add_error("employees", "Select at least one employee.")
                    selected_employees = []
                else:
                    employees_by_id = {
                        str(person.pk): person
                        for person in self.employee_queryset.filter(pk__in=employee_ids)
                    }
                    if len(employees_by_id) != len(employee_ids):
                        self.add_error(
                            "employees",
                            "One or more selected employees are no longer active in this organization. Refresh the page and select them again.",
                        )
                        selected_employees = []
                    else:
                        selected_employees = [employees_by_id[value] for value in employee_ids]
                        cleaned["employees"] = selected_employees
        work_date = cleaned.get("work_date")
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        break_minutes = cleaned.get("scheduled_break_minutes")
        employee_field = "employee" if self.instance else "employees"
        if any(
            selected.organization_id != self.organization.pk
            for selected in selected_employees
        ):
            self.add_error(employee_field, "Choose employees from your organization.")
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
                if not self.instance and selected_employees:
                    conflicts = (
                        Shift.objects.filter(
                            organization=self.organization,
                            employee__in=selected_employees,
                        )
                        .filter(
                            Q(work_date=work_date)
                            | Q(
                                status=Shift.Status.SCHEDULED,
                                scheduled_start__lt=end_utc,
                                scheduled_end__gt=start_utc,
                            )
                        )
                        .select_related("employee")
                    )
                    conflict_rows = list(conflicts)
                    conflict_messages = {}
                    for existing in conflict_rows:
                        if existing.work_date == work_date:
                            conflict_messages[existing.employee_id] = (
                                "Already has a shift on this work date."
                            )
                    for existing in conflict_rows:
                        if existing.employee_id not in conflict_messages:
                            conflict_messages[existing.employee_id] = (
                                "Overlaps another scheduled shift."
                            )
                    self.employee_conflicts = conflict_messages
                    for option in self.employee_options:
                        option.schedule_conflict = conflict_messages.get(option.pk, "")
                    selected_conflicts = [
                        f"{person.full_name}: {conflict_messages[person.pk]}"
                        for person in selected_employees
                        if person.pk in conflict_messages
                    ]
                    if selected_conflicts:
                        conflict_summary = "; ".join(selected_conflicts[:4])
                        if len(selected_conflicts) > 4:
                            conflict_summary += (
                                f"; and {len(selected_conflicts) - 4} more."
                            )
                        self.add_error(
                            "employees",
                            "Some selected employees cannot be scheduled. "
                            + conflict_summary
                            + " Remove them or change the shift details. No shifts were created.",
                        )
        return cleaned

    def save(self, commit=True):
        if not self.is_valid():
            raise ValueError("Cannot save an invalid shift form.")
        if self.instance is None:
            raise ValueError("Use create_shifts() to save a new shift assignment.")
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
