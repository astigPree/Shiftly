from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from attendance.models import BreakSession
from attendance.services import attendance_state, last_activity
from audit.models import AuditEvent
from audit.services import record_event
from employees.models import Employee
from organizations.models import Organization
from schedules.models import Shift
from timesheets.models import Timesheet


def employer_dashboard_data(organization, now=None):
    now = now or timezone.now()
    org_timezone = ZoneInfo(organization.timezone)
    local_now = timezone.localtime(now, org_timezone)
    local_today = local_now.date()
    shifts = (
        Shift.objects.filter(
            organization=organization,
            work_date=local_today,
            status=Shift.Status.SCHEDULED,
        )
        .select_related("employee", "organization", "attendance_session")
        .prefetch_related("attendance_session__breaks")
        .order_by("scheduled_start", "employee__last_name", "employee__first_name")
    )
    rows = []
    counts = {"ON_SHIFT": 0, "LATE": 0, "ABSENT": 0, "MISSING_CLOCK_OUT": 0}
    for shift in shifts:
        session = getattr(shift, "attendance_session", None)
        state = attendance_state(shift, at=now)
        late_clock_in = bool(session and session.clock_in_at > shift.scheduled_start)
        if state["code"] in ("WORKING", "ON_BREAK"):
            counts["ON_SHIFT"] += 1
        if state["code"] == "LATE" or late_clock_in:
            counts["LATE"] += 1
        if state["code"] == "ABSENT":
            counts["ABSENT"] += 1
        if state.get("missing_clock_out"):
            counts["MISSING_CLOCK_OUT"] += 1
        rows.append(
            {
                "shift": shift,
                "session": session,
                "state": state,
                "late_clock_in": late_clock_in,
                "last_activity": last_activity(session),
            }
        )
    timesheet_counts = {
        row["status"]: row["total"]
        for row in Timesheet.objects.filter(organization=organization)
        .values("status")
        .annotate(total=Count("pk"))
    }
    active_employee_count = Employee.objects.filter(
        organization=organization,
        status=Employee.Status.ACTIVE,
    ).count()
    attention_count = (
        timesheet_counts.get(Timesheet.Status.PENDING, 0)
        + timesheet_counts.get(Timesheet.Status.NEEDS_REVIEW, 0)
        + counts["MISSING_CLOCK_OUT"]
    )
    return {
        "local_today": local_today,
        "local_now": local_now,
        "updated_at": local_now,
        "greeting_period": (
            "morning" if local_now.hour < 12
            else "afternoon" if local_now.hour < 17
            else "evening"
        ),
        "active_employee_count": active_employee_count,
        "can_schedule_shift": active_employee_count > 0,
        "on_shift_count": counts["ON_SHIFT"],
        "late_count": counts["LATE"],
        "absent_count": counts["ABSENT"],
        "missing_clock_out_count": counts["MISSING_CLOCK_OUT"],
        "pending_timesheet_count": timesheet_counts.get(Timesheet.Status.PENDING, 0),
        "needs_review_timesheet_count": timesheet_counts.get(Timesheet.Status.NEEDS_REVIEW, 0),
        "attention_count": attention_count,
        "has_attention": attention_count > 0,
        "attendance_rows": rows[:5],
        "today_shift_count": len(rows),
        "dashboard_empty_state": "no_employees" if active_employee_count == 0 else "no_shifts",
    }


@transaction.atomic
def save_organization_settings(*, organization, user, organization_name, timezone_name):
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    previous_name = organization.name
    previous_timezone = organization.timezone
    timezone_locked = organization.shifts.exists()
    if timezone_locked and timezone_name != organization.timezone:
        raise ValidationError({"timezone": "The organization time zone is locked after its first shift."})
    organization.name = organization_name
    organization.timezone = timezone_name if not timezone_locked else organization.timezone
    organization.save(update_fields=["name", "timezone", "updated_at"])
    changed_fields = []
    if previous_name != organization.name:
        changed_fields.append("name")
    if previous_timezone != organization.timezone:
        changed_fields.append("timezone")
    if changed_fields:
        record_event(
            organization=organization,
            actor=user,
            action=AuditEvent.Action.ORGANIZATION_UPDATED,
            target_type="organization",
            target_id=organization.pk,
            summary="Updated organization settings.",
            metadata={"changed_fields": changed_fields},
        )
    return organization


@transaction.atomic
def save_employer_profile(*, user, first_name, last_name, preferred_timezone=None):
    user.first_name = first_name
    user.last_name = last_name
    update_fields = ["first_name", "last_name"]
    if preferred_timezone is not None:
        user.preferred_timezone = preferred_timezone
        update_fields.append("preferred_timezone")
    user.save(update_fields=update_fields)


@transaction.atomic
def save_workspace_settings(*, organization, user, organization_name, timezone_name, first_name, last_name):
    organization = save_organization_settings(
        organization=organization,
        user=user,
        organization_name=organization_name,
        timezone_name=timezone_name,
    )
    save_employer_profile(user=user, first_name=first_name, last_name=last_name)
    return organization
