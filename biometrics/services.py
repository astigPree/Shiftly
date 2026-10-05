"""Device adapters, immutable punch import, and attendance reconciliation.

The adapter is deliberately small: the rest of Shiftly only consumes DTOs and
never depends on the vendor SDK.  This makes a real F7 proof replaceable with
another terminal provider and keeps tests deterministic.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from attendance.models import AttendanceSession, BreakSession
from employees.models import Employee
from schedules.models import Shift

from .models import (
    AttendanceDevice,
    BiometricAttendanceProjection,
    BiometricPunch,
    BiometricPunchIssue,
    DeviceIdentity,
    DeviceIdentityAssignment,
    DeviceSyncRun,
)


class BiometricDeviceError(Exception):
    """A safe, operator-facing device error without credentials."""


class BiometricConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class DeviceInfo:
    firmware: str = ""
    serial_number: str = ""
    model: str = ""


@dataclass(frozen=True)
class DeviceUser:
    terminal_user_id: str
    display_name: str = ""
    fingerprint_enrolled: bool = False


@dataclass(frozen=True)
class DevicePunch:
    terminal_user_id: str
    occurred_at: datetime
    source_local_timestamp: str
    source_timezone: str
    device_record_id: str = ""
    status: str = ""
    raw_payload: dict | None = None


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as error:
        raise BiometricConfigurationError(
            "Install the cryptography package before saving biometric device credentials."
        ) from error
    configured = getattr(settings, "BIOMETRIC_CREDENTIAL_KEY", "") or ""
    if not configured:
        if not getattr(settings, "DEBUG", False):
            raise BiometricConfigurationError(
                "Set BIOMETRIC_CREDENTIAL_KEY before storing biometric device credentials in production."
            )
        # Development fallback keeps local setup usable while deployments can
        # require a dedicated key through the settings environment variable.
        configured = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        import base64

        configured = base64.urlsafe_b64encode(configured)
    try:
        return Fernet(configured)
    except Exception as error:
        raise BiometricConfigurationError("BIOMETRIC_CREDENTIAL_KEY is not a valid Fernet key.") from error


def encrypt_password(password: str) -> str:
    if not password:
        return ""
    return _fernet().encrypt(password.encode("utf-8")).decode("ascii")


def decrypt_password(device: AttendanceDevice) -> str:
    if not device.communication_password_encrypted:
        return ""
    try:
        return _fernet().decrypt(device.communication_password_encrypted.encode("ascii")).decode("utf-8")
    except Exception as error:
        raise BiometricConfigurationError("The saved device credential could not be decrypted.") from error


def _operator_required(actor, organization):
    if actor is None:
        return
    if not getattr(actor, "is_authenticated", False) or getattr(actor, "role", None) != "EMPLOYER":
        raise PermissionDenied("Only an employer can manage biometric devices.")
    if getattr(getattr(actor, "organization", None), "pk", None) != organization.pk:
        raise PermissionDenied("The device belongs to another organization.")


class ZKTecoF7Adapter:
    """Best-effort pyzk adapter for ZKTeco F7 terminals.

    pyzk is optional at import time; a connection test gives a clear setup
    error until the office environment installs and proves the SDK/firmware.
    """

    def __init__(self, device: AttendanceDevice):
        self.device = device
        self._connection = None

    def _connect(self):
        try:
            from zk import ZK
        except ImportError as error:
            raise BiometricDeviceError("The F7 adapter is not installed on this server (missing pyzk).") from error
        try:
            client = ZK(
                self.device.host,
                port=self.device.port,
                password=int(decrypt_password(self.device) or 0),
                timeout=8,
                ommit_ping=False,
            )
            self._connection = client.connect()
            return self._connection
        except Exception as error:
            raise BiometricDeviceError(f"Could not reach {self.device.name} at {self.device.host}:{self.device.port}.") from error

    def close(self):
        if self._connection is not None:
            try:
                self._connection.disconnect()
            except Exception:
                pass
            self._connection = None

    def test_connection(self):
        connection = self._connect()
        try:
            firmware = str(getattr(connection, "get_device_name", lambda: "")() or "")
            serial = str(getattr(connection, "get_serialnumber", lambda: "")() or "")
            return DeviceInfo(firmware=firmware, serial_number=serial, model=self.device.model)
        finally:
            self.close()

    def list_users(self):
        connection = self._connect()
        try:
            users = []
            for item in connection.get_users() or []:
                terminal_id = str(getattr(item, "user_id", None) or getattr(item, "uid", "")).strip()
                if not terminal_id:
                    continue
                users.append(DeviceUser(
                    terminal_user_id=terminal_id,
                    display_name=str(getattr(item, "name", "") or "").strip(),
                    fingerprint_enrolled=bool(getattr(item, "fingerprint", None) or getattr(item, "fingerprint_count", 0)),
                ))
            return users
        except Exception as error:
            raise BiometricDeviceError(f"{self.device.name} returned an invalid user list.") from error
        finally:
            self.close()

    def list_punches(self, since=None):
        connection = self._connect()
        try:
            rows = []
            for item in connection.get_attendance() or []:
                local_value = getattr(item, "timestamp", None) or getattr(item, "time", None)
                if not isinstance(local_value, datetime):
                    continue
                tz = ZoneInfo(self.device.timezone)
                local_value = local_value.replace(tzinfo=tz) if local_value.tzinfo is None else local_value.astimezone(tz)
                occurred_at = local_value.astimezone(dt_timezone.utc)
                if since and occurred_at < since:
                    continue
                terminal_id = str(getattr(item, "user_id", None) or getattr(item, "uid", "")).strip()
                if not terminal_id:
                    continue
                record_id = str(getattr(item, "id", None) or getattr(item, "record_id", "") or "").strip()
                status = str(getattr(item, "status", None) or getattr(item, "punch", "") or "").strip()
                rows.append(DevicePunch(
                    terminal_user_id=terminal_id,
                    occurred_at=occurred_at,
                    source_local_timestamp=local_value.strftime("%Y-%m-%d %H:%M:%S"),
                    source_timezone=self.device.timezone,
                    device_record_id=record_id,
                    status=status,
                    raw_payload={"user_id": terminal_id, "timestamp": local_value.isoformat(), "status": status, "record_id": record_id},
                ))
            return rows
        except Exception as error:
            raise BiometricDeviceError(f"{self.device.name} returned an invalid attendance list.") from error
        finally:
            self.close()


def adapter_for(device):
    if device.model.lower().startswith("zkteco") or device.model.lower().startswith("f7"):
        return ZKTecoF7Adapter(device)
    raise BiometricDeviceError(f"No adapter is available for {device.model}.")


@transaction.atomic
def assign_identity(*, identity, employee, effective_from, effective_until=None, actor):
    """Create a historical terminal-to-employee assignment.

    Closing the current assignment is explicit and preserves all previously
    imported punches against their original assignment row.
    """
    _operator_required(actor, identity.device.organization)
    if employee.organization_id != identity.device.organization_id:
        raise ValidationError("The employee and terminal must belong to the same organization.")
    assignment = DeviceIdentityAssignment(
        device_identity=identity,
        employee=employee,
        effective_from=effective_from,
        effective_until=effective_until,
        assigned_by=actor,
    )
    assignment.full_clean()
    assignment.save()
    # A user may have been mapped after the terminal sync.  Resolve existing
    # immutable punches into this historical assignment without rewriting any
    # raw evidence.
    pending = BiometricPunch.objects.filter(
        device_identity=identity,
        identity_assignment__isnull=True,
        occurred_at__gte=assignment.effective_from,
    )
    if assignment.effective_until:
        pending = pending.filter(occurred_at__lt=assignment.effective_until)
    pending_rows = list(pending)
    pending.update(identity_assignment=assignment)
    for punch in pending_rows:
        punch.identity_assignment = assignment
        projection = projection_for_punch(punch)
        if projection:
            reconcile_biometric_projection(projection.shift)
    return assignment


def _resolve_assignment(identity, occurred_at):
    return DeviceIdentityAssignment.objects.filter(
        device_identity=identity,
        effective_from__lte=occurred_at,
    ).filter(Q(effective_until__isnull=True) | Q(effective_until__gt=occurred_at)).select_related("employee").first()


def _device_lock(device):
    # Lock acquisition is its own short transaction.  The longer network call
    # must not hold a database transaction open, and failure reporting must be
    # committed even when the adapter raises.
    with transaction.atomic():
        device = AttendanceDevice.objects.select_for_update().select_related("organization").get(pk=device.pk)
        if device.sync_lock_until and device.sync_lock_until > timezone.now():
            return None
        device.sync_lock_until = timezone.now() + timedelta(minutes=10)
        device.save(update_fields=["sync_lock_until", "updated_at"])
        return device


def sync_device_users(device, *, actor=None, adapter=None):
    _operator_required(actor, device.organization)
    device = _device_lock(device)
    if device is None:
        return {"status": DeviceSyncRun.Status.SKIPPED, "reason": "another sync is already running"}
    run = DeviceSyncRun.objects.create(device=device, kind=DeviceSyncRun.Kind.USERS, initiated_by=actor)
    adapter = adapter or adapter_for(device)
    try:
        users = adapter.list_users()
        now = timezone.now()
        for user in users:
            identity, _ = DeviceIdentity.objects.get_or_create(device=device, terminal_user_id=user.terminal_user_id)
            identity.display_name = user.display_name
            identity.fingerprint_enrolled = user.fingerprint_enrolled
            identity.first_seen_at = identity.first_seen_at or now
            identity.last_seen_at = now
            identity.save(update_fields=["display_name", "fingerprint_enrolled", "first_seen_at", "last_seen_at", "updated_at"])
        run.finish(DeviceSyncRun.Status.SUCCEEDED, users_seen=len(users))
        device.health = AttendanceDevice.Health.HEALTHY
        device.last_user_sync_at = now
        device.last_successful_sync_at = now
        device.last_seen_at = now
        device.sync_lock_until = None
        device.save(update_fields=["health", "last_user_sync_at", "last_successful_sync_at", "last_seen_at", "sync_lock_until", "updated_at"])
        return {"status": run.status, "run": run, "users_seen": len(users)}
    except Exception as error:
        safe = error if isinstance(error, BiometricDeviceError) else BiometricDeviceError("User sync failed.")
        run.finish(DeviceSyncRun.Status.FAILED, error_code="DEVICE_ERROR", error_message=str(safe))
        device.health = AttendanceDevice.Health.OFFLINE
        device.sync_lock_until = None
        device.save(update_fields=["health", "sync_lock_until", "updated_at"])
        raise safe


def _issue_for_unmapped(device, punch, run):
    issue, created = BiometricPunchIssue.objects.get_or_create(
        organization=device.organization,
        device=device,
        code=BiometricPunchIssue.Code.UNMAPPED_ID,
        status=BiometricPunchIssue.Status.OPEN,
        summary=f"Terminal identity {punch.terminal_user_id} is not assigned to an employee.",
        defaults={"details": {"terminal_user_id": punch.terminal_user_id}},
    )
    return created


def sync_device_punches(device, *, actor=None, since=None, now=None, adapter=None):
    _operator_required(actor, device.organization)
    device = _device_lock(device)
    if device is None:
        return {"status": DeviceSyncRun.Status.SKIPPED, "reason": "another sync is already running"}
    run = DeviceSyncRun.objects.create(device=device, kind=DeviceSyncRun.Kind.PUNCHES, initiated_by=actor)
    adapter = adapter or adapter_for(device)
    try:
        punches = adapter.list_punches(since=since)
        created = duplicates = issues = 0
        for item in punches:
            payload = item.raw_payload or {}
            payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            canonical = BiometricPunch.make_canonical_key(
                device_record_id=item.device_record_id,
                terminal_user_id=item.terminal_user_id,
                occurred_at=item.occurred_at,
                status=item.status,
            )
            if not item.device_record_id:
                # Some F7 firmware omits a stable record id.  Keep identical
                # retries idempotent while allowing distinct same-second
                # events when the payload differs.
                canonical = hashlib.sha256(f"{canonical}|{payload_hash}".encode("utf-8")).hexdigest()
            identity = DeviceIdentity.objects.filter(device=device, terminal_user_id=item.terminal_user_id).first()
            assignment = _resolve_assignment(identity, item.occurred_at) if identity else None
            if BiometricPunch.objects.filter(device=device, canonical_key=canonical).exists():
                duplicates += 1
                continue
            punch = BiometricPunch.objects.create(
                device=device,
                device_identity=identity,
                identity_assignment=assignment,
                sync_run=run,
                device_record_id=item.device_record_id,
                terminal_user_id=item.terminal_user_id,
                source_local_timestamp=item.source_local_timestamp,
                source_timezone=item.source_timezone,
                occurred_at=item.occurred_at,
                canonical_key=canonical,
                payload_hash=payload_hash,
                raw_payload=payload,
            )
            created += 1
            if assignment is None:
                issues += int(_issue_for_unmapped(device, item, run))
                continue
            projection = projection_for_punch(punch, now=now)
            if projection:
                reconcile_biometric_projection(projection.shift, now=now)
        run.finish(DeviceSyncRun.Status.SUCCEEDED, punches_seen=len(punches), punches_created=created, punches_duplicate=duplicates, issues_created=issues)
        stamp = now or timezone.now()
        device.health = AttendanceDevice.Health.HEALTHY
        device.last_punch_sync_at = stamp
        device.last_successful_sync_at = stamp
        device.last_seen_at = stamp
        device.sync_lock_until = None
        device.save(update_fields=["health", "last_punch_sync_at", "last_successful_sync_at", "last_seen_at", "sync_lock_until", "updated_at"])
        return {"status": run.status, "run": run, "punches_seen": len(punches), "punches_created": created, "duplicates": duplicates, "issues": issues}
    except Exception as error:
        safe = error if isinstance(error, BiometricDeviceError) else BiometricDeviceError("Punch sync failed.")
        run.finish(DeviceSyncRun.Status.FAILED, error_code="DEVICE_ERROR", error_message=str(safe), punches_seen=0)
        device.health = AttendanceDevice.Health.OFFLINE
        device.sync_lock_until = None
        device.save(update_fields=["health", "sync_lock_until", "updated_at"])
        raise safe


def _shift_for_assignment(assignment, occurred_at):
    device = assignment.device_identity.device
    local_date = timezone.localtime(occurred_at, ZoneInfo(device.timezone)).date()
    return Shift.objects.filter(employee=assignment.employee, work_date=local_date).first()


def projection_for_punch(punch, *, now=None):
    assignment = punch.identity_assignment
    if assignment is None:
        return None
    shift = _shift_for_assignment(assignment, punch.occurred_at)
    if shift is None:
        BiometricPunchIssue.objects.get_or_create(
            organization=punch.device.organization,
            device=punch.device,
            punch=punch,
            code=BiometricPunchIssue.Code.NO_SHIFT,
            status=BiometricPunchIssue.Status.OPEN,
            summary=f"No scheduled shift matched punch for {assignment.employee.employee_code}.",
            defaults={"employee": assignment.employee, "details": {"occurred_at": punch.occurred_at.isoformat()}},
        )
        return None
    projection, _ = BiometricAttendanceProjection.objects.get_or_create(shift=shift, defaults={"employee": assignment.employee})
    return projection


def reconcile_biometric_projection(shift, *, now=None):
    projection, _ = BiometricAttendanceProjection.objects.get_or_create(shift=shift, defaults={"employee": shift.employee})
    punches = list(BiometricPunch.objects.filter(
        identity_assignment__employee=shift.employee,
        occurred_at__gte=shift.scheduled_start - timedelta(hours=12),
        occurred_at__lte=shift.scheduled_end + timedelta(hours=24),
    ))
    # The query above intentionally scopes by employee and time; filter by the
    # local work date as the final guard for overnight schedules.
    punches = [
        p for p in punches
        if timezone.localtime(p.occurred_at, ZoneInfo(p.source_timezone)).date() == shift.work_date
        or (shift.is_overnight and timezone.localtime(p.occurred_at, ZoneInfo(p.source_timezone)).date() == shift.work_date + timedelta(days=1))
    ]
    punches.sort(key=lambda p: p.occurred_at)
    projection.punch_count = len(punches)
    projection.first_punch_at = punches[0].occurred_at if punches else None
    projection.last_punch_at = punches[-1].occurred_at if punches else None
    projection.candidate_breaks = []
    projection.issue_summary = ""
    if len(punches) < 2:
        projection.status = BiometricAttendanceProjection.Status.COLLECTING
        projection.save()
        return projection
    interior = punches[1:-1]
    if len(interior) % 2:
        projection.status = BiometricAttendanceProjection.Status.NEEDS_REVIEW
        projection.issue_summary = "An even number of interior scans is required to pair flexible breaks."
        projection.save()
        BiometricPunchIssue.objects.get_or_create(
            organization=shift.organization, projection=projection,
            code=BiometricPunchIssue.Code.ODD_SEQUENCE, status=BiometricPunchIssue.Status.OPEN,
            summary=f"{shift.employee.employee_code} has an incomplete biometric break sequence.",
            defaults={"employee": shift.employee},
        )
        return projection
    breaks = []
    for start, end in zip(interior[::2], interior[1::2]):
        if end.occurred_at <= start.occurred_at:
            projection.status = BiometricAttendanceProjection.Status.NEEDS_REVIEW
            projection.issue_summary = "Biometric scans are out of order."
            projection.save()
            return projection
        breaks.append({"start": start.occurred_at.isoformat(), "end": end.occurred_at.isoformat()})
    projection.candidate_breaks = breaks
    capture_window = getattr(getattr(shift.organization, "biometric_settings", None), "post_shift_capture_minutes", 240)
    closed = (now or timezone.now()) >= shift.scheduled_end + timedelta(minutes=capture_window)
    projection.status = BiometricAttendanceProjection.Status.READY if closed else BiometricAttendanceProjection.Status.COLLECTING
    projection.candidate_closed_at = (now or timezone.now()) if closed else None
    projection.save()
    for punch in punches:
        if punch.projection_id != projection.pk:
            punch.projection = projection
            punch.save(update_fields=["projection"])
    return projection


@transaction.atomic
def materialize_biometric_projection(projection, *, actor=None, force=False):
    projection = BiometricAttendanceProjection.objects.select_for_update().select_related("shift", "employee", "shift__organization").get(pk=projection.pk)
    if actor is None:
        raise PermissionDenied("An employer reviewer is required to apply biometric attendance.")
    _operator_required(actor, projection.shift.organization)
    if projection.status not in {BiometricAttendanceProjection.Status.READY, BiometricAttendanceProjection.Status.NEEDS_REVIEW} and not force:
        raise ValidationError("This biometric projection is still collecting scans.")
    if projection.status == BiometricAttendanceProjection.Status.NEEDS_REVIEW and not force:
        raise ValidationError("Resolve the biometric sequence issue before applying attendance.")
    existing = AttendanceSession.objects.filter(shift=projection.shift).first()
    if existing:
        BiometricPunchIssue.objects.get_or_create(
            organization=projection.shift.organization, projection=projection,
            code=BiometricPunchIssue.Code.SOURCE_CONFLICT, status=BiometricPunchIssue.Status.OPEN,
            summary=f"A non-biometric attendance record already exists for {projection.employee.employee_code}.",
            defaults={"employee": projection.employee},
        )
        projection.status = BiometricAttendanceProjection.Status.CONFLICT
        projection.save(update_fields=["status", "updated_at"])
        return existing
    if not projection.first_punch_at or not projection.last_punch_at:
        raise ValidationError("At least a clock-in and clock-out scan are required.")
    session = AttendanceSession.objects.create(
        organization=projection.shift.organization,
        employee=projection.employee,
        shift=projection.shift,
        clock_in_at=projection.first_punch_at,
        clock_out_at=projection.last_punch_at,
        status=AttendanceSession.Status.COMPLETED,
        source=AttendanceSession.Source.BIOMETRIC,
    )
    for item in projection.candidate_breaks:
        BreakSession.objects.create(
            attendance_session=session,
            started_at=datetime.fromisoformat(item["start"]),
            ended_at=datetime.fromisoformat(item["end"]),
        )
    from timesheets.services import generate_timesheet

    generate_timesheet(session)
    projection.materialized_session = session
    projection.status = BiometricAttendanceProjection.Status.MATERIALIZED
    projection.save(update_fields=["materialized_session", "status", "updated_at"])
    return session

