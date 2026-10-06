import hashlib
import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .validators import validate_timezone


class OrganizationBiometricSettings(models.Model):
    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="biometric_settings",
    )
    enabled = models.BooleanField(default=False)
    default_sync_interval_seconds = models.PositiveIntegerField(default=120)
    early_clock_in_minutes = models.PositiveIntegerField(default=30)
    post_shift_capture_minutes = models.PositiveIntegerField(default=240)
    duplicate_window_seconds = models.PositiveIntegerField(default=60)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Biometric settings"

    def clean(self):
        super().clean()
        errors = {}
        if not 30 <= self.default_sync_interval_seconds <= 86400:
            errors["default_sync_interval_seconds"] = "Use a sync interval from 30 seconds to 24 hours."
        if self.early_clock_in_minutes > 720:
            errors["early_clock_in_minutes"] = "The early clock-in window cannot exceed 12 hours."
        if self.post_shift_capture_minutes > 1440:
            errors["post_shift_capture_minutes"] = "The post-shift capture window cannot exceed 24 hours."
        if self.duplicate_window_seconds > 3600:
            errors["duplicate_window_seconds"] = "The duplicate window cannot exceed one hour."
        if errors:
            raise ValidationError(errors)


class AttendanceDevice(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DISABLED = "DISABLED", "Disabled"

    class Health(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Unknown"
        HEALTHY = "HEALTHY", "Healthy"
        DEGRADED = "DEGRADED", "Needs attention"
        OFFLINE = "OFFLINE", "Offline"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="attendance_devices"
    )
    name = models.CharField(max_length=120)
    model = models.CharField(max_length=80, default="ZKTeco F7")
    host = models.GenericIPAddressField()
    port = models.PositiveIntegerField(default=4370)
    timezone = models.CharField(max_length=64, default="Asia/Manila", validators=[validate_timezone])
    communication_password_encrypted = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    health = models.CharField(max_length=10, choices=Health.choices, default=Health.UNKNOWN, db_index=True)
    sync_interval_seconds = models.PositiveIntegerField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_user_sync_at = models.DateTimeField(null=True, blank=True)
    last_punch_sync_at = models.DateTimeField(null=True, blank=True)
    last_successful_sync_at = models.DateTimeField(null=True, blank=True)
    sync_lock_until = models.DateTimeField(null=True, blank=True)
    firmware = models.CharField(max_length=120, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="biometric_device_org_name_unique"),
            models.CheckConstraint(check=Q(port__gte=1, port__lte=65535), name="biometric_device_valid_port"),
            models.CheckConstraint(check=Q(status__in=["ACTIVE", "DISABLED"]), name="biometric_device_status_valid"),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="bio_dev_org_status_idx"),
            models.Index(fields=["organization", "health"], name="bio_dev_org_health_idx"),
        ]

    @property
    def effective_sync_interval_seconds(self):
        settings = getattr(self.organization, "biometric_settings", None)
        return self.sync_interval_seconds or getattr(settings, "default_sync_interval_seconds", 120)

    @property
    def is_sync_locked(self):
        return bool(self.sync_lock_until and self.sync_lock_until > timezone.now())

    def clean(self):
        super().clean()
        if self.sync_interval_seconds and not 30 <= self.sync_interval_seconds <= 86400:
            raise ValidationError({"sync_interval_seconds": "Use a sync interval from 30 seconds to 24 hours."})
        if self.organization_id and self.timezone:
            validate_timezone(self.timezone)

    def __str__(self):
        return f"{self.name} ({self.host}:{self.port})"


class DeviceIdentity(models.Model):
    device = models.ForeignKey(AttendanceDevice, on_delete=models.PROTECT, related_name="identities")
    terminal_user_id = models.CharField(max_length=64)
    display_name = models.CharField(max_length=150, blank=True)
    fingerprint_enrolled = models.BooleanField(default=False)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["terminal_user_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["device", "terminal_user_id"], name="biometric_identity_device_user_unique"),
        ]

    @property
    def employee(self):
        assignment = self.assignments.filter(effective_from__lte=timezone.now()).filter(
            Q(effective_until__isnull=True) | Q(effective_until__gt=timezone.now())
        ).select_related("employee").first()
        return assignment.employee if assignment else None

    def __str__(self):
        return f"{self.device.name} · {self.terminal_user_id}"


