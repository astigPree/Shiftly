"""Device adapters, immutable punch import, and attendance reconciliation.

The adapter is deliberately small: the rest of Shiftly only consumes DTOs and
never depends on the vendor SDK.  This makes a real F7 proof replaceable with
another terminal provider and keeps tests deterministic.
"""

import hashlib
import json
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
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


class BiometricErrorCode:
    """Stable error identifiers shared by adapters, services, and views."""

    CONFIGURATION = "BIO-CONFIG-INVALID"
    CREDENTIAL_KEY = "BIO-CREDENTIAL-KEY"
    CREDENTIAL_DECRYPT = "BIO-CREDENTIAL-DECRYPT"
    CREDENTIAL_FORMAT = "BIO-CREDENTIAL-FORMAT"
    ADAPTER_MISSING = "BIO-ADAPTER-MISSING"
    UNSUPPORTED_DEVICE = "BIO-UNSUPPORTED-DEVICE"
    NETWORK_UNREACHABLE = "BIO-NETWORK-UNREACHABLE"
    NETWORK_TIMEOUT = "BIO-NETWORK-TIMEOUT"
    AUTHENTICATION = "BIO-AUTHENTICATION-FAILED"
    PROTOCOL = "BIO-PROTOCOL-ERROR"
    PAYLOAD = "BIO-PAYLOAD-INVALID"
    SYNC_LOCKED = "BIO-SYNC-LOCKED"
    DATABASE = "BIO-DATABASE"
    INTERNAL = "BIO-INTERNAL"


class BiometricOperationError(Exception):
    """Safe structured error for an expected biometric operation failure."""

    def __init__(
        self,
        operator_message,
        *,
        code=BiometricErrorCode.INTERNAL,
        category="INTERNAL",
        retryable=False,
        health_outcome=AttendanceDevice.Health.DEGRADED,
        operator_action="",
        diagnostics=None,
    ):
        super().__init__(operator_message)
        self.code = code
        self.category = category
        self.retryable = bool(retryable)
        self.health_outcome = health_outcome
        self.operator_message = operator_message
        self.operator_action = operator_action
        self.diagnostics = diagnostics if isinstance(diagnostics, dict) else {}


class BiometricDeviceError(BiometricOperationError):
    """Safe, operator-facing device error without credentials."""

    def __init__(self, operator_message, **kwargs):
        kwargs.setdefault("code", BiometricErrorCode.NETWORK_UNREACHABLE)
        kwargs.setdefault("category", "NETWORK")
        kwargs.setdefault("retryable", True)
        kwargs.setdefault("health_outcome", AttendanceDevice.Health.OFFLINE)
        super().__init__(operator_message, **kwargs)


class BiometricConfigurationError(BiometricOperationError):
    """A device configuration or credential cannot be used safely."""

    def __init__(self, operator_message, **kwargs):
        kwargs.setdefault("code", BiometricErrorCode.CONFIGURATION)
        kwargs.setdefault("category", "CONFIGURATION")
        kwargs.setdefault("health_outcome", AttendanceDevice.Health.DEGRADED)
        super().__init__(operator_message, **kwargs)


