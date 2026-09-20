from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.permissions import employee_required, employer_required, organization_for_user
from employees.models import Employee
from schedules.models import Shift
from timesheets.models import Timesheet
from .models import AttendanceSession, BreakSession
from .services import attendance_state, clock_in, clock_out, end_break, last_activity, start_break


def _with_attendance(queryset):
    return queryset.select_related("attendance_session").prefetch_related(
        Prefetch("attendance_session__breaks", queryset=BreakSession.objects.order_by("started_at"))
    )


def _duration_label(seconds):
    minutes = max(0, seconds) // 60
    hours, minutes = divmod(minutes, 60)
    return f"{hours} hr {minutes:02d} min" if hours else f"{minutes} min"


def _minutes_label(minutes):
    hours, minutes = divmod(max(0, minutes), 60)
    return f"{hours} hr {minutes:02d} min" if hours else f"{minutes} min"


@employer_required
@require_GET
def attendance_list(request):
    organization = organization_for_user(request.user)
    local_today = timezone.localdate(timezone=ZoneInfo(organization.timezone))
    raw_date = request.GET.get("date", "")
    try:
        selected_date = date.fromisoformat(raw_date) if raw_date else local_today
    except ValueError:
        selected_date = local_today
    status_filter = request.GET.get("status", "").upper()
    allowed_statuses = ["SCHEDULED", "LATE", "ABSENT", "WORKING", "ON_BREAK", "COMPLETED", "CANCELLED"]
    if status_filter not in allowed_statuses:
        status_filter = ""
    shifts = _with_attendance(
        Shift.objects.filter(organization=organization, work_date=selected_date)
        .select_related("employee", "organization")
        .order_by("scheduled_start", "employee__last_name")
    )
    now = timezone.now()
    rows = []
    for shift in shifts:
        state = attendance_state(shift, at=now)
        session = getattr(shift, "attendance_session", None)
        late_clock_in = bool(session and session.clock_in_at > shift.scheduled_start)
        if status_filter == "LATE":
            if state["code"] != "LATE" and not late_clock_in:
                continue
        elif status_filter == "WORKING":
            if state["code"] not in ("WORKING", "ON_BREAK"):
                continue
        elif status_filter and status_filter != state["code"]:
            continue
        rows.append(
            {
                "shift": shift,
                "session": session,
                "state": state,
                "last_activity": last_activity(session),
                "late_clock_in": late_clock_in,
            }
        )
    page = Paginator(rows, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "attendance/list.html",
        {
            "page": page,
            "selected_date": selected_date,
            "status_filter": status_filter,
            "status_choices": [
                ("SCHEDULED", "Scheduled"), ("LATE", "Late"), ("ABSENT", "Absent"),
                ("WORKING", "Working"), ("ON_BREAK", "On break"), ("COMPLETED", "Completed"),
                ("CANCELLED", "Cancelled"),
            ],
            "organization": organization,
            "local_today": local_today,
        },
    )


