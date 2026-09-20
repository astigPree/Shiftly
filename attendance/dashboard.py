from django.db.models import Prefetch
from django.utils import timezone

from schedules.models import Shift

from .models import BreakSession
from .services import attendance_state


def _last_activity(session):
    if session is None:
        return None, ""
    if session.clock_out_at:
        return session.clock_out_at, "Clocked out"

    breaks = list(session.breaks.all())
    open_break = next((item for item in breaks if item.ended_at is None), None)
    if open_break:
        return open_break.started_at, "Break started"

    completed_breaks = [item for item in breaks if item.ended_at is not None]
    if completed_breaks:
        latest_break = max(completed_breaks, key=lambda item: item.ended_at)
        return latest_break.ended_at, "Break ended"

    return session.clock_in_at, "Clocked in"


def _matches_status(row, status_filter):
    if not status_filter:
        return True
    if status_filter == "WORKING":
        return row["state"]["code"] in ("WORKING", "ON_BREAK")
    if status_filter == "LATE":
        return row["is_late"]
    if status_filter == "OPEN_CLOCKOUT":
        return row["state"]["missing_clock_out"]
    if status_filter == "NEEDS_FOLLOWUP":
        return row["needs_follow_up"]
    return row["state"]["code"] == status_filter


def get_employer_attendance_dashboard(
    *, organization, work_date, status_filter="", search_query="", at=None
):
    """Build the date-wide summary and filtered rows for the employer monitor."""
    updated_at = at or timezone.now()
    search_term = search_query.casefold()
    shifts = (
        Shift.objects.filter(organization=organization, work_date=work_date)
        .select_related("employee", "organization", "attendance_session")
        .prefetch_related(
            Prefetch(
                "attendance_session__breaks",
                queryset=BreakSession.objects.order_by("started_at"),
            )
        )
        .order_by("scheduled_start", "employee__last_name")
    )

    all_rows = []
    summary = {"on_shift": 0, "late": 0, "absent": 0, "open_clockouts": 0}
    for shift in shifts:
        state = attendance_state(shift, at=updated_at)
        session = getattr(shift, "attendance_session", None)
        late_clock_in = bool(session and session.clock_in_at > shift.scheduled_start)
        late_minutes = 0
        if late_clock_in:
            late_seconds = (session.clock_in_at - shift.scheduled_start).total_seconds()
            late_minutes = max(1, int((late_seconds + 59) // 60))

        exceptions = []
        if late_clock_in:
            exceptions.append(f"{late_minutes} min late")
        if state["missing_clock_out"]:
            exceptions.append("Missing clock-out")

        last_activity_at, last_activity_label = _last_activity(session)
        if session is not None:
            activity_text = ""
        elif state["code"] == "SCHEDULED":
            activity_text = "No attendance yet"
        elif state["code"] == "LATE":
            activity_text = "No clock-in recorded"
        elif state["code"] == "ABSENT":
            activity_text = "No attendance recorded"
        elif state["code"] == "CANCELLED":
            activity_text = "Shift cancelled"
        else:
            activity_text = "No attendance recorded"
        is_late = late_clock_in or state["code"] == "LATE"
        needs_follow_up = is_late or state["code"] == "ABSENT" or state["missing_clock_out"]
        row = {
            "shift": shift,
            "session": session,
            "state": state,
            "late_clock_in": late_clock_in,
            "late_minutes": late_minutes,
            "is_late": is_late,
            "needs_follow_up": needs_follow_up,
            "last_activity_at": last_activity_at,
            "last_activity_label": last_activity_label,
            "activity_text": activity_text,
            "exceptions": exceptions,
        }
        all_rows.append(row)

        if state["code"] in ("WORKING", "ON_BREAK"):
            summary["on_shift"] += 1
        if row["is_late"]:
            summary["late"] += 1
        if state["code"] == "ABSENT":
            summary["absent"] += 1
        if state["missing_clock_out"]:
            summary["open_clockouts"] += 1

    filtered_rows = []
    for row in all_rows:
        if not _matches_status(row, status_filter):
            continue
        if search_term:
            employee = row["shift"].employee
            searchable_text = " ".join(
                (
                    employee.full_name,
                    employee.employee_code,
                    employee.email,
                    employee.job_title,
                )
            ).casefold()
            if search_term not in searchable_text:
                continue
        filtered_rows.append(row)

    return {
        "rows": filtered_rows,
        "summary": summary,
        "updated_at": updated_at,
        "total_date_shifts": len(all_rows),
        "follow_up_count": sum(row["needs_follow_up"] for row in all_rows),
    }
