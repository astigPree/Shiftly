from datetime import datetime, timedelta, timezone as datetime_timezone

from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from employees.models import Employee
from schedules.models import Shift
from .models import AttendanceCorrection, AttendanceSession, BreakSession


def effective_attendance_values(session):
    """Return the latest effective punch and break values for payroll.

    Raw AttendanceSession and BreakSession rows are never rewritten.  The
    newest correction, when present, overlays those raw values.
    """
    prefetched = getattr(session, "_prefetched_objects_cache", {}).get("corrections")
    if prefetched is not None:
        correction = prefetched[0] if prefetched else None
    else:
        correction = (
            AttendanceCorrection.objects.filter(attendance_session_id=session.pk)
            .order_by("-created_at", "-pk")
            .first()
        )
    if correction is None:
        breaks = list(session.breaks.all())
        return {
            "clock_in_at": session.clock_in_at,
            "clock_out_at": session.clock_out_at,
            "breaks": breaks,
            "correction": None,
        }
    breaks = [
        SimpleNamespace(
            started_at=datetime.fromisoformat(item["start"]),
            ended_at=datetime.fromisoformat(item["end"]) if item.get("end") else None,
        )
        for item in correction.corrected_breaks
    ]
    return {
        "clock_in_at": correction.corrected_clock_in_at,
        "clock_out_at": correction.corrected_clock_out_at,
        "breaks": breaks,
        "correction": correction,
    }


def _serialize_breaks(breaks):
    return [
        {
            "start": item.started_at.astimezone(datetime_timezone.utc).isoformat(),
            "end": item.ended_at.astimezone(datetime_timezone.utc).isoformat() if item.ended_at else None,
        }
        for item in breaks
    ]


def _session_work_timezone(session):
    profile = getattr(session.employee, "payroll_profile", None)
    timezone_name = getattr(profile, "payroll_timezone", "") or session.organization.timezone
    return ZoneInfo(timezone_name), timezone_name


def _require_owner(employee, actor):
    if not actor.is_authenticated or employee.user_id != actor.pk:
        raise PermissionDenied("You can only record attendance for your own shifts.")


def _ensure_clockable(shift, employee, now):
    if shift.employee_id != employee.pk:
        raise PermissionDenied
    if shift.organization_id != employee.organization_id:
        raise PermissionDenied("The shift does not belong to the employee's organization.")
    if employee.status != Employee.Status.ACTIVE:
        raise PermissionDenied("Inactive employees cannot record attendance.")
    if employee_requires_biometric(employee):
        raise PermissionDenied(
            "This employee is assigned to a biometric terminal. Use the assigned terminal or ask an employer to record a correction."
        )
    if shift.status != Shift.Status.SCHEDULED:
        raise ValidationError("A cancelled shift cannot be clocked into.")
    earliest = shift.scheduled_start - timedelta(minutes=30)
    if now < earliest:
        raise ValidationError("Clock-in opens 30 minutes before the scheduled start.")
    if now >= shift.scheduled_end:
        raise ValidationError("Clock-in is closed because the scheduled shift has ended.")


@transaction.atomic
def clock_in(*, shift, employee, actor, at=None):
    now = at or timezone.now()
    shift = Shift.objects.select_for_update().select_related("employee").get(pk=shift.pk)
    employee = Employee.objects.select_for_update(of=("self",)).select_related("user").get(pk=employee.pk)
    _require_owner(employee, actor)
    _ensure_clockable(shift, employee, now)
    if AttendanceSession.objects.filter(shift=shift).exists():
        raise ValidationError("This shift already has an attendance session.")
    try:
        return AttendanceSession.objects.create(
            organization=shift.organization,
            employee=employee,
            shift=shift,
            clock_in_at=now,
            status=AttendanceSession.Status.WORKING,
            source=AttendanceSession.Source.EMPLOYEE_WEB,
        )
    except IntegrityError as error:
        raise ValidationError("An open attendance session already exists for this employee.") from error


def _locked_owned_session(session, employee, actor):
    session = (
        AttendanceSession.objects.select_for_update(of=("self",))
        .select_related("employee", "employee__user", "shift")
        .get(pk=session.pk)
    )
    _require_owner(session.employee, actor)
    if employee_requires_biometric(session.employee):
        raise PermissionDenied(
            "This employee is assigned to a biometric terminal. Breaks and clock-out are recorded at the terminal."
        )
    if session.employee_id != employee.pk:
        raise PermissionDenied
    return session


