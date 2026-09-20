from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class AttendanceSession(models.Model):
    class Status(models.TextChoices):
        WORKING = "WORKING", "Working"
        ON_BREAK = "ON_BREAK", "On break"
        COMPLETED = "COMPLETED", "Completed"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="attendance_sessions",
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="attendance_sessions",
    )
    shift = models.OneToOneField(
        "schedules.Shift",
        on_delete=models.PROTECT,
        related_name="attendance_session",
    )
    clock_in_at = models.DateTimeField()
    clock_out_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.WORKING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-clock_in_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(clock_out_at__isnull=True) | Q(clock_out_at__gt=models.F("clock_in_at")),
                name="attendance_clockout_after_clockin",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="COMPLETED", clock_out_at__isnull=False)
                    | Q(status__in=["WORKING", "ON_BREAK"], clock_out_at__isnull=True)
                ),
                name="attendance_status_clockout_consistent",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["WORKING", "ON_BREAK", "COMPLETED"]),
                name="attendance_status_valid",
            ),
            models.UniqueConstraint(
                fields=["employee"],
                condition=Q(clock_out_at__isnull=True),
                name="attendance_one_open_per_employee",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="attendance_org_status_idx"),
            models.Index(fields=["employee", "clock_in_at"], name="attendance_employee_in_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.shift_id and self.employee_id and self.shift.employee_id != self.employee_id:
            errors["employee"] = "The attendance employee must match the assigned shift."
        if self.shift_id and self.organization_id and self.shift.organization_id != self.organization_id:
            errors["organization"] = "The attendance organization must match the shift."
        if self.clock_in_at and self.clock_out_at and self.clock_out_at <= self.clock_in_at:
            errors["clock_out_at"] = "Clock-out must be after clock-in."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            prior = type(self).objects.only("clock_in_at", "clock_out_at").get(pk=self.pk)
            if self.clock_in_at != prior.clock_in_at:
                raise ValidationError({"clock_in_at": "The original clock-in timestamp is immutable."})
            if prior.clock_out_at is not None and self.clock_out_at != prior.clock_out_at:
                raise ValidationError({"clock_out_at": "The original clock-out timestamp is immutable."})
        return super().save(*args, **kwargs)

    @property
    def missing_clock_out(self):
        from django.utils import timezone

        return self.clock_out_at is None and timezone.now() >= self.shift.scheduled_end

    def __str__(self):
        return f"Attendance for {self.employee.full_name} on {self.shift.work_date}"


class BreakSession(models.Model):
    attendance_session = models.ForeignKey(
        AttendanceSession,
        on_delete=models.PROTECT,
        related_name="breaks",
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["started_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gt=models.F("started_at")),
                name="attendance_break_end_after_start",
            ),
            models.UniqueConstraint(
                fields=["attendance_session"],
                condition=Q(ended_at__isnull=True),
                name="attendance_one_open_break",
            ),
        ]
        indexes = [models.Index(fields=["attendance_session", "started_at"], name="attendance_break_order_idx")]

    def clean(self):
        super().clean()
        if self.started_at and self.ended_at and self.ended_at <= self.started_at:
            raise ValidationError({"ended_at": "A break must end after it starts."})

    def save(self, *args, **kwargs):
        if self.pk:
            prior = type(self).objects.only("started_at", "ended_at").get(pk=self.pk)
            if self.started_at != prior.started_at:
                raise ValidationError({"started_at": "The original break start timestamp is immutable."})
            if prior.ended_at is not None and self.ended_at != prior.ended_at:
                raise ValidationError({"ended_at": "The original break end timestamp is immutable."})
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Break started {self.started_at}"
