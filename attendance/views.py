from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import employee_required, employer_required, organization_for_user
from employees.models import Employee
from schedules.models import Shift
from .models import AttendanceSession, BreakSession
from .services import attendance_state, clock_in, clock_out, end_break, last_activity, start_break


def _with_attendance(queryset):
    return queryset.select_related("attendance_session").prefetch_related(
        Prefetch("attendance_session__breaks", queryset=BreakSession.objects.order_by("started_at"))
    )


@employer_required
def attendance_list(request):
    organization = organization_for_user(request.user)
    local_today = timezone.localdate(timezone=ZoneInfo(organization.timezone))
    raw_date = request.GET.get("date", "")
    try:
        selected_date = date.fromisoformat(raw_date) if raw_date else local_today
    except ValueError:
        selected_date = local_today
    status_filter = request.GET.get("status", "").upper()
    shifts = _with_attendance(
        Shift.objects.filter(organization=organization, work_date=selected_date)
        .select_related("employee", "organization")
        .order_by("scheduled_start", "employee__last_name")
    )
    now = timezone.now()
    rows = []
    for shift in shifts:
        state = attendance_state(shift, at=now)
        if status_filter and status_filter != state["code"]:
            continue
        session = getattr(shift, "attendance_session", None)
        rows.append(
            {
                "shift": shift,
                "session": session,
                "state": state,
                "last_activity": last_activity(session),
                "late_clock_in": bool(session and session.clock_in_at > shift.scheduled_start),
            }
        )
    allowed_statuses = ["SCHEDULED", "LATE", "ABSENT", "WORKING", "ON_BREAK", "COMPLETED", "CANCELLED"]
    if status_filter not in allowed_statuses:
        status_filter = ""
        rows = []
        for shift in shifts:
            state = attendance_state(shift, at=now)
            session = getattr(shift, "attendance_session", None)
            rows.append({"shift": shift, "session": session, "state": state, "last_activity": last_activity(session), "late_clock_in": bool(session and session.clock_in_at > shift.scheduled_start)})
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
        },
    )


@employee_required
def my_attendance(request):
    employee = request.user.employee_profile
    organization = employee.organization
    now = timezone.now()
    today = timezone.localdate(now, timezone=ZoneInfo(organization.timezone))
    shifts = _with_attendance(
        Shift.objects.filter(employee=employee)
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
                "state": state,
                "can_clock_in": can_clock_in,
                "last_activity": last_activity(session),
            }
        )
    return render(
        request,
        "attendance/my_attendance.html",
        {"cards": cards, "organization": organization, "now": now},
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
