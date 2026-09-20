from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Timesheet(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        NEEDS_REVIEW = "NEEDS_REVIEW", "Needs review"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="timesheets",
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="timesheets",
    )
    shift = models.OneToOneField(
        "schedules.Shift",
        on_delete=models.PROTECT,
        related_name="timesheet",
    )
    attendance_session = models.OneToOneField(
        "attendance.AttendanceSession",
        on_delete=models.PROTECT,
        related_name="timesheet",
    )
    scheduled_minutes = models.PositiveIntegerField(default=0)
    break_minutes = models.PositiveIntegerField(default=0)
    worked_minutes = models.PositiveIntegerField(default=0)
    payable_minutes = models.PositiveIntegerField(default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    undertime_minutes = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    review_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-shift__work_date", "-created_at"]
        constraints = [
            models.CheckConstraint(
                check=Q(status__in=["PENDING", "APPROVED", "REJECTED", "NEEDS_REVIEW"]),
                name="timesheets_status_valid",
            ),
            models.CheckConstraint(check=Q(scheduled_minutes__gte=0), name="timesheets_scheduled_nonneg"),
            models.CheckConstraint(check=Q(break_minutes__gte=0), name="timesheets_break_nonneg"),
            models.CheckConstraint(check=Q(worked_minutes__gte=0), name="timesheets_worked_nonneg"),
            models.CheckConstraint(check=Q(payable_minutes__gte=0), name="timesheets_payable_nonneg"),
            models.CheckConstraint(check=Q(late_minutes__gte=0), name="timesheets_late_nonneg"),
            models.CheckConstraint(check=Q(undertime_minutes__gte=0), name="timesheets_undertime_nonneg"),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="timesheets_org_status_idx"),
            models.Index(fields=["organization", "created_at"], name="timesheets_org_created_idx"),
            models.Index(fields=["employee", "created_at"], name="ts_emp_created_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.shift_id:
            if self.shift.employee_id != self.employee_id:
                errors["employee"] = "The employee must match the assigned shift."
            if self.shift.organization_id != self.organization_id:
                errors["organization"] = "The organization must match the assigned shift."
        if self.attendance_session_id:
            if self.attendance_session.shift_id != self.shift_id:
                errors["attendance_session"] = "The attendance session must belong to this shift."
            if self.attendance_session.clock_out_at is None:
                errors["attendance_session"] = "An incomplete attendance session cannot have a timesheet."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            prior = type(self).objects.get(pk=self.pk)
            immutable_fields = (
                "organization_id", "employee_id", "shift_id", "attendance_session_id",
                "scheduled_minutes", "break_minutes", "worked_minutes", "payable_minutes",
                "late_minutes", "undertime_minutes", "review_reason",
            )
            if any(getattr(prior, field) != getattr(self, field) for field in immutable_fields):
                raise ValidationError("Timesheet details cannot be edited after generation.")
            if prior.status in (self.Status.APPROVED, self.Status.REJECTED) and self.status != prior.status:
                raise ValidationError("Approved and rejected timesheets are terminal.")
            allowed = {
                self.Status.PENDING: {self.Status.PENDING, self.Status.APPROVED, self.Status.REJECTED},
                self.Status.NEEDS_REVIEW: {self.Status.NEEDS_REVIEW, self.Status.REJECTED},
                self.Status.APPROVED: {self.Status.APPROVED},
                self.Status.REJECTED: {self.Status.REJECTED},
            }
            if self.status not in allowed[prior.status]:
                raise ValidationError("This timesheet status transition is not allowed.")
        return super().save(*args, **kwargs)

    @property
    def local_work_date(self):
        return self.shift.work_date

    def __str__(self):
        return f"{self.employee.full_name} · {self.shift.work_date} · {self.get_status_display()}"


class TimesheetApproval(models.Model):
    class Action(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    timesheet = models.ForeignKey(Timesheet, on_delete=models.PROTECT, related_name="approvals")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="timesheet_reviews")
    action = models.CharField(max_length=10, choices=Action.choices)
    comment = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-reviewed_at", "-id"]
        constraints = [
            models.CheckConstraint(check=Q(action__in=["APPROVED", "REJECTED"]), name="timesheets_review_action_valid"),
            models.CheckConstraint(
                check=Q(action="APPROVED") | ~Q(comment=""),
                name="timesheets_rejection_comment_required",
            ),
        ]

    def clean(self):
        super().clean()
        if self.action == self.Action.REJECTED and not self.comment.strip():
            raise ValidationError({"comment": "A comment is required when rejecting a timesheet."})

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Timesheet review history is append-only.")
        if self.comment:
            self.comment = self.comment.strip()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Timesheet review history is append-only.")

    def __str__(self):
        return f"{self.get_action_display()} by {self.reviewer}"
