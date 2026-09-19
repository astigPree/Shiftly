from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from zoneinfo import ZoneInfo


class Shift(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        CANCELLED = "CANCELLED", "Cancelled"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="shifts",
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="shifts",
    )
    work_date = models.DateField(help_text="Local calendar date the shift starts on.")
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    scheduled_break_minutes = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.SCHEDULED,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["work_date", "scheduled_start", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "work_date"],
                name="schedules_employee_work_date_unique",
            ),
            models.CheckConstraint(
                condition=Q(scheduled_end__gt=models.F("scheduled_start")),
                name="schedules_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["SCHEDULED", "CANCELLED"]),
                name="schedules_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "work_date"], name="schedules_org_date_idx"),
            models.Index(fields=["employee", "work_date"], name="schedules_employee_date_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.employee_id and self.organization_id:
            if self.employee.organization_id != self.organization_id:
                errors["employee"] = "The employee must belong to this organization."
        if self.scheduled_start and self.scheduled_end:
            if self.scheduled_end <= self.scheduled_start:
                errors["scheduled_end"] = "Shift end must be after shift start."
            elif self.scheduled_break_minutes * 60 > (self.scheduled_end - self.scheduled_start).total_seconds():
                errors["scheduled_break_minutes"] = "The break allowance cannot exceed the shift duration."
        if errors:
            raise ValidationError(errors)

    @property
    def scheduled_gross_minutes(self):
        return max(0, int((self.scheduled_end - self.scheduled_start).total_seconds() // 60))

    @property
    def scheduled_minutes(self):
        return max(0, self.scheduled_gross_minutes - self.scheduled_break_minutes)

    @property
    def is_overnight(self):
        zone = ZoneInfo(self.organization.timezone)
        return self.scheduled_end.astimezone(zone).date() != self.scheduled_start.astimezone(zone).date()

    def __str__(self):
        return f"{self.employee.full_name} · {self.work_date}"
