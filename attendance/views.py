from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.permissions import employee_required, employer_required, organization_for_user
from employees.models import Employee
from schedules.models import Shift
from timesheets.models import Timesheet
from .dashboard import get_employer_attendance_dashboard
from .forms import AttendanceCorrectionForm, AttendanceManualEntryForm
from .models import AttendanceCorrection, AttendanceSession, BreakSession
from .services import (
    attendance_state,
    clock_in,
    clock_out,
    correct_attendance,
    effective_attendance_values,
    end_break,
    last_activity,
    record_attendance,
    start_break,
)


def _with_attendance(queryset):
    return queryset.select_related("attendance_session").prefetch_related(
        Prefetch("attendance_session__breaks", queryset=BreakSession.objects.order_by("started_at")),
        Prefetch("attendance_session__corrections", queryset=AttendanceCorrection.objects.order_by("-created_at", "-pk")),
    )


def _duration_label(seconds):
    minutes = max(0, seconds) // 60
    hours, minutes = divmod(minutes, 60)
    return f"{hours} hr {minutes:02d} min" if hours else f"{minutes} min"


def _minutes_label(minutes):
    hours, minutes = divmod(max(0, minutes), 60)
    return f"{hours} hr {minutes:02d} min" if hours else f"{minutes} min"


def _add_attendance_validation_errors(form, error):
    """Keep service validation attached to the field the employer can fix."""
    field_map = {
        "corrected_clock_in_at": "clock_in_at",
        "corrected_clock_out_at": "clock_out_at",
        "reason": "reason",
    }
    error_labels = {
        "original_breaks": "Break corrections",
        "corrected_breaks": "Break corrections",
    }
    message_dict = getattr(error, "message_dict", None)
    if not message_dict:
        form.add_error(None, " ".join(error.messages))
        return

    for source_field, messages in message_dict.items():
        target_field = field_map.get(source_field, source_field)
        if target_field in form.fields:
            for message in messages:
                form.add_error(target_field, message)
            continue
        label = error_labels.get(source_field, source_field.replace("_", " ").capitalize())
        form.add_error(None, f"{label}: {' '.join(messages)}")


def _employee_duration_label(minutes):
    hours, minutes = divmod(max(0, minutes), 60)
    return f"{hours}h {minutes:02d}m"


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
    allowed_statuses = [
        "SCHEDULED", "LATE", "ABSENT", "WORKING", "ON_BREAK", "COMPLETED",
        "CANCELLED", "OPEN_CLOCKOUT", "NEEDS_FOLLOWUP",
    ]
    if status_filter not in allowed_statuses:
        status_filter = ""
    search_query = request.GET.get("q", "").strip()[:100]
    dashboard = get_employer_attendance_dashboard(
        organization=organization,
        work_date=selected_date,
        status_filter=status_filter,
        search_query=search_query,
    )
    page = Paginator(dashboard["rows"], 30).get_page(request.GET.get("page"))
    return render(
        request,
        "attendance/list.html",
        {
            "page": page,
            "summary": dashboard["summary"],
            "updated_at": dashboard["updated_at"],
            "total_date_shifts": dashboard["total_date_shifts"],
            "follow_up_count": dashboard["follow_up_count"],
            "selected_date": selected_date,
            "status_filter": status_filter,
            "search_query": search_query,
            "showing_start": page.start_index() if page.object_list else 0,
            "showing_end": page.end_index() if page.object_list else 0,
            "status_choices": [
                ("SCHEDULED", "Scheduled"), ("LATE", "Late"), ("ABSENT", "Absent"),
                ("WORKING", "Working"), ("ON_BREAK", "On break"), ("COMPLETED", "Completed"),
                ("CANCELLED", "Cancelled"), ("OPEN_CLOCKOUT", "Open clock-outs"),
                ("NEEDS_FOLLOWUP", "Needs follow-up"),
            ],
            "organization": organization,
            "local_today": local_today,
        },
    )


def _attendance_correction_context(request, session, form=None):
    organization = organization_for_user(request.user)
    effective = effective_attendance_values(session)
    timezone_name = getattr(getattr(session.employee, "payroll_profile", None), "payroll_timezone", "") or organization.timezone
    initial_breaks = [(item.started_at, item.ended_at) for item in effective["breaks"]]
    effective_local_date = (
        timezone.localtime(effective["clock_in_at"], ZoneInfo(timezone_name)).date()
        if effective["clock_in_at"]
        else None
    )
    if form is None:
        form = AttendanceCorrectionForm(
            timezone_name=timezone_name,
            initial={
                "clock_in_at": form_datetime_value(effective["clock_in_at"], timezone_name),
                "clock_out_at": form_datetime_value(effective["clock_out_at"], timezone_name),
            },
            initial_breaks=initial_breaks,
        )
    locked = _attendance_is_locked(session)
    return {
        "session": session,
        "shift": session.shift,
        "employee": session.employee,
        "organization": organization,
        "timezone_name": timezone_name,
        "effective": effective,
        "effective_local_date": effective_local_date,
        "effective_date_mismatch": bool(
            effective_local_date and effective_local_date != session.shift.work_date
        ),
        "corrections": session.corrections.select_related("created_by"),
        "form": form,
        "is_locked": locked,
    }


