from datetime import timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone


_DATETIME_FORMAT = "%Y-%m-%dT%H:%M"


class AttendanceCorrectionForm(forms.Form):
    """Employer form for correcting effective attendance values in local time."""

    clock_in_at = forms.DateTimeField(
        label="Corrected clock-in",
        input_formats=[_DATETIME_FORMAT],
        widget=forms.DateTimeInput(
            format=_DATETIME_FORMAT,
            attrs={"type": "datetime-local", "autocomplete": "off"},
        ),
    )
    clock_out_at = forms.DateTimeField(
        label="Corrected clock-out",
        input_formats=[_DATETIME_FORMAT],
        widget=forms.DateTimeInput(
            format=_DATETIME_FORMAT,
            attrs={"type": "datetime-local", "autocomplete": "off"},
        ),
    )
    reason = forms.CharField(
        label="Correction reason",
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": 500}),
        help_text="Required for payroll audit. Describe what was corrected and why.",
    )

    def __init__(self, *args, timezone_name="UTC", initial_breaks=None, **kwargs):
        self.work_timezone = ZoneInfo(timezone_name)
        self.break_rows = []
        super().__init__(*args, **kwargs)

        initial_breaks = list(initial_breaks or [])
        row_count = max(3, len(initial_breaks))
        # Keep the editor compact for the common one-break/no-break case. The
        # remaining rows are still part of the form so a correction can add up
        # to three intervals without another request.
        self.visible_break_rows = max(1, len(initial_breaks))
        if self.is_bound:
            for index in range(row_count):
                start_name = f"break_{index + 1}_start"
                end_name = f"break_{index + 1}_end"
                if self.data.get(start_name) or self.data.get(end_name):
                    self.visible_break_rows = max(self.visible_break_rows, index + 1)
        for index in range(row_count):
            start_name = f"break_{index + 1}_start"
            end_name = f"break_{index + 1}_end"
            self.fields[start_name] = forms.DateTimeField(
                label=f"Break {index + 1} start",
                required=False,
                input_formats=[_DATETIME_FORMAT],
                widget=forms.DateTimeInput(
                    format=_DATETIME_FORMAT,
                    attrs={"type": "datetime-local", "autocomplete": "off"},
                ),
            )
            self.fields[end_name] = forms.DateTimeField(
                label=f"Break {index + 1} end",
                required=False,
                input_formats=[_DATETIME_FORMAT],
                widget=forms.DateTimeInput(
                    format=_DATETIME_FORMAT,
                    attrs={"type": "datetime-local", "autocomplete": "off"},
                ),
            )
            self.break_rows.append((start_name, end_name))
            if index < len(initial_breaks):
                break_item = initial_breaks[index]
                self.initial[start_name] = self._format_initial(break_item[0])
                self.initial[end_name] = self._format_initial(break_item[1])
        self.break_fields = [(self[start_name], self[end_name]) for start_name, end_name in self.break_rows]

    def _format_initial(self, value):
        if value is None:
            return ""
        if timezone.is_naive(value):
            value = timezone.make_aware(value, datetime_timezone.utc)
        return timezone.localtime(value, self.work_timezone).strftime(_DATETIME_FORMAT)

    def _localize(self, value):
        if value is None:
            return None
        # ``datetime-local`` contains a wall-clock value with no offset. Django
        # attaches the project timezone (UTC here) while cleaning a
        # DateTimeField, so do not trust that attached offset. Interpret the
        # submitted wall-clock value in the employee's work timezone first.
        wall_clock = value.replace(tzinfo=None) if timezone.is_aware(value) else value
        return timezone.make_aware(wall_clock, self.work_timezone).astimezone(datetime_timezone.utc)

    def clean(self):
        cleaned = super().clean()
        clock_in = self._localize(cleaned.get("clock_in_at"))
        clock_out = self._localize(cleaned.get("clock_out_at"))
        if clock_in and clock_out and clock_out <= clock_in:
            self.add_error("clock_out_at", "Clock-out must be after clock-in.")

        breaks = []
        for start_name, end_name in self.break_rows:
            start_value = cleaned.get(start_name)
            end_value = cleaned.get(end_name)
            if not start_value and not end_value:
                continue
            if not start_value:
                self.add_error(start_name, "Enter the break start or clear both break fields.")
                continue
            if not end_value:
                self.add_error(end_name, "Enter the break end or clear both break fields.")
                continue
            start = self._localize(start_value)
            end = self._localize(end_value)
            if end <= start:
                self.add_error(end_name, "Break end must be after its start.")
                continue
            if clock_in and start < clock_in:
                self.add_error(start_name, "Break must start after clock-in.")
            if clock_out and end > clock_out:
                self.add_error(end_name, "Break must end before clock-out.")
            breaks.append((start, end))

        ordered = sorted(breaks, key=lambda item: item[0])
        for previous, current in zip(ordered, ordered[1:]):
            if current[0] < previous[1]:
                self.add_error("reason", "Break intervals cannot overlap.")
                break

        cleaned["corrected_clock_in_at"] = clock_in
        cleaned["corrected_clock_out_at"] = clock_out
        cleaned["corrected_breaks"] = ordered
        reason = (cleaned.get("reason") or "").strip()
        if reason and len(reason) < 5:
            self.add_error("reason", "Give a little more detail so the correction can be audited.")
        cleaned["reason"] = reason
        return cleaned

