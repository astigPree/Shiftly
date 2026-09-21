from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from audit.models import AuditEvent
from audit.services import record_event
from employees.models import Employee
from organizations.models import Organization
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
def create_shift(*, organization, employee, work_date, scheduled_start, scheduled_end, scheduled_break_minutes, actor):
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
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
    record_event(
        organization=organization,
        actor=actor,
        action=AuditEvent.Action.SHIFT_CREATED,
        target_type="shift",
        target_id=shift.pk,
        summary=f"Scheduled shift for employee {employee.employee_code}.",
        metadata={
            "employee_id": employee.pk,
            "work_date": shift.work_date.isoformat(),
            "scheduled_start": shift.scheduled_start.isoformat(),
            "scheduled_end": shift.scheduled_end.isoformat(),
            "scheduled_break_minutes": shift.scheduled_break_minutes,
        },
    )
    return shift


@transaction.atomic
def create_shifts(
    *, organization, employees, shift_intervals, scheduled_break_minutes, actor,
):
    """Create each selected employee's shifts for all requested work dates."""
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    employee_ids = {employee.pk for employee in employees}
    if not employee_ids or not shift_intervals:
        raise ValidationError("Select at least one employee and work date.")
    locked_employees = list(
        Employee.objects.select_for_update()
        .filter(
            pk__in=employee_ids,
            organization=organization,
            status=Employee.Status.ACTIVE,
        )
        .order_by("pk")
    )
    if len(locked_employees) != len(employee_ids):
        raise ValidationError(
            "One or more selected employees are no longer active in this organization. Refresh and review the selection."
        )

    created_shifts = []
    for employee in locked_employees:
        for interval in sorted(shift_intervals, key=lambda item: item["work_date"]):
            try:
                shift = create_shift(
                    organization=organization,
                    employee=employee,
                    work_date=interval["work_date"],
                    scheduled_start=interval["scheduled_start"],
                    scheduled_end=interval["scheduled_end"],
                    scheduled_break_minutes=scheduled_break_minutes,
                    actor=actor,
                )
            except ValidationError as error:
                raise ValidationError(
                    f"{employee.full_name} on {interval['work_date']}: "
                    f"{' '.join(error.messages)}"
                ) from error
            created_shifts.append(shift)
    return created_shifts


@transaction.atomic
def update_shift(shift, *, organization, employee, work_date, scheduled_start, scheduled_end, scheduled_break_minutes, actor):
    shift = Shift.objects.select_for_update().get(pk=shift.pk, organization=organization)
    if shift.status != Shift.Status.SCHEDULED:
        raise ValidationError("Cancelled shifts cannot be edited.")
    if _attendance_has_started(shift):
        raise ValidationError("A shift cannot be edited after attendance has started.")

    before = {
        "employee_id": shift.employee_id,
        "work_date": shift.work_date,
        "scheduled_start": shift.scheduled_start,
        "scheduled_end": shift.scheduled_end,
        "scheduled_break_minutes": shift.scheduled_break_minutes,
    }
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
    after = {
        "employee_id": shift.employee_id,
        "work_date": shift.work_date,
        "scheduled_start": shift.scheduled_start,
        "scheduled_end": shift.scheduled_end,
        "scheduled_break_minutes": shift.scheduled_break_minutes,
    }
    changed_fields = [field for field, old_value in before.items() if old_value != after[field]]
    if changed_fields:
        record_event(
            organization=organization,
            actor=actor,
            action=AuditEvent.Action.SHIFT_UPDATED,
            target_type="shift",
            target_id=shift.pk,
            summary=f"Updated shift for employee {employee.employee_code}.",
            metadata={
                "changed_fields": changed_fields,
                "work_date": shift.work_date.isoformat(),
                "scheduled_start": shift.scheduled_start.isoformat(),
                "scheduled_end": shift.scheduled_end.isoformat(),
            },
        )
    return shift


@transaction.atomic
def cancel_shift(shift, *, organization, actor):
    shift = Shift.objects.select_for_update().get(pk=shift.pk, organization=organization)
    if shift.status == Shift.Status.CANCELLED:
        return shift
    if _attendance_has_started(shift):
        raise ValidationError("A shift cannot be cancelled after attendance has started.")
    shift.status = Shift.Status.CANCELLED
    shift.save(update_fields=["status", "updated_at"])
    record_event(
        organization=organization,
        actor=actor,
        action=AuditEvent.Action.SHIFT_CANCELLED,
        target_type="shift",
        target_id=shift.pk,
        summary=f"Cancelled shift for employee {shift.employee.employee_code}.",
        metadata={"work_date": shift.work_date.isoformat()},
    )
    return shift