def form_datetime_value(value, timezone_name):
    if value is None:
        return ""
    return timezone.localtime(value, ZoneInfo(timezone_name)).strftime("%Y-%m-%dT%H:%M")


@employer_required
def record_attendance_page(request, shift_pk):
    organization = organization_for_user(request.user)
    shift = get_object_or_404(
        Shift.objects.filter(organization=organization)
        .select_related("employee", "employee__payroll_profile", "organization"),
        pk=shift_pk,
    )
    if hasattr(shift, "attendance_session"):
        messages.info(request, "This shift already has attendance. Review the existing record instead.")
        return redirect("attendance:correct", session_pk=shift.attendance_session.pk)
    timezone_name = getattr(getattr(shift.employee, "payroll_profile", None), "payroll_timezone", "") or organization.timezone
    initial = {
        "clock_in_at": form_datetime_value(shift.scheduled_start, timezone_name),
        "clock_out_at": form_datetime_value(shift.scheduled_end, timezone_name),
    }
    form = AttendanceManualEntryForm(
        request.POST or None,
        timezone_name=timezone_name,
        initial=initial,
        initial_breaks=[],
    )
    if request.method == "POST" and form.is_valid():
        try:
            session = record_attendance(
                shift=shift,
                actor=request.user,
                clock_in_at=form.cleaned_data["corrected_clock_in_at"],
                clock_out_at=form.cleaned_data["corrected_clock_out_at"],
                breaks=form.cleaned_data["corrected_breaks"],
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as error:
            _add_attendance_validation_errors(form, error)
        else:
            messages.success(request, "Attendance recorded. A timesheet was created and is ready for review.")
            return redirect("attendance:correct", session_pk=session.pk)
    return render(request, "attendance/record.html", {
        "organization": organization,
        "shift": shift,
        "employee": shift.employee,
        "timezone_name": timezone_name,
        "form": form,
    }, status=400 if request.method == "POST" and form.errors else 200)


def _attendance_is_locked(session):
    from payroll.models import PayrollRun, PayrollTimeEntry

    return PayrollTimeEntry.objects.filter(
        timesheet__attendance_session_id=session.pk,
        statement__run__status=PayrollRun.Status.FINALIZED,
    ).exists()


@employer_required
def correct_attendance_page(request, session_pk):
    organization = organization_for_user(request.user)
    session = get_object_or_404(
        AttendanceSession.objects.filter(organization=organization)
        .select_related("employee", "employee__payroll_profile", "shift", "organization")
        .prefetch_related(
            Prefetch("breaks", queryset=BreakSession.objects.order_by("started_at", "id")),
            Prefetch("corrections", queryset=AttendanceCorrection.objects.select_related("created_by").order_by("-created_at", "-pk")),
        ),
        pk=session_pk,
    )
    effective = effective_attendance_values(session)
    timezone_name = getattr(getattr(session.employee, "payroll_profile", None), "payroll_timezone", "") or organization.timezone
    initial_breaks = [(item.started_at, item.ended_at) for item in effective["breaks"]]
    effective_local_date = (
        timezone.localtime(effective["clock_in_at"], ZoneInfo(timezone_name)).date()
        if effective["clock_in_at"]
        else None
    )
    if request.method == "POST":
        form = AttendanceCorrectionForm(
            request.POST,
            timezone_name=timezone_name,
            initial_breaks=initial_breaks,
        )
        if form.is_valid():
            try:
                correct_attendance(
                    session=session,
                    actor=request.user,
                    corrected_clock_in_at=form.cleaned_data["corrected_clock_in_at"],
                    corrected_clock_out_at=form.cleaned_data["corrected_clock_out_at"],
                    corrected_breaks=form.cleaned_data["corrected_breaks"],
                    reason=form.cleaned_data["reason"],
                )
            except ValidationError as error:
                _add_attendance_validation_errors(form, error)
            else:
                messages.success(request, "Attendance corrected. The timesheet was recalculated and returned for review.")
                # Keep the employer on the correction record so the new
                # effective values and audit entry are immediately visible.
                return redirect(reverse("attendance:correct", args=[session.pk]))
    else:
        form_clock_in = effective["clock_in_at"]
        form_clock_out = effective["clock_out_at"]
        form_breaks = initial_breaks
        if effective_local_date and effective_local_date != session.shift.work_date:
            # A legacy correction may have been saved with the wrong local
            # calendar date. Start the repair form from the immutable employee
            # punch so the employer does not have to manually reconstruct it.
            form_clock_in = session.clock_in_at
            form_clock_out = session.clock_out_at
            form_breaks = [(item.started_at, item.ended_at) for item in session.breaks.all()]
        form = AttendanceCorrectionForm(
            timezone_name=timezone_name,
            initial={
                "clock_in_at": form_datetime_value(form_clock_in, timezone_name),
                "clock_out_at": form_datetime_value(form_clock_out, timezone_name),
            },
            initial_breaks=form_breaks,
        )
    context = _attendance_correction_context(request, session, form=form)
    return render(request, "attendance/correct.html", context, status=400 if request.method == "POST" and form.errors else 200)


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
            | Q(
                status=Shift.Status.SCHEDULED,
                scheduled_start__lte=now,
                scheduled_end__gt=now,
            )
            | Q(attendance_session__isnull=False, attendance_session__clock_out_at__isnull=True)
        )
        .select_related("organization", "employee")
        .order_by("work_date", "scheduled_start")
    )
    cards = []
    for shift in shifts:
        session = getattr(shift, "attendance_session", None)
        state = attendance_state(shift, at=now)
        effective = effective_attendance_values(session) if session else None
        breaks = effective["breaks"] if effective else []
        completed_break_seconds = sum(
            int((item.ended_at - item.started_at).total_seconds())
            for item in breaks if item.ended_at
        )
        active_break = next((item for item in breaks if item.ended_at is None), None)
        worked_seconds = 0
        break_seconds = completed_break_seconds
        if session:
            effective_clock_in = effective["clock_in_at"]
            effective_clock_out = effective["clock_out_at"]
            end = effective_clock_out or now
            elapsed = max(0, int((end - effective_clock_in).total_seconds()))
            if active_break:
                break_seconds += max(0, int((now - active_break.started_at).total_seconds()))
                elapsed -= max(0, int((now - active_break.started_at).total_seconds()))
            worked_seconds = max(0, elapsed - completed_break_seconds)
        show_clock_in = (
            session is None
            and shift.status == Shift.Status.SCHEDULED
            and now < shift.scheduled_end
        )
        clock_in_opens_at = shift.scheduled_start - timedelta(minutes=30)
        can_clock_in = show_clock_in and now >= clock_in_opens_at
        cards.append(
            {
                "shift": shift,
                "session": session,
                "effective_clock_out_at": effective["clock_out_at"] if effective else None,
                "timesheet": getattr(session, "timesheet", None) if session else None,
                "state": state,
                "show_clock_in": show_clock_in,
                "can_clock_in": can_clock_in,
                "clock_in_opens_at": clock_in_opens_at,
                "clock_in_closes_at": shift.scheduled_end,
                "last_activity": last_activity(session),
                "breaks": breaks,
                "worked_seconds": worked_seconds,
                "break_seconds": break_seconds,
                "work_timer_running": bool(session and not effective["clock_out_at"] and session.status == AttendanceSession.Status.WORKING),
                "break_timer_running": bool(active_break),
                "active_break": active_break,
                "worked_duration_label": _duration_label(worked_seconds),
                "break_duration_label": _duration_label(break_seconds),
                "scheduled_duration_label": _employee_duration_label(shift.scheduled_minutes),
            }
        )
    has_open_session = any(card["session"] and not card["effective_clock_out_at"] for card in cards)
    if has_open_session:
        for card in cards:
            if card["session"] is None:
                card["show_clock_in"] = False
                card["can_clock_in"] = False
    today_card = next((card for card in cards if card["shift"].work_date == today), None)
    active_card = next((card for card in cards if card["session"] and not card["effective_clock_out_at"]), None)
    clockable_card = next((card for card in cards if card["can_clock_in"]), None)
    upcoming_card = next(
        (
            card for card in cards
            if card["shift"].work_date > today and card["shift"].status == Shift.Status.SCHEDULED
        ),
        None,
    )
    scheduled_today_card = (
        today_card
        if today_card and today_card["shift"].status == Shift.Status.SCHEDULED
        else None
    )
    focus_card = active_card or clockable_card or scheduled_today_card or upcoming_card
    show_cancelled_notice = bool(
        today_card
        and today_card["shift"].status == Shift.Status.CANCELLED
    )
    show_upcoming_summary = bool(
        upcoming_card
        and (focus_card is None or focus_card["shift"].pk != upcoming_card["shift"].pk)
    )
    weekly_minutes = Timesheet.objects.filter(
        organization=organization,
        employee=employee,
        shift__work_date__range=(week_start, week_start + timedelta(days=6)),
    ).aggregate(total=Sum("worked_minutes"))["total"] or 0
    recent_timesheets = list(
        Timesheet.objects.filter(organization=organization, employee=employee)
        .select_related("shift")[:5]
    )
    for timesheet in recent_timesheets:
        timesheet.worked_duration_label = _employee_duration_label(timesheet.worked_minutes)
    return render(
        request,
        "attendance/my_attendance.html",
        {
            "cards": cards,
            "today_card": today_card,
            "focus_card": focus_card,
            "upcoming_card": upcoming_card,
            "show_cancelled_notice": show_cancelled_notice,
            "show_upcoming_summary": show_upcoming_summary,
            "weekly_minutes": weekly_minutes,
            "weekly_hours_label": _employee_duration_label(weekly_minutes),
            "week_start": week_start,
            "week_end": week_start + timedelta(days=6),
            "recent_timesheets": recent_timesheets,
            "organization": organization,
            "employer_contact_email": organization.owner.email,
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