def safe_operation_error(error, fallback="Shiftly could not complete this biometric operation."):
    """Convert an unexpected exception into a safe, non-leaking result."""
    if isinstance(error, BiometricOperationError):
        return error
    return BiometricOperationError(
        fallback,
        code=BiometricErrorCode.INTERNAL,
        category="INTERNAL",
        health_outcome=AttendanceDevice.Health.DEGRADED,
        diagnostics={"exception_type": error.__class__.__name__},
    )


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
            "The biometric credential encryption dependency is not available on this server.",
            code=BiometricErrorCode.CREDENTIAL_KEY,
            category="CONFIGURATION",
            operator_action="Contact the system administrator.",
            diagnostics={"exception_type": error.__class__.__name__},
        ) from error
    configured = getattr(settings, "BIOMETRIC_CREDENTIAL_KEY", "") or ""
    if not configured:
        if not getattr(settings, "DEBUG", False):
            raise BiometricConfigurationError(
                "The biometric credential encryption key is not configured.",
                code=BiometricErrorCode.CREDENTIAL_KEY,
                category="CONFIGURATION",
                operator_action="Contact the system administrator.",
            )
        # Development fallback keeps local setup usable while deployments can
        # require a dedicated key through the settings environment variable.
        configured = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        import base64

        configured = base64.urlsafe_b64encode(configured)
    try:
        return Fernet(configured)
    except Exception as error:
        raise BiometricConfigurationError(
            "The biometric credential encryption key is invalid.",
            code=BiometricErrorCode.CREDENTIAL_KEY,
            category="CONFIGURATION",
            operator_action="Contact the system administrator.",
            diagnostics={"exception_type": error.__class__.__name__},
        ) from error


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
        if isinstance(error, BiometricOperationError):
            raise
        raise BiometricConfigurationError(
            "The saved terminal credential could not be decrypted. Enter it again.",
            code=BiometricErrorCode.CREDENTIAL_DECRYPT,
            category="CONFIGURATION",
            operator_action="Edit the terminal and save its communication password again.",
            diagnostics={"exception_type": error.__class__.__name__},
        ) from error


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
            raise BiometricConfigurationError(
                "The ZKTeco F7 adapter is not installed on this server.",
                code=BiometricErrorCode.ADAPTER_MISSING,
                category="CONFIGURATION",
                operator_action="Install and configure the supported F7 adapter.",
                diagnostics={"exception_type": error.__class__.__name__},
            ) from error
        password = decrypt_password(self.device)
        if password and not password.isdigit():
            raise BiometricConfigurationError(
                "The terminal communication password must be numeric for this adapter.",
                code=BiometricErrorCode.CREDENTIAL_FORMAT,
                category="CONFIGURATION",
                operator_action="Edit the terminal and enter its numeric communication password.",
            )
        try:
            client = ZK(
                self.device.host,
                port=self.device.port,
                password=int(password or 0),
                timeout=8,
                ommit_ping=False,
            )
            self._connection = client.connect()
            return self._connection
        except Exception as error:
            details = f"{error.__class__.__name__} {error}".lower()
            if isinstance(error, (TimeoutError, socket.timeout)) or "timeout" in details:
                raise BiometricDeviceError(
                    f"{self.device.name} did not respond in time.",
                    code=BiometricErrorCode.NETWORK_TIMEOUT,
                    category="NETWORK",
                    retryable=True,
                    health_outcome=AttendanceDevice.Health.DEGRADED,
                    operator_action="Check the terminal power and office network. Scheduled sync will retry.",
                    diagnostics={"exception_type": error.__class__.__name__},
                ) from error
            if any(term in details for term in ("password", "auth", "permission", "unauthorized", "denied")):
                raise BiometricDeviceError(
                    f"{self.device.name} rejected its communication password.",
                    code=BiometricErrorCode.AUTHENTICATION,
                    category="AUTHENTICATION",
                    health_outcome=AttendanceDevice.Health.DEGRADED,
                    operator_action="Edit the terminal and test the saved communication password.",
                    diagnostics={"exception_type": error.__class__.__name__},
                ) from error
            if isinstance(error, (ConnectionError, OSError)) or any(
                term in details
                for term in ("can't connect", "cannot connect", "connection refused", "unreachable", "no route", "network")
            ):
                raise BiometricDeviceError(
                    f"{self.device.name} could not be reached on the office network.",
                    code=BiometricErrorCode.NETWORK_UNREACHABLE,
                    category="NETWORK",
                    retryable=True,
                    health_outcome=AttendanceDevice.Health.OFFLINE,
                    operator_action="Check power, LAN access, host, and port 4370.",
                    diagnostics={"exception_type": error.__class__.__name__},
                ) from error
            raise BiometricDeviceError(
                f"{self.device.name} returned an unsupported connection response.",
                code=BiometricErrorCode.PROTOCOL,
                category="PROTOCOL",
                health_outcome=AttendanceDevice.Health.DEGRADED,
                operator_action="Review the terminal firmware and connection details.",
                diagnostics={"exception_type": error.__class__.__name__},
            ) from error

    def close(self):
        if self._connection is not None:
            try:
                self._connection.disconnect()
            except Exception:
                pass
            self._connection = None

    def test_connection(self):
        try:
            connection = self._connect()
            firmware = str(getattr(connection, "get_device_name", lambda: "")() or "")
            serial = str(getattr(connection, "get_serialnumber", lambda: "")() or "")
            return DeviceInfo(firmware=firmware, serial_number=serial, model=self.device.model)
        finally:
            self.close()

    def list_users(self):
        try:
            connection = self._connect()
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
            if isinstance(error, BiometricOperationError):
                raise
            raise BiometricDeviceError(
                f"{self.device.name} returned an invalid user list.",
                code=BiometricErrorCode.PAYLOAD,
                category="DATA",
                health_outcome=AttendanceDevice.Health.DEGRADED,
                operator_action="Review the sync operation details.",
                diagnostics={"exception_type": error.__class__.__name__},
            ) from error
        finally:
            self.close()

    def list_punches(self, since=None):
        try:
            connection = self._connect()
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
            if isinstance(error, BiometricOperationError):
                raise
            raise BiometricDeviceError(
                f"{self.device.name} returned invalid attendance data.",
                code=BiometricErrorCode.PAYLOAD,
                category="DATA",
                health_outcome=AttendanceDevice.Health.DEGRADED,
                operator_action="Review the sync operation details.",
                diagnostics={"exception_type": error.__class__.__name__},
            ) from error
        finally:
            self.close()


