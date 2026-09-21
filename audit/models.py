from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Audit events are append-only.")

    def delete(self):
        raise ValidationError("Audit events are append-only.")


class AuditEvent(models.Model):
    class Action(models.TextChoices):
        ORGANIZATION_CREATED = "ORGANIZATION_CREATED", _("Organization created")
        ORGANIZATION_UPDATED = "ORGANIZATION_UPDATED", _("Organization settings updated")
        EMPLOYEE_CREATED = "EMPLOYEE_CREATED", _("Employee created")
        EMPLOYEE_UPDATED = "EMPLOYEE_UPDATED", _("Employee updated")
        EMPLOYEE_ACTIVATED = "EMPLOYEE_ACTIVATED", _("Employee activated")
        EMPLOYEE_DEACTIVATED = "EMPLOYEE_DEACTIVATED", _("Employee deactivated")
        SHIFT_CREATED = "SHIFT_CREATED", _("Shift created")
        SHIFT_UPDATED = "SHIFT_UPDATED", _("Shift updated")
        SHIFT_CANCELLED = "SHIFT_CANCELLED", _("Shift cancelled")
        TIMESHEET_APPROVED = "TIMESHEET_APPROVED", _("Timesheet approved")
        TIMESHEET_REJECTED = "TIMESHEET_REJECTED", _("Timesheet rejected")
        PAYROLL_RULES_UPDATED = "PAYROLL_RULES_UPDATED", _("Payroll rules updated")
        PAYROLL_PROFILE_UPDATED = "PAYROLL_PROFILE_UPDATED", _("Employee payroll profile updated")
        PAYROLL_RATE_ADDED = "PAYROLL_RATE_ADDED", _("Employee pay rate added")
        PAYROLL_RUN_CREATED = "PAYROLL_RUN_CREATED", _("Payroll run created")
        PAYROLL_RUN_RECALCULATED = "PAYROLL_RUN_RECALCULATED", _("Payroll run recalculated")
        PAYROLL_RUN_REVIEWED = "PAYROLL_RUN_REVIEWED", _("Payroll run submitted for review")
        PAYROLL_RUN_FINALIZED = "PAYROLL_RUN_FINALIZED", _("Payroll run finalized")
        PAYROLL_RUN_VOIDED = "PAYROLL_RUN_VOIDED", _("Payroll run voided")
        PAYROLL_ADJUSTMENT_ADDED = "PAYROLL_ADJUSTMENT_ADDED", _("Payroll adjustment added")
        PAYROLL_ADJUSTMENT_REMOVED = "PAYROLL_ADJUSTMENT_REMOVED", _("Payroll adjustment removed")
        PAYROLL_EXCEPTION_RESOLVED = "PAYROLL_EXCEPTION_RESOLVED", _("Payroll exception resolved")
        PAYROLL_EXPORT_ACCESSED = "PAYROLL_EXPORT_ACCESSED", _("Payroll export accessed")
        PAYROLL_STATEMENT_ACCESSED = "PAYROLL_STATEMENT_ACCESSED", _("Payroll statement accessed")

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    target_type = models.CharField(max_length=32)
    target_id = models.CharField(max_length=64)
    summary = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["organization", "-created_at"], name="audit_org_created_idx"),
            models.Index(fields=["organization", "action", "-created_at"], name="audit_org_action_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Audit events are append-only.")
        if not isinstance(self.metadata, dict):
            raise ValidationError({"metadata": "Audit metadata must be an object."})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit events are append-only.")

    def __str__(self):
        return f"{self.get_action_display()} · {self.target_type} {self.target_id}"
