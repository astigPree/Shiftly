from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from employees.models import Employee
from .models import Shift
from .timeutils import local_datetime_to_utc


MAX_BULK_SHIFT_DATES = 90
MAX_BULK_SHIFT_ASSIGNMENTS = 1000


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
    work_dates = forms.CharField(
        required=False,
        label="Work dates",
        help_text="Choose one or more dates for the same shift.",
        widget=forms.HiddenInput(attrs={"data-work-date-selection-input": ""}),
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
            self.fields.pop("work_dates")
            employees = Employee.objects.filter(organization=organization).filter(
                Q(status=Employee.Status.ACTIVE) | Q(pk=instance.employee_id)
            )
            self.fields["employee"].queryset = employees.order_by("last_name", "first_name")
        else:
            self.fields.pop("employee")
            self.fields.pop("work_date")
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
            self.date_conflict_counts = {}
            self.date_conflict_data = "{}"
            self.calendar_today = datetime.now(ZoneInfo(organization.timezone)).date()
            self.max_bulk_shift_dates = MAX_BULK_SHIFT_DATES
            self.max_bulk_shift_assignments = MAX_BULK_SHIFT_ASSIGNMENTS
            if self.is_bound:
                try:
                    selected_dates = json.loads(
                        self.data.get(self.add_prefix("work_dates"), "")
                    )
                    if not isinstance(selected_dates, list):
                        selected_dates = []
                except (TypeError, ValueError):
                    selected_dates = []
            else:
                selected_dates = self.initial.get("work_dates", [])
                if isinstance(selected_dates, str):
                    try:
                        selected_dates = json.loads(selected_dates)
                    except ValueError:
                        selected_dates = [selected_dates]
                if not isinstance(selected_dates, (list, tuple, set)):
                    selected_dates = [selected_dates]
            self.selected_work_dates = sorted(
                {
                    value.isoformat() if isinstance(value, date) else str(value)
                    for value in selected_dates
                    if value
                }
            )
            self.initial["work_dates"] = json.dumps(self.selected_work_dates)
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
            work_dates = [cleaned["work_date"]] if cleaned.get("work_date") else []
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

            raw_work_dates = cleaned.get("work_dates", "")
            try:
                date_values = json.loads(raw_work_dates or "[]")
            except (TypeError, ValueError):
                date_values = None
            if not isinstance(date_values, list) or any(
                not isinstance(value, str) for value in date_values
            ):
                self.add_error("work_dates", "Choose work dates from the calendar.")
                work_dates = []
            else:
                work_dates = []
                invalid_dates = []
                for value in dict.fromkeys(date_values):
                    try:
                        parsed_date = date.fromisoformat(value)
                    except ValueError:
                        invalid_dates.append(value)
                        continue
                    if parsed_date.isoformat() != value:
                        invalid_dates.append(value)
                    else:
                        work_dates.append(parsed_date)
                self.selected_work_dates = [
                    selected_date.isoformat() for selected_date in work_dates
                ]
                if invalid_dates:
                    self.add_error(
                        "work_dates",
                        "One or more selected dates are invalid. Choose them again in the calendar.",
                    )
                if not work_dates:
                    self.add_error("work_dates", "Choose at least one work date.")
                elif len(work_dates) > MAX_BULK_SHIFT_DATES:
                    self.add_error(
                        "work_dates",
                        f"Choose no more than {MAX_BULK_SHIFT_DATES} dates at a time.",
                    )
                else:
                    cleaned["work_dates"] = work_dates

        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        break_minutes = cleaned.get("scheduled_break_minutes")
        employee_field = "employee" if self.instance else "employees"
        if any(
            selected.organization_id != self.organization.pk
            for selected in selected_employees
        ):
            self.add_error(employee_field, "Choose employees from your organization.")
        if self.errors:
            return cleaned
        if not all((work_dates, start_time, end_time)):
            return cleaned
        if start_time == end_time:
            self.add_error("end_time", "Start and end times must be different.")
            return cleaned

        shift_intervals = []
        interval_errors = []
        for work_date in work_dates:
            end_date = work_date + timedelta(days=1) if end_time < start_time else work_date
            start_local = datetime.combine(work_date, start_time)
            end_local = datetime.combine(end_date, end_time)
            try:
                start_utc = local_datetime_to_utc(
                    start_local, self.organization.timezone
                )
            except ValidationError as error:
                if self.instance:
                    self.add_error("start_time", error)
                else:
                    interval_errors.append(
                        f"{work_date.isoformat()} start: {' '.join(error.messages)}"
                    )
                continue
            try:
                end_utc = local_datetime_to_utc(end_local, self.organization.timezone)
            except ValidationError as error:
                if self.instance:
                    self.add_error("end_time", error)
                else:
                    interval_errors.append(
                        f"{work_date.isoformat()} end: {' '.join(error.messages)}"
                    )
                continue

            if end_utc <= start_utc:
                if self.instance:
                    self.add_error(
                        "end_time", "The shift must have a positive elapsed duration."
                    )
                else:
                    interval_errors.append(
                        f"{work_date.isoformat()}: the shift duration is invalid."
                    )
                continue
            if (
                break_minutes is not None
                and break_minutes * 60 > (end_utc - start_utc).total_seconds()
            ):
                if self.instance:
                    self.add_error(
                        "scheduled_break_minutes",
                        "The break allowance cannot exceed the shift duration.",
                    )
                else:
                    interval_errors.append(
                        f"{work_date.isoformat()}: the break exceeds the shift duration."
                    )
                continue
            shift_intervals.append(
                {
                    "work_date": work_date,
                    "scheduled_start": start_utc,
                    "scheduled_end": end_utc,
                }
            )

        if interval_errors:
            self.add_error(
                "work_dates",
                "Some dates cannot use this shift time: "
                + "; ".join(interval_errors[:5])
                + (f"; and {len(interval_errors) - 5} more." if len(interval_errors) > 5 else ""),
            )
        if self.errors or len(shift_intervals) != len(work_dates):
            return cleaned

        if self.instance:
            cleaned["scheduled_start"] = shift_intervals[0]["scheduled_start"]
            cleaned["scheduled_end"] = shift_intervals[0]["scheduled_end"]
            return cleaned

        cleaned["shift_intervals"] = shift_intervals
        planned_count = len(selected_employees) * len(shift_intervals)
        if planned_count > MAX_BULK_SHIFT_ASSIGNMENTS:
            self.add_error(
                "work_dates",
                f"This selection would create {planned_count} shifts. Schedule no more than {MAX_BULK_SHIFT_ASSIGNMENTS} shifts at a time; remove some employees or dates.",
            )
            return cleaned

        if selected_employees:
            nearby_dates = {
                work_date + timedelta(days=offset)
                for work_date in work_dates
                for offset in (-1, 0, 1)
            }
            existing_by_employee_date = {}
            existing_shifts = (
                Shift.objects.filter(
                    organization=self.organization,
                    employee__in=selected_employees,
                    work_date__in=nearby_dates,
                )
                .select_related("employee")
            )
            for existing in existing_shifts:
                existing_by_employee_date.setdefault(
                    (existing.employee_id, existing.work_date), []
                ).append(existing)

            conflict_details = {}
            for interval in shift_intervals:
                work_date = interval["work_date"]
                date_issues = []
                for person in selected_employees:
                    nearby_shifts = [
                        existing
                        for offset in (-1, 0, 1)
                        for existing in existing_by_employee_date.get(
                            (person.pk, work_date + timedelta(days=offset)), []
                        )
                    ]
                    if any(existing.work_date == work_date for existing in nearby_shifts):
                        date_issues.append(
                            f"{person.full_name}: already has a shift on this work date."
                        )
                    elif any(
                        existing.status == Shift.Status.SCHEDULED
                        and existing.scheduled_start < interval["scheduled_end"]
                        and existing.scheduled_end > interval["scheduled_start"]
                        for existing in nearby_shifts
                    ):
                        date_issues.append(
                            f"{person.full_name}: overlaps another scheduled shift."
                        )
                if date_issues:
                    conflict_details[work_date.isoformat()] = date_issues

            self.date_conflict_counts = {
                date_string: len(details)
                for date_string, details in conflict_details.items()
            }
            self.date_conflict_data = json.dumps(self.date_conflict_counts)
            if conflict_details:
                conflict_summary = []
                for date_string, details in list(conflict_details.items())[:5]:
                    conflict_summary.append(
                        f"{date_string}: {len(details)} employee conflict"
                        f"{'s' if len(details) != 1 else ''}"
                    )
                details_preview = [
                    f"{date_string} — {detail}"
                    for date_string, details in conflict_details.items()
                    for detail in details
                ][:5]
                self.add_error(
                    "work_dates",
                    "Some employee and date combinations conflict. "
                    + "; ".join(conflict_summary)
                    + ". "
                    + " ".join(details_preview)
                    + " Remove a conflicting employee or date. No shifts were created.",
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