def adapter_for(device):
    model = (device.model or "").lower()
    if model.startswith("zkteco") or model.startswith("f7"):
        return ZKTecoF7Adapter(device)
    raise BiometricConfigurationError(
        f"No supported adapter is available for {device.model}.",
        code=BiometricErrorCode.UNSUPPORTED_DEVICE,
        category="CONFIGURATION",
        health_outcome=AttendanceDevice.Health.DEGRADED,
        operator_action="Use a supported ZKTeco F7 model or contact the system administrator.",
    )


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
    pending.update(identity_assignment=assignment)
    reconcile_identity_assignment_punches(assignment)
    return assignment


def reconcile_identity_assignment_punches(assignment, *, actor=None, now=None):
    """Re-run matching for every immutable punch covered by an assignment.

    Assignments can be created after a terminal sync. Reprocessing the full
    historical interval keeps mapping changes idempotent and lets newly
    created or edited shifts receive the same evidence without rewriting raw
    punch records.
    """
    punches = BiometricPunch.objects.filter(
        device_identity=assignment.device_identity,
        identity_assignment=assignment,
        occurred_at__gte=assignment.effective_from,
    ).select_related("identity_assignment", "device")
    if assignment.effective_until:
        punches = punches.filter(occurred_at__lt=assignment.effective_until)
    shifts = set()
    for punch in punches:
        projection = projection_for_punch(punch, now=now)
        if projection:
            shifts.add(projection.shift_id)
    for shift_id in shifts:
        shift = Shift.objects.get(pk=shift_id)
        reconcile_biometric_projection(shift, now=now)
    return BiometricAttendanceProjection.objects.filter(shift_id__in=shifts)


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


def _release_device_lock(device):
    """Release only the lock held by this operation."""
    if device and device.sync_lock_until is not None:
        device.sync_lock_until = None
        device.save(update_fields=["sync_lock_until", "updated_at"])


def _skipped_run(device, kind, actor):
    run = DeviceSyncRun.objects.create(device=device, kind=kind, initiated_by=actor)
    run.finish(
        DeviceSyncRun.Status.SKIPPED,
        error_code=BiometricErrorCode.SYNC_LOCKED,
        error_message="Another biometric operation is already running for this terminal.",
        diagnostics={"reason": "device_lock"},
    )
    return {
        "status": run.status,
        "run": run,
        "reason": "another sync is already running",
        "error_code": BiometricErrorCode.SYNC_LOCKED,
    }


def _mark_device_success(device, *, now, kind, health=AttendanceDevice.Health.HEALTHY):
    device.health = health
    device.last_seen_at = now
    if kind != DeviceSyncRun.Kind.CONNECTION:
        device.last_successful_sync_at = now
    if kind == DeviceSyncRun.Kind.USERS:
        device.last_user_sync_at = now
    elif kind == DeviceSyncRun.Kind.PUNCHES:
        device.last_punch_sync_at = now
    device.sync_lock_until = None
    update_fields = ["health", "last_seen_at", "sync_lock_until", "updated_at"]
    if kind != DeviceSyncRun.Kind.CONNECTION:
        update_fields.append("last_successful_sync_at")
    if kind == DeviceSyncRun.Kind.USERS:
        update_fields.append("last_user_sync_at")
    elif kind == DeviceSyncRun.Kind.PUNCHES:
        update_fields.append("last_punch_sync_at")
    device.save(update_fields=update_fields)