@employee_required
@require_GET
def my_attendance(request):
    employee = request.user.employee_profile
    organization = employee.organization
    now = timezone.now()
    today = timezone.localdate(now, timezone=ZoneInfo(organization.timezone))
    week_start = today - timedelta(days=today.weekday())
    shifts = _with_attendance(
        Shift.objects.filter(employee=employee, organization=organization)
        .filter(
            Q(work_date__range=(today, today + timedelta(days=7)))
            | Q(attendance_session__isnull=False, attendance_session__clock_out_at__isnull=True)
        )
        .select_related("organization", "employee")
        .order_by("work_date", "scheduled_start")
    )
    cards = []
    for shift in shifts:
        session = getattr(shift, "attendance_session", None)
        state = attendance_state(shift, at=now)
        breaks = list(session.breaks.all()) if session else []
        completed_break_seconds = sum(
            int((item.ended_at - item.started_at).total_seconds())
            for item in breaks if item.ended_at
        )
        active_break = next((item for item in breaks if item.ended_at is None), None)
        worked_seconds = 0
        break_seconds = completed_break_seconds
        if session:
            end = session.clock_out_at or now
            elapsed = max(0, int((end - session.clock_in_at).total_seconds()))
            if active_break:
                break_seconds += max(0, int((now - active_break.started_at).total_seconds()))
                elapsed -= max(0, int((now - active_break.started_at).total_seconds()))
            worked_seconds = max(0, elapsed - completed_break_seconds)
        can_clock_in = (
            session is None
            and shift.status == Shift.Status.SCHEDULED
            and now >= shift.scheduled_start - timedelta(minutes=30)
            and now < shift.scheduled_end
        )
        cards.append(
            {
                "shift": shift,
                "session": session,
                "timesheet": getattr(session, "timesheet", None) if session else None,
                "state": state,
                "can_clock_in": can_clock_in,
                "last_activity": last_activity(session),
                "breaks": breaks,
                "worked_seconds": worked_seconds,
                "break_seconds": break_seconds,
                "work_timer_running": bool(session and not session.clock_out_at and session.status == AttendanceSession.Status.WORKING),
                "break_timer_running": bool(active_break),
                "active_break": active_break,
                "worked_duration_label": _duration_label(worked_seconds),
                "break_duration_label": _duration_label(break_seconds),
            }
        )
    today_card = next((card for card in cards if card["shift"].work_date == today), None)
    active_card = next((card for card in cards if card["session"] and not card["session"].clock_out_at), None)
    focus_card = active_card or today_card
    upcoming_card = next((card for card in cards if card["shift"].work_date > today), None)
    weekly_minutes = Timesheet.objects.filter(
        organization=organization,
        employee=employee,
        shift__work_date__range=(week_start, week_start + timedelta(days=6)),
    ).aggregate(total=Sum("worked_minutes"))["total"] or 0
    recent_timesheets = (
        Timesheet.objects.filter(organization=organization, employee=employee)
        .select_related("shift")[:5]
    )
    return render(
        request,
        "attendance/my_attendance.html",
        {
            "cards": cards,
            "today_card": today_card,
            "focus_card": focus_card,
            "upcoming_card": upcoming_card,
            "weekly_minutes": weekly_minutes,
            "weekly_hours_label": _minutes_label(weekly_minutes),
            "week_start": week_start,
            "recent_timesheets": recent_timesheets,
            "organization": organization,
            "now": now,
            "local_today": today,
        },
    )


def _employee_shift(request, pk):
    employee = request.user.employee_profile
    return employee, get_object_or_404(
        Shift.objects.filter(organization=employee.organization, employee=employee), pk=pk
    )


def _employee_session(request, pk):
    employee = request.user.employee_profile
    return employee, get_object_or_404(
        AttendanceSession.objects.filter(organization=employee.organization, employee=employee), pk=pk
    )


@employee_required
@require_POST
def clock_in_action(request, shift_pk):
    employee, shift = _employee_shift(request, shift_pk)
    try:
        clock_in(shift=shift, employee=employee, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "You are clocked in.")
    return redirect("attendance:my_attendance")


@employee_required
@require_POST
def start_break_action(request, session_pk):
    employee, session = _employee_session(request, session_pk)
    try:
        start_break(session=session, employee=employee, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Your break has started.")
    return redirect("attendance:my_attendance")


@employee_required
@require_POST
def end_break_action(request, session_pk):
    employee, session = _employee_session(request, session_pk)
    try:
        end_break(session=session, employee=employee, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Your break has ended.")
    return redirect("attendance:my_attendance")


@employee_required
@require_POST
def clock_out_action(request, session_pk):
    employee, session = _employee_session(request, session_pk)
    try:
        clock_out(session=session, employee=employee, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "You are clocked out. Your completed timesheet is ready for review.")
    return redirect("attendance:my_attendance")
