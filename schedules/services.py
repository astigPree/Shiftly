from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from .models import Shift


def _attendance_has_started(shift):
    try:
        AttendanceSession = apps.get_model("attendance", "AttendanceSession")
    except LookupError:
        return False
    return AttendanceSession.objects.filter(shift=shift).exists()


def _validate_assignment(organization, employee):
    if employee.organization_id != organization.pk:
        raise PermissionDenied("This employee belongs to another organization.")


def _validate_conflicts(shift, *, exclude_pk=None):
    same_date = Shift.objects.filter(
        employee=shift.employee,
        work_date=shift.work_date,
    )
    overlaps = Shift.objects.filter(
        employee=shift.employee,
        status=Shift.Status.SCHEDULED,
        scheduled_start__lt=shift.scheduled_end,
        scheduled_end__gt=shift.scheduled_start,
    )
    if exclude_pk:
        same_date = same_date.exclude(pk=exclude_pk)
        overlaps = overlaps.exclude(pk=exclude_pk)
    if same_date.exists():
        raise ValidationError({"work_date": "This employee already has a shift on that local work date."})
    if overlaps.exists():
        raise ValidationError({"employee": "This shift overlaps another scheduled shift for the employee."})


@transaction.atomic
def create_shift(*, organization, employee, work_date, scheduled_start, scheduled_end, scheduled_break_minutes):
    employee = type(employee).objects.select_for_update().get(pk=employee.pk)
    _validate_assignment(organization, employee)
    shift = Shift(
        organization=organization,
        employee=employee,
        work_date=work_date,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        scheduled_break_minutes=scheduled_break_minutes,
    )
    shift.full_clean()
    _validate_conflicts(shift)
    try:
        shift.save(force_insert=True)
    except IntegrityError as error:
        raise ValidationError("The employee already has a conflicting shift. Refresh and try again.") from error
    return shift


@transaction.atomic
def update_shift(shift, *, organization, employee, work_date, scheduled_start, scheduled_end, scheduled_break_minutes):
    shift = Shift.objects.select_for_update().get(pk=shift.pk, organization=organization)
    if shift.status != Shift.Status.SCHEDULED:
        raise ValidationError("Cancelled shifts cannot be edited.")
    if _attendance_has_started(shift):
        raise ValidationError("A shift cannot be edited after attendance has started.")

    employee = type(employee).objects.select_for_update().get(pk=employee.pk)
    _validate_assignment(organization, employee)
    shift.employee = employee
    shift.work_date = work_date
    shift.scheduled_start = scheduled_start
    shift.scheduled_end = scheduled_end
    shift.scheduled_break_minutes = scheduled_break_minutes
    shift.full_clean()
    _validate_conflicts(shift, exclude_pk=shift.pk)
    try:
        shift.save(update_fields=[
            "employee", "work_date", "scheduled_start", "scheduled_end",
            "scheduled_break_minutes", "updated_at",
        ])
    except IntegrityError as error:
        raise ValidationError("The employee already has a conflicting shift. Refresh and try again.") from error
    return shift


@transaction.atomic
def cancel_shift(shift, *, organization):
    shift = Shift.objects.select_for_update().get(pk=shift.pk, organization=organization)
    if shift.status == Shift.Status.CANCELLED:
        return shift
    if _attendance_has_started(shift):
        raise ValidationError("A shift cannot be cancelled after attendance has started.")
    shift.status = Shift.Status.CANCELLED
    shift.save(update_fields=["status", "updated_at"])
    return shift