def _mark_device_failure(device, error):
    device.health = error.health_outcome if error.health_outcome in {
        choice for choice, _label in AttendanceDevice.Health.choices
    } else AttendanceDevice.Health.DEGRADED
    device.sync_lock_until = None
    device.save(update_fields=["health", "sync_lock_until", "updated_at"])


def _finish_failed_run(run, device, error, **counts):
    safe = safe_operation_error(error)
    run.finish(
        DeviceSyncRun.Status.FAILED,
        error_code=safe.code,
        error_message=safe.operator_message,
        diagnostics={
            "category": safe.category,
            "retryable": safe.retryable,
            **safe.diagnostics,
        },
        **counts,
    )
    _mark_device_failure(device, safe)
    return safe


def _valid_device_user(user):
    terminal_id = str(getattr(user, "terminal_user_id", "") or "").strip()
    return bool(user and terminal_id) and len(terminal_id) <= 64


def _valid_device_punch(punch):
    terminal_id = str(getattr(punch, "terminal_user_id", "") or "").strip()
    if not punch or not terminal_id or len(terminal_id) > 64:
        return False
    occurred_at = getattr(punch, "occurred_at", None)
    if not isinstance(occurred_at, datetime) or not timezone.is_aware(occurred_at):
        return False
    try:
        ZoneInfo(getattr(punch, "source_timezone", ""))
    except Exception:
        return False
    return True


def sync_device_users(device, *, actor=None, adapter=None):
    _operator_required(actor, device.organization)
    locked_device = _device_lock(device)
    if locked_device is None:
        return _skipped_run(device, DeviceSyncRun.Kind.USERS, actor)
    run = None
    users_seen = invalid = 0
    try:
        run = DeviceSyncRun.objects.create(device=locked_device, kind=DeviceSyncRun.Kind.USERS, initiated_by=actor)
        adapter = adapter or adapter_for(locked_device)
        users = adapter.list_users()
        now = timezone.now()
        for user in users:
            users_seen += 1
            if not _valid_device_user(user):
                invalid += 1
                continue
            identity, _ = DeviceIdentity.objects.get_or_create(device=locked_device, terminal_user_id=user.terminal_user_id)
            identity.display_name = user.display_name
            identity.fingerprint_enrolled = user.fingerprint_enrolled
            identity.first_seen_at = identity.first_seen_at or now
            identity.last_seen_at = now
            identity.save(update_fields=["display_name", "fingerprint_enrolled", "first_seen_at", "last_seen_at", "updated_at"])
        status = DeviceSyncRun.Status.PARTIAL if invalid else DeviceSyncRun.Status.SUCCEEDED
        run.finish(
            status,
            error_code=BiometricErrorCode.PAYLOAD if invalid else "",
            error_message="Some terminal users could not be imported." if invalid else "",
            diagnostics={"invalid_records": invalid},
            users_seen=users_seen,
        )
        _mark_device_success(
            locked_device,
            now=now,
            kind=DeviceSyncRun.Kind.USERS,
            health=AttendanceDevice.Health.DEGRADED if invalid else AttendanceDevice.Health.HEALTHY,
        )
        return {"status": run.status, "run": run, "users_seen": users_seen, "invalid": invalid}
    except Exception as error:
        if run is None:
            run = DeviceSyncRun.objects.create(device=locked_device, kind=DeviceSyncRun.Kind.USERS, initiated_by=actor)
        safe = _finish_failed_run(run, locked_device, error, users_seen=users_seen)
        raise safe
    finally:
        _release_device_lock(locked_device)


