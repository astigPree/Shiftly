from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from accounts.permissions import organization_for_user
from audit.models import AuditEvent
from audit.services import record_event
from schedules.models import Shift
from attendance.models import AttendanceSession
from .calculations import TimesheetCalculationError, calculate_timesheet
from .models import Timesheet, TimesheetApproval


@transaction.atomic
def generate_timesheet(attendance_session):
    session = (
        AttendanceSession.objects.select_for_update()
        .select_related("shift", "employee", "organization")
        .get(pk=attendance_session.pk)
    )
    if session.clock_out_at is None or session.status != AttendanceSession.Status.COMPLETED:
        raise ValidationError("A timesheet is created only after clock-out.")
    shift = Shift.objects.select_for_update().get(pk=session.shift_id)
    existing = Timesheet.objects.filter(shift=shift).first()
    if existing:
        return existing

    break_sessions = list(session.breaks.order_by("started_at", "id"))
    values = {
        "scheduled_minutes": 0,
        "break_minutes": 0,
        "worked_minutes": 0,
        "payable_minutes": 0,
        "late_minutes": 0,
        "undertime_minutes": 0,
    }
    status = Timesheet.Status.PENDING
    review_reason = ""
    try:
        calculated = calculate_timesheet(shift, session, break_sessions)
        values = {
            "scheduled_minutes": calculated.scheduled_minutes,
            "break_minutes": calculated.break_minutes,
            "worked_minutes": calculated.worked_minutes,
            "payable_minutes": calculated.payable_minutes,
            "late_minutes": calculated.late_minutes,
            "undertime_minutes": calculated.undertime_minutes,
        }
    except TimesheetCalculationError as error:
        status = Timesheet.Status.NEEDS_REVIEW
        review_reason = str(error)

    try:
        with transaction.atomic():
            return Timesheet.objects.create(
                organization=session.organization,
                employee=session.employee,
                shift=shift,
                attendance_session=session,
                status=status,
                review_reason=review_reason,
                **values,
            )
    except IntegrityError:
        return Timesheet.objects.get(shift=shift)


@transaction.atomic
def review_timesheet(*, timesheet, reviewer, action, comment=""):
    if not reviewer.is_authenticated or reviewer.role != User.Role.EMPLOYER:
        raise PermissionDenied("Only the employer can review timesheets.")
    organization = organization_for_user(reviewer)
    if organization is None or organization.pk != timesheet.organization_id:
        raise PermissionDenied("You cannot review a timesheet from another organization.")

    timesheet = Timesheet.objects.select_for_update().get(
        pk=timesheet.pk,
        organization=organization,
    )
    comment = (comment or "").strip()
    if action == TimesheetApproval.Action.APPROVED:
        if timesheet.status != Timesheet.Status.PENDING:
            raise ValidationError("Only pending timesheets can be approved.")
        timesheet.status = Timesheet.Status.APPROVED
    elif action == TimesheetApproval.Action.REJECTED:
        if timesheet.status not in (Timesheet.Status.PENDING, Timesheet.Status.NEEDS_REVIEW):
            raise ValidationError("This timesheet has already been decided.")
        if not comment:
            raise ValidationError("Add a comment explaining why the timesheet is rejected.")
        timesheet.status = Timesheet.Status.REJECTED
    else:
        raise ValidationError("Choose a valid review action.")

    timesheet.save(update_fields=["status", "updated_at"])
    approval = TimesheetApproval.objects.create(
        timesheet=timesheet,
        reviewer=reviewer,
        action=action,
        comment=comment,
        reviewed_at=timezone.now(),
    )
    audit_action = (
        AuditEvent.Action.TIMESHEET_APPROVED
        if action == TimesheetApproval.Action.APPROVED
        else AuditEvent.Action.TIMESHEET_REJECTED
    )
    record_event(
        organization=organization,
        actor=reviewer,
        action=audit_action,
        target_type="timesheet",
        target_id=timesheet.pk,
        summary=f"{timesheet.get_status_display()} timesheet for {timesheet.employee.employee_code}.",
        metadata={"status": timesheet.status},
    )
    return timesheet, approval