def employee_requires_biometric(employee):
    """Return whether at least one active terminal identity is assigned.

    The import is intentionally local so the legacy attendance app remains
    usable during migrations and in installations without biometric devices.
    """
    try:
        from biometrics.models import DeviceIdentityAssignment
    except ImportError:
        return False
    if employee.status != Employee.Status.ACTIVE:
        return False
    settings = getattr(employee.organization, "biometric_settings", None)
    if not settings or not settings.enabled:
        return False
    return DeviceIdentityAssignment.objects.filter(
        employee_id=employee.pk,
        effective_from__lte=timezone.now(),
    ).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gt=timezone.now())
    ).filter(device_identity__device__status="ACTIVE").exists()


@transaction.atomic
def start_break(*, session, employee, actor, at=None):
    now = at or timezone.now()
    session = _locked_owned_session(session, employee, actor)
    if effective_attendance_values(session)["clock_out_at"] is not None:
        raise ValidationError("This attendance session was corrected by your employer and is closed.")
    if session.clock_out_at is not None or session.status != AttendanceSession.Status.WORKING:
        raise ValidationError("A break can only start while you are working.")
    if BreakSession.objects.filter(attendance_session=session, ended_at__isnull=True).exists():
        raise ValidationError("A break is already in progress.")
    try:
        break_session = BreakSession.objects.create(attendance_session=session, started_at=now)
    except IntegrityError as error:
        raise ValidationError("A break is already in progress.") from error
    session.status = AttendanceSession.Status.ON_BREAK
    session.save(update_fields=["status", "updated_at"])
    return break_session


@transaction.atomic
def end_break(*, session, employee, actor, at=None):
    now = at or timezone.now()
    session = _locked_owned_session(session, employee, actor)
    if effective_attendance_values(session)["clock_out_at"] is not None:
        raise ValidationError("This attendance session was corrected by your employer and is closed.")
    if session.clock_out_at is not None or session.status != AttendanceSession.Status.ON_BREAK:
        raise ValidationError("There is no break to end.")
    break_session = (
        BreakSession.objects.select_for_update()
        .filter(attendance_session=session, ended_at__isnull=True)
        .first()
    )
    if break_session is None:
        raise ValidationError("There is no break to end.")
    if now <= break_session.started_at:
        raise ValidationError("A break must have a positive duration before it can end.")
    break_session.ended_at = now
    break_session.save(update_fields=["ended_at"])
    session.status = AttendanceSession.Status.WORKING
    session.save(update_fields=["status", "updated_at"])
    return break_session


@transaction.atomic
def clock_out(*, session, employee, actor, at=None):
    now = at or timezone.now()
    session = _locked_owned_session(session, employee, actor)
    if effective_attendance_values(session)["clock_out_at"] is not None:
        raise ValidationError("This attendance session was corrected by your employer and is closed.")
    if session.clock_out_at is not None or session.status != AttendanceSession.Status.WORKING:
        raise ValidationError("Clock-out is available only while working. End any open break first.")
    if now <= session.clock_in_at:
        raise ValidationError("Clock-out must be after clock-in.")
    if BreakSession.objects.filter(attendance_session=session, ended_at__isnull=True).exists():
        raise ValidationError("End your break before clocking out.")
    session.clock_out_at = now
    session.status = AttendanceSession.Status.COMPLETED
    session.save(update_fields=["clock_out_at", "status", "updated_at"])
    from timesheets.services import generate_timesheet

    generate_timesheet(session)
    return session