class DeviceIdentityAssignment(models.Model):
    device_identity = models.ForeignKey(DeviceIdentity, on_delete=models.PROTECT, related_name="assignments")
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="biometric_assignments")
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField(null=True, blank=True)
    assigned_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="biometric_assignments_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-id"]
        indexes = [
            models.Index(fields=["device_identity", "effective_from"], name="biometric_assign_hist_idx"),
            models.Index(fields=["employee", "effective_from"], name="biometric_assign_emp_idx"),
        ]

    def clean(self):
        super().clean()
        if self.effective_until and self.effective_from and self.effective_until <= self.effective_from:
            raise ValidationError({"effective_until": "The end must be after the effective start."})
        if self.device_identity_id and self.employee_id:
            device_organization_id = DeviceIdentity.objects.filter(
                pk=self.device_identity_id
            ).values_list("device__organization_id", flat=True).first()
            employee_organization_id = self.employee.organization_id
            if device_organization_id and employee_organization_id and device_organization_id != employee_organization_id:
                raise ValidationError("The device and employee must belong to the same organization.")
        # A model instance can be partially populated while a ModelForm is
        # validating it.  Never dereference a missing relation descriptor.
        if self.device_identity_id and self.effective_from:
            overlapping = DeviceIdentityAssignment.objects.filter(
                device_identity_id=self.device_identity_id
            ).exclude(pk=self.pk)
            if self.effective_until:
                overlapping = overlapping.filter(effective_from__lt=self.effective_until)
            overlapping = overlapping.filter(
                Q(effective_until__isnull=True) | Q(effective_until__gt=self.effective_from)
            )
            if overlapping.exists():
                raise ValidationError("This terminal identity already has an overlapping assignment.")


class DeviceSyncRun(models.Model):
    class Kind(models.TextChoices):
        CONNECTION = "CONNECTION", "Connection test"
        USERS = "USERS", "User sync"
        PUNCHES = "PUNCHES", "Punch sync"

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        PARTIAL = "PARTIAL", "Partial"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Skipped"

    device = models.ForeignKey(AttendanceDevice, on_delete=models.PROTECT, related_name="sync_runs")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING, db_index=True)
    initiated_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="biometric_sync_runs")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    users_seen = models.PositiveIntegerField(default=0)
    punches_seen = models.PositiveIntegerField(default=0)
    punches_created = models.PositiveIntegerField(default=0)
    punches_duplicate = models.PositiveIntegerField(default=0)
    issues_created = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    diagnostics = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [models.Index(fields=["device", "-started_at"], name="biometric_sync_device_idx")]

    def finish(self, status, *, error_code="", error_message="", diagnostics=None, **counts):
        self.status = status
        self.finished_at = timezone.now()
        self.error_code = error_code
        self.error_message = error_message[:4000]
        if diagnostics is not None:
            self.diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        for field, value in counts.items():
            if field in {"users_seen", "punches_seen", "punches_created", "punches_duplicate", "issues_created"}:
                setattr(self, field, max(0, int(value or 0)))
        update_fields = ["status", "finished_at", "error_code", "error_message", *counts.keys()]
        if diagnostics is not None:
            update_fields.append("diagnostics")
        self.save(update_fields=update_fields)