def test_device_connection(device, *, actor=None, adapter=None):
    """Run and record one connection test through the normal device lock."""
    _operator_required(actor, device.organization)
    locked_device = _device_lock(device)
    if locked_device is None:
        return _skipped_run(device, DeviceSyncRun.Kind.CONNECTION, actor)
    run = None
    try:
        run = DeviceSyncRun.objects.create(
            device=locked_device,
            kind=DeviceSyncRun.Kind.CONNECTION,
            initiated_by=actor,
        )
        info = (adapter or adapter_for(locked_device)).test_connection()
        now = timezone.now()
        run.finish(
            DeviceSyncRun.Status.SUCCEEDED,
            diagnostics={"firmware": info.firmware[:120], "serial_number": info.serial_number[:120]},
        )
        locked_device.firmware = info.firmware[:120]
        locked_device.serial_number = info.serial_number[:120]
        _mark_device_success(locked_device, now=now, kind=DeviceSyncRun.Kind.CONNECTION)
        locked_device.save(update_fields=["firmware", "serial_number", "updated_at"])
        return {"status": run.status, "run": run, "info": info}
    except Exception as error:
        if run is None:
            run = DeviceSyncRun.objects.create(
                device=locked_device,
                kind=DeviceSyncRun.Kind.CONNECTION,
                initiated_by=actor,
            )
        safe = _finish_failed_run(run, locked_device, error)
        raise safe
    finally:
        _release_device_lock(locked_device)


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
    locked_device = _device_lock(device)
    if locked_device is None:
        return _skipped_run(device, DeviceSyncRun.Kind.PUNCHES, actor)
    run = None
    punches_seen = created = duplicates = issues = invalid = 0
    try:
        run = DeviceSyncRun.objects.create(device=locked_device, kind=DeviceSyncRun.Kind.PUNCHES, initiated_by=actor)
        adapter = adapter or adapter_for(locked_device)
        punches = adapter.list_punches(since=since)
        for item in punches:
            punches_seen += 1
            if not _valid_device_punch(item):
                invalid += 1
                continue
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
            identity = DeviceIdentity.objects.filter(device=locked_device, terminal_user_id=item.terminal_user_id).first()
            assignment = _resolve_assignment(identity, item.occurred_at) if identity else None
            if BiometricPunch.objects.filter(device=locked_device, canonical_key=canonical).exists():
                duplicates += 1
                continue
            try:
                punch = BiometricPunch.objects.create(
                    device=locked_device,
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
            except IntegrityError:
                duplicates += 1
                continue
            created += 1
            if assignment is None:
                issues += int(_issue_for_unmapped(locked_device, item, run))
                continue
            projection = projection_for_punch(punch, now=now)
            if projection:
                reconcile_biometric_projection(projection.shift, now=now)
        # A candidate can become reviewable because time passed even when the
        # terminal returned no new event in this sync.
        refresh_due_biometric_projections(now=now or timezone.now())
        partial = bool(invalid)
        run.finish(
            DeviceSyncRun.Status.PARTIAL if partial else DeviceSyncRun.Status.SUCCEEDED,
            error_code=BiometricErrorCode.PAYLOAD if partial else "",
            error_message="Some terminal scans could not be imported." if partial else "",
            diagnostics={"invalid_records": invalid},
            punches_seen=punches_seen,
            punches_created=created,
            punches_duplicate=duplicates,
            issues_created=issues,
        )
        stamp = now or timezone.now()
        _mark_device_success(
            locked_device,
            now=stamp,
            kind=DeviceSyncRun.Kind.PUNCHES,
            health=AttendanceDevice.Health.DEGRADED if partial else AttendanceDevice.Health.HEALTHY,
        )
        return {
            "status": run.status,
            "run": run,
            "punches_seen": punches_seen,
            "punches_created": created,
            "duplicates": duplicates,
            "issues": issues,
            "invalid": invalid,
        }
    except Exception as error:
        if run is None:
            run = DeviceSyncRun.objects.create(device=locked_device, kind=DeviceSyncRun.Kind.PUNCHES, initiated_by=actor)
        safe = _finish_failed_run(
            run,
            locked_device,
            error,
            punches_seen=punches_seen,
            punches_created=created,
            punches_duplicate=duplicates,
            issues_created=issues,
        )
        raise safe
    finally:
        _release_device_lock(locked_device)


PROVISIONAL_ALGORITHM_VERSION = "provisional-v1"


def _biometric_policy(organization):
    policy = getattr(organization, "biometric_settings", None)
    return {
        "early_clock_in_minutes": getattr(policy, "early_clock_in_minutes", 30),
        "post_shift_capture_minutes": getattr(policy, "post_shift_capture_minutes", 240),
        "duplicate_window_seconds": getattr(policy, "duplicate_window_seconds", 60),
    }


def _employee_timezone_name(employee, organization):
    try:
        profile = employee.payroll_profile
    except Exception:
        profile = None
    return (getattr(profile, "payroll_timezone", "") or organization.timezone).strip() or organization.timezone


def _candidate_shifts_for_assignment(assignment, occurred_at):
    organization = assignment.device_identity.device.organization
    policy = _biometric_policy(organization)
    early = timedelta(minutes=policy["early_clock_in_minutes"])
    post = timedelta(minutes=policy["post_shift_capture_minutes"])
    return list(
        Shift.objects.filter(
            employee=assignment.employee,
            status=Shift.Status.SCHEDULED,
            scheduled_start__lte=occurred_at + early,
            scheduled_end__gte=occurred_at - post,
        ).select_related("organization", "employee").order_by("scheduled_start", "pk")
    )


def _shift_for_assignment(assignment, occurred_at):
    candidates = _candidate_shifts_for_assignment(assignment, occurred_at)
    return candidates[0] if len(candidates) == 1 else None


def _resolve_punch_issue(punch, code):
    BiometricPunchIssue.objects.filter(
        punch=punch,
        code=code,
        status=BiometricPunchIssue.Status.OPEN,
    ).update(
        status=BiometricPunchIssue.Status.RESOLVED,
        resolved_at=timezone.now(),
    )


def projection_for_punch(punch, *, now=None):
    assignment = punch.identity_assignment
    if assignment is None:
        return None
    candidates = _candidate_shifts_for_assignment(assignment, punch.occurred_at)
    if not candidates:
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
    if len(candidates) > 1:
        BiometricPunchIssue.objects.get_or_create(
            organization=punch.device.organization,
            device=punch.device,
            punch=punch,
            employee=assignment.employee,
            code=BiometricPunchIssue.Code.AMBIGUOUS_SHIFT,
            status=BiometricPunchIssue.Status.OPEN,
            summary=f"More than one scheduled shift could match {assignment.employee.employee_code}'s scan.",
            defaults={"details": {"occurred_at": punch.occurred_at.isoformat(), "shift_ids": [shift.pk for shift in candidates]}},
        )
        return None
    shift = candidates[0]
    _resolve_punch_issue(punch, BiometricPunchIssue.Code.NO_SHIFT)
    _resolve_punch_issue(punch, BiometricPunchIssue.Code.AMBIGUOUS_SHIFT)
    projection, _ = BiometricAttendanceProjection.objects.get_or_create(shift=shift, defaults={"employee": assignment.employee})
    return projection


def _effective_punches_for_shift(shift):
    policy = _biometric_policy(shift.organization)
    start = shift.scheduled_start - timedelta(minutes=policy["early_clock_in_minutes"])
    end = shift.scheduled_end + timedelta(minutes=policy["post_shift_capture_minutes"])
    raw_punches = list(
        BiometricPunch.objects.filter(
            identity_assignment__employee=shift.employee,
            occurred_at__gte=start,
            occurred_at__lte=end,
        ).select_related("device", "device_identity", "identity_assignment")
        .order_by("occurred_at", "device_id", "pk")
    )
    effective = []
    duplicate_window = policy["duplicate_window_seconds"]
    for punch in raw_punches:
        previous = effective[-1] if effective else None
        if (
            previous
            and punch.device_id == previous.device_id
            and punch.device_identity_id == previous.device_identity_id
            and (punch.occurred_at - previous.occurred_at).total_seconds() <= duplicate_window
        ):
            continue
        effective.append(punch)
    return raw_punches, effective


def _projection_fingerprint(shift, effective_punches, policy):
    value = {
        "algorithm": PROVISIONAL_ALGORITHM_VERSION,
        "shift": shift.pk,
        "punches": [p.pk for p in effective_punches],
        "early": policy["early_clock_in_minutes"],
        "post": policy["post_shift_capture_minutes"],
        "duplicate": policy["duplicate_window_seconds"],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _close_projection_sequence_issues(projection):
    BiometricPunchIssue.objects.filter(
        projection=projection,
        code__in=[BiometricPunchIssue.Code.ODD_SEQUENCE, BiometricPunchIssue.Code.OPEN_BREAK],
        status=BiometricPunchIssue.Status.OPEN,
    ).update(status=BiometricPunchIssue.Status.RESOLVED, resolved_at=timezone.now())


def _retain_locked_projection_evidence(projection, shift, stamp):
    """Attach late evidence without rewriting an applied or conflicted result."""
    raw_punches, _ = _effective_punches_for_shift(shift)
    issue_code = (
        BiometricPunchIssue.Code.LATE_EVIDENCE
        if projection.materialized_session_id
        else BiometricPunchIssue.Code.SOURCE_CONFLICT
    )
    for punch in raw_punches:
        if punch.projection_id is not None:
            continue
        punch.projection = projection
        punch.save(update_fields=["projection"])
        BiometricPunchIssue.objects.get_or_create(
            punch=punch,
            code=issue_code,
            defaults={
                "organization": shift.organization,
                "device": punch.device,
                "projection": projection,
                "employee": shift.employee,
                "status": BiometricPunchIssue.Status.OPEN,
                "summary": (
                    f"A biometric scan arrived after attendance was applied for {shift.employee.employee_code}."
                    if issue_code == BiometricPunchIssue.Code.LATE_EVIDENCE
                    else f"A biometric scan conflicts with the recorded attendance for {shift.employee.employee_code}."
                ),
                "details": {"occurred_at": punch.occurred_at.isoformat()},
            },
        )
    projection.last_reconciled_at = stamp
    projection.save(update_fields=["last_reconciled_at", "updated_at"])


@transaction.atomic
def reconcile_biometric_projection(shift, *, now=None):
    stamp = now or timezone.now()
    projection, _ = BiometricAttendanceProjection.objects.select_for_update().get_or_create(
        shift=shift,
        defaults={"employee": shift.employee},
    )
    if projection.materialized_session_id or projection.status == BiometricAttendanceProjection.Status.CONFLICT:
        _retain_locked_projection_evidence(projection, shift, stamp)
        return projection

    policy = _biometric_policy(shift.organization)
    candidate_closes_at = shift.scheduled_end + timedelta(minutes=policy["post_shift_capture_minutes"])
    raw_punches, punches = _effective_punches_for_shift(shift)
    for punch in raw_punches:
        if punch.projection_id != projection.pk:
            punch.projection = projection
            punch.save(update_fields=["projection"])

    projection.punch_count = len(punches)
    projection.first_punch_at = punches[0].occurred_at if punches else None
    projection.last_punch_at = punches[-1].occurred_at if punches else None
    projection.provisional_started_at = projection.first_punch_at
    projection.last_effective_scan_at = projection.last_punch_at
    projection.candidate_breaks = []
    projection.issue_summary = ""
    projection.candidate_closes_at = candidate_closes_at
    projection.last_reconciled_at = stamp
    projection.algorithm_version = PROVISIONAL_ALGORITHM_VERSION
    projection.input_fingerprint = _projection_fingerprint(shift, punches, policy)
    closed = stamp >= candidate_closes_at
    projection.candidate_closed_at = stamp if closed else None

    if not punches:
        projection.status = BiometricAttendanceProjection.Status.COLLECTING
        projection.live_state = BiometricAttendanceProjection.LiveState.NONE
        projection.save()
        return projection

    if len(punches) < 2:
        projection.status = (
            BiometricAttendanceProjection.Status.NEEDS_REVIEW
            if closed else BiometricAttendanceProjection.Status.COLLECTING
        )
        projection.live_state = (
            BiometricAttendanceProjection.LiveState.NEEDS_REVIEW
            if closed else BiometricAttendanceProjection.LiveState.WORKING
        )
        if closed:
            projection.issue_summary = "A second fingerprint scan is required to complete this attendance sequence."
            BiometricPunchIssue.objects.get_or_create(
                organization=shift.organization,
                projection=projection,
                employee=shift.employee,
                code=BiometricPunchIssue.Code.ODD_SEQUENCE,
                status=BiometricPunchIssue.Status.OPEN,
                summary=f"{shift.employee.employee_code} is missing a final biometric scan.",
                defaults={"details": {"punch_count": len(punches)}},
            )
        projection.save()
        return projection

    interior = punches[1:-1]
    if len(interior) % 2:
        projection.status = (
            BiometricAttendanceProjection.Status.NEEDS_REVIEW
            if closed else BiometricAttendanceProjection.Status.COLLECTING
        )
        projection.live_state = (
            BiometricAttendanceProjection.LiveState.NEEDS_REVIEW
            if closed else BiometricAttendanceProjection.LiveState.AWAITING_NEXT_SCAN
        )
        projection.issue_summary = "An even number of interior scans is required to pair flexible breaks."
        if closed:
            BiometricPunchIssue.objects.get_or_create(
                organization=shift.organization,
                projection=projection,
                employee=shift.employee,
                code=BiometricPunchIssue.Code.ODD_SEQUENCE,
                status=BiometricPunchIssue.Status.OPEN,
                summary=f"{shift.employee.employee_code} has an incomplete biometric break sequence.",
                defaults={"details": {"punch_count": len(punches)}},
            )
        projection.save()
        return projection

    breaks = []
    for start, end in zip(interior[::2], interior[1::2]):
        if end.occurred_at <= start.occurred_at:
            projection.status = BiometricAttendanceProjection.Status.NEEDS_REVIEW if closed else BiometricAttendanceProjection.Status.COLLECTING
            projection.live_state = BiometricAttendanceProjection.LiveState.NEEDS_REVIEW if closed else BiometricAttendanceProjection.LiveState.AWAITING_NEXT_SCAN
            projection.issue_summary = "Biometric scans are out of order."
            projection.save()
            return projection
        breaks.append({"start": start.occurred_at.isoformat(), "end": end.occurred_at.isoformat()})

    projection.candidate_breaks = breaks
    projection.status = BiometricAttendanceProjection.Status.READY if closed else BiometricAttendanceProjection.Status.COLLECTING
    projection.live_state = BiometricAttendanceProjection.LiveState.READY_FOR_REVIEW if closed else BiometricAttendanceProjection.LiveState.AWAITING_NEXT_SCAN
    if closed:
        _close_projection_sequence_issues(projection)
    projection.save()
    return projection


def reconcile_unmatched_punches_for_shift(shift, *, actor=None, now=None):
    """Reprocess evidence after a schedule or identity mapping becomes available."""
    policy = _biometric_policy(shift.organization)
    start = shift.scheduled_start - timedelta(minutes=policy["early_clock_in_minutes"])
    end = shift.scheduled_end + timedelta(minutes=policy["post_shift_capture_minutes"])
    punches = BiometricPunch.objects.filter(
        identity_assignment__employee=shift.employee,
        occurred_at__gte=start,
        occurred_at__lte=end,
    ).select_related("identity_assignment", "device")
    projections = set()
    for punch in punches:
        projection = projection_for_punch(punch, now=now)
        if projection and projection.shift_id == shift.pk:
            projections.add(projection.pk)
    for projection_pk in projections:
        reconcile_biometric_projection(shift, now=now)
    return BiometricAttendanceProjection.objects.filter(pk__in=projections)


def refresh_due_biometric_projections(now=None):
    stamp = now or timezone.now()
    projections = BiometricAttendanceProjection.objects.filter(
        status=BiometricAttendanceProjection.Status.COLLECTING,
    ).select_related("shift", "shift__organization", "shift__employee")
    refreshed = []
    for projection in projections:
        close_at = projection.candidate_closes_at
        if close_at is None:
            policy = _biometric_policy(projection.shift.organization)
            close_at = projection.shift.scheduled_end + timedelta(minutes=policy["post_shift_capture_minutes"])
        if close_at <= stamp:
            refreshed.append(reconcile_biometric_projection(projection.shift, now=stamp))
    return refreshed


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
    projection.live_state = BiometricAttendanceProjection.LiveState.MATERIALIZED
    projection.save(update_fields=["materialized_session", "status", "live_state", "updated_at"])
    return session