@transaction.atomic
def correct_attendance(*, session, actor, corrected_clock_in_at, corrected_clock_out_at, corrected_breaks, reason):
    """Record an employer correction and refresh any generated timesheet."""
    from accounts.models import User
    from accounts.permissions import organization_for_user
    from audit.models import AuditEvent
    from audit.services import record_event
    from payroll.models import PayrollRun, PayrollTimeEntry
    from timesheets.services import recalculate_timesheet

    if not actor.is_authenticated or actor.role != User.Role.EMPLOYER:
        raise PermissionDenied("Only an employer can correct attendance.")
    organization = organization_for_user(actor)
    if organization is None or organization.pk != session.organization_id:
        raise PermissionDenied("You cannot correct attendance from another organization.")
    locked_session = (
        AttendanceSession.objects.select_for_update()
        .select_related("employee", "employee__payroll_profile", "shift", "organization")
        .get(pk=session.pk, organization=organization)
    )
    if corrected_clock_out_at and corrected_clock_out_at <= corrected_clock_in_at:
        raise ValidationError("Clock-out must be after clock-in.")
    work_timezone, timezone_name = _session_work_timezone(locked_session)
    corrected_clock_in_date = timezone.localtime(corrected_clock_in_at, work_timezone).date()
    if corrected_clock_in_date != locked_session.shift.work_date:
        work_date_label = f"{locked_session.shift.work_date:%b} {locked_session.shift.work_date.day}, {locked_session.shift.work_date:%Y}"
        raise ValidationError(
            f"Corrected clock-in must be on {work_date_label} "
            f"in {timezone_name}."
        )
    if corrected_clock_out_at:
        corrected_clock_out_date = timezone.localtime(corrected_clock_out_at, work_timezone).date()
        latest_allowed_date = timezone.localtime(locked_session.shift.scheduled_end, work_timezone).date()
        if corrected_clock_out_date < locked_session.shift.work_date or corrected_clock_out_date > latest_allowed_date:
            raise ValidationError(
                "Corrected clock-out must stay within the shift's local work-date window."
            )
    if PayrollTimeEntry.objects.filter(
        timesheet__attendance_session_id=locked_session.pk,
        statement__run__status=PayrollRun.Status.FINALIZED,
    ).exists():
        raise ValidationError("This attendance is locked because it is included in finalized payroll.")

    current = effective_attendance_values(locked_session)
    normalized_breaks = list(corrected_breaks or [])
    original_breaks = _serialize_breaks(current["breaks"])
    corrected_break_payload = _serialize_breaks(
        [SimpleNamespace(started_at=start, ended_at=end) for start, end in normalized_breaks]
    )
    if (
        current["clock_in_at"] == corrected_clock_in_at
        and current["clock_out_at"] == corrected_clock_out_at
        and original_breaks == corrected_break_payload
    ):
        raise ValidationError("Change a punch or break value before saving the correction.")

    correction = AttendanceCorrection.objects.create(
        attendance_session=locked_session,
        created_by=actor,
        original_clock_in_at=current["clock_in_at"],
        original_clock_out_at=current["clock_out_at"],
        corrected_clock_in_at=corrected_clock_in_at,
        corrected_clock_out_at=corrected_clock_out_at,
        original_breaks=original_breaks,
        corrected_breaks=corrected_break_payload,
        reason=reason,
    )
    timesheet = getattr(locked_session, "timesheet", None)
    if timesheet is not None:
        recalculate_timesheet(timesheet, attendance_session=locked_session, correction=correction)
    elif corrected_clock_out_at:
        from timesheets.services import generate_timesheet

        generate_timesheet(locked_session)

    record_event(
        organization=organization,
        actor=actor,
        action=AuditEvent.Action.ATTENDANCE_CORRECTED,
        target_type="attendance_correction",
        target_id=correction.pk,
        summary=f"Corrected attendance for {locked_session.employee.employee_code}.",
        metadata={
            "attendance_session_id": locked_session.pk,
            "reason": reason.strip(),
            "original_clock_in_at": current["clock_in_at"].isoformat() if current["clock_in_at"] else None,
            "original_clock_out_at": current["clock_out_at"].isoformat() if current["clock_out_at"] else None,
            "corrected_clock_in_at": corrected_clock_in_at.isoformat(),
            "corrected_clock_out_at": corrected_clock_out_at.isoformat() if corrected_clock_out_at else None,
        },
    )
    return correction