class BiometricPunch(models.Model):
    device = models.ForeignKey(AttendanceDevice, on_delete=models.PROTECT, related_name="punches")
    device_identity = models.ForeignKey(DeviceIdentity, null=True, blank=True, on_delete=models.PROTECT, related_name="punches")
    identity_assignment = models.ForeignKey(DeviceIdentityAssignment, null=True, blank=True, on_delete=models.PROTECT, related_name="punches")
    sync_run = models.ForeignKey(DeviceSyncRun, on_delete=models.PROTECT, related_name="punches")
    device_record_id = models.CharField(max_length=128, blank=True)
    terminal_user_id = models.CharField(max_length=64)
    source_local_timestamp = models.CharField(max_length=64)
    source_timezone = models.CharField(max_length=64, validators=[validate_timezone])
    occurred_at = models.DateTimeField(db_index=True)
    canonical_key = models.CharField(max_length=128)
    payload_hash = models.CharField(max_length=64)
    raw_payload = models.JSONField(default=dict)
    imported_at = models.DateTimeField(auto_now_add=True)
    projection = models.ForeignKey("BiometricAttendanceProjection", null=True, blank=True, on_delete=models.PROTECT, related_name="punches")

    class Meta:
        ordering = ["occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["device", "canonical_key"], name="biometric_punch_device_key_unique"),
        ]
        indexes = [
            models.Index(fields=["device", "occurred_at"], name="bio_punch_device_time_idx"),
            models.Index(fields=["terminal_user_id", "occurred_at"], name="bio_punch_user_time_idx"),
        ]

    @classmethod
    def make_canonical_key(cls, *, device_record_id, terminal_user_id, occurred_at, status=""):
        if device_record_id:
            return f"record:{device_record_id}"
        value = "|".join([terminal_user_id, occurred_at.isoformat(), status or ""])
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


class BiometricAttendanceProjection(models.Model):
    class Status(models.TextChoices):
        COLLECTING = "COLLECTING", "Collecting"
        READY = "READY", "Ready"
        NEEDS_REVIEW = "NEEDS_REVIEW", "Needs review"
        MATERIALIZED = "MATERIALIZED", "Materialized"
        CONFLICT = "CONFLICT", "Source conflict"

    shift = models.OneToOneField("schedules.Shift", on_delete=models.PROTECT, related_name="biometric_projection")
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="biometric_projections")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COLLECTING, db_index=True)
    first_punch_at = models.DateTimeField(null=True, blank=True)
    last_punch_at = models.DateTimeField(null=True, blank=True)
    candidate_breaks = models.JSONField(default=list, blank=True)
    punch_count = models.PositiveIntegerField(default=0)
    issue_summary = models.TextField(blank=True)
    candidate_closed_at = models.DateTimeField(null=True, blank=True)
    materialized_session = models.OneToOneField("attendance.AttendanceSession", null=True, blank=True, on_delete=models.PROTECT, related_name="biometric_projection_materialized")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["employee", "status"], name="biometric_projection_emp_idx")]


class BiometricPunchIssue(models.Model):
    class Code(models.TextChoices):
        UNMAPPED_ID = "UNMAPPED_ID", "Unmapped terminal identity"
        NO_SHIFT = "NO_SHIFT", "No matching shift"
        AMBIGUOUS_SHIFT = "AMBIGUOUS_SHIFT", "Ambiguous shift"
        ODD_SEQUENCE = "ODD_SEQUENCE", "Incomplete punch sequence"
        OPEN_BREAK = "OPEN_BREAK", "Open break"
        LATE_EVIDENCE = "LATE_EVIDENCE", "Late evidence"
        SOURCE_CONFLICT = "SOURCE_CONFLICT", "Source conflict"
        CLOCK_DRIFT = "CLOCK_DRIFT", "Device clock drift"
        OFFLINE = "OFFLINE", "Device offline"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        RESOLVED = "RESOLVED", "Resolved"
        DISMISSED = "DISMISSED", "Dismissed"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="biometric_issues")
    device = models.ForeignKey(AttendanceDevice, null=True, blank=True, on_delete=models.PROTECT, related_name="issues")
    punch = models.ForeignKey(BiometricPunch, null=True, blank=True, on_delete=models.PROTECT, related_name="issues")
    projection = models.ForeignKey(BiometricAttendanceProjection, null=True, blank=True, on_delete=models.PROTECT, related_name="issues")
    employee = models.ForeignKey("employees.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="biometric_issues")
    code = models.CharField(max_length=20, choices=Code.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    summary = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="biometric_issues_resolved")

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "status"], name="biometric_issue_org_status_idx")]

    def resolve(self, actor, status=Status.RESOLVED):
        if status not in {self.Status.RESOLVED, self.Status.DISMISSED}:
            raise ValidationError("Use Resolved or Dismissed when closing an issue.")
        self.status = status
        self.resolved_by = actor
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_by", "resolved_at"])

