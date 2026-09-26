from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from employees.models import Employee
from schedules.models import Shift
from .models import AttendanceSession, BreakSession


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
    if session.employee_id != employee.pk:
        raise PermissionDenied
    return session


@transaction.atomic
def start_break(*, session, employee, actor, at=None):
    now = at or timezone.now()
    session = _locked_owned_session(session, employee, actor)
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
    if session.clock_out_at is not None:
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
    if session.clock_out_at:
        return session.clock_out_at
    breaks = list(session.breaks.all())
    open_break = next((item for item in breaks if item.ended_at is None), None)
    if open_break:
        return open_break.started_at
    completed_breaks = [item for item in breaks if item.ended_at is not None]
    latest_break = max(completed_breaks, key=lambda item: item.ended_at) if completed_breaks else None
    return latest_break.ended_at if latest_break else session.clock_in_at
from datetime import timedelta