@transaction.atomic
def record_attendance(*, shift, actor, clock_in_at, clock_out_at, breaks, reason):
    """Create a complete employer-entered session when an employee missed the punch."""
    from accounts.models import User
    from accounts.permissions import organization_for_user
    from audit.models import AuditEvent
    from audit.services import record_event
    from timesheets.services import generate_timesheet

    if not actor.is_authenticated or actor.role != User.Role.EMPLOYER:
        raise PermissionDenied("Only an employer can record attendance for an employee.")
    organization = organization_for_user(actor)
    locked_shift = Shift.objects.select_for_update().select_related(
        "employee", "employee__payroll_profile", "organization"
    ).get(pk=shift.pk, organization=organization)
    if locked_shift.status != Shift.Status.SCHEDULED:
        raise ValidationError("Attendance can only be recorded for a scheduled shift.")
    if AttendanceSession.objects.filter(shift=locked_shift).exists():
        raise ValidationError("This shift already has attendance. Open the existing record to correct it.")
    if not clock_in_at or not clock_out_at:
        raise ValidationError("Enter both clock-in and clock-out.")
    if clock_out_at <= clock_in_at:
        raise ValidationError("Clock-out must be after clock-in.")
    profile = getattr(locked_shift.employee, "payroll_profile", None)
    timezone_name = getattr(profile, "payroll_timezone", "") or organization.timezone
    work_timezone = ZoneInfo(timezone_name)
    if timezone.localtime(clock_in_at, work_timezone).date() != locked_shift.work_date:
        raise ValidationError(
            f"Clock-in must be on {locked_shift.work_date:%b} {locked_shift.work_date.day}, "
            f"{locked_shift.work_date:%Y} in {timezone_name}."
        )
    latest_end_date = timezone.localtime(locked_shift.scheduled_end, work_timezone).date()
    clock_out_date = timezone.localtime(clock_out_at, work_timezone).date()
    if clock_out_date < locked_shift.work_date or clock_out_date > latest_end_date:
        raise ValidationError("Clock-out must stay within the shift's local work-date window.")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValidationError("Enter a clear reason for the employer-entered attendance.")

    session = AttendanceSession.objects.create(
        organization=organization,
        employee=locked_shift.employee,
        shift=locked_shift,
        clock_in_at=clock_in_at,
        clock_out_at=clock_out_at,
        status=AttendanceSession.Status.COMPLETED,
        source=AttendanceSession.Source.EMPLOYER_MANUAL,
    )
    for started_at, ended_at in breaks or []:
        BreakSession.objects.create(
            attendance_session=session,
            started_at=started_at,
            ended_at=ended_at,
        )
    generate_timesheet(session)
    record_event(
        organization=organization,
        actor=actor,
        action=AuditEvent.Action.ATTENDANCE_CORRECTED,
        target_type="attendance_session",
        target_id=session.pk,
        summary=f"Recorded missed attendance for {locked_shift.employee.employee_code}.",
        metadata={
            "source": "EMPLOYER_MANUAL_ENTRY",
            "shift_id": locked_shift.pk,
            "clock_in_at": clock_in_at.isoformat(),
            "clock_out_at": clock_out_at.isoformat(),
            "reason": reason,
        },
    )
    return session


def attendance_state(shift, *, at=None):
    now = at or timezone.now()
    if shift.status == Shift.Status.CANCELLED:
        return {"code": "CANCELLED", "label": "Cancelled", "missing_clock_out": False}
    session = getattr(shift, "attendance_session", None)
    if session is None:
        if now < shift.scheduled_start:
            return {"code": "SCHEDULED", "label": "Scheduled", "missing_clock_out": False}
        if now < shift.scheduled_end:
            return {"code": "LATE", "label": "Late", "missing_clock_out": False}
        return {"code": "ABSENT", "label": "Absent", "missing_clock_out": False}
    effective = effective_attendance_values(session)
    if effective["clock_out_at"] is not None:
        return {"code": "COMPLETED", "label": "Completed", "missing_clock_out": False}
    if session.status == AttendanceSession.Status.ON_BREAK:
        code, label = "ON_BREAK", "On break"
    else:
        code, label = "WORKING", "Working"
    return {
        "code": code,
        "label": label,
        "missing_clock_out": now >= shift.scheduled_end,
    }


def last_activity(session):
    if session is None:
        return None
    effective = effective_attendance_values(session)
    if effective["clock_out_at"]:
        return effective["clock_out_at"]
    breaks = effective["breaks"]
    open_break = next((item for item in breaks if item.ended_at is None), None)
    if open_break:
        return open_break.started_at
    completed_breaks = [item for item in breaks if item.ended_at is not None]
    latest_break = max(completed_breaks, key=lambda item: item.ended_at) if completed_breaks else None
    return latest_break.ended_at if latest_break else effective["clock_in_at"]
from datetime import timedelta
