from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from accounts.permissions import employer_required, organization_for_user
from attendance.models import AttendanceSession, BreakSession
from attendance.services import attendance_state
from audit.models import AuditEvent
from employees.models import Employee
from schedules.models import Shift
from timesheets.models import Timesheet
from .forms import DailyAttendanceFilterForm, TimesheetReportFilterForm, WeekReportFilterForm
from .services import export_timesheets_csv, timesheet_report_queryset


REPORTS = {"attendance", "hours", "timesheets", "activity"}


def _filter_form_data(request, keys, *, form_class, initial, organization=None):
    bound = any(key in request.GET for key in keys)
    form_kwargs = {"initial": initial}
    if organization is not None:
        form_kwargs["organization"] = organization
    form = form_class(request.GET if bound else None, **form_kwargs)
    if not bound:
        return initial, form
    if form.is_valid():
        return form.cleaned_data, form
    return initial, form


def _duration_label(minutes):
    hours, remaining_minutes = divmod(minutes or 0, 60)
    return f"{hours}h {remaining_minutes:02d}m"


def _activity_label(session, org_timezone):
    if session is None:
        return ""
    if session.clock_out_at:
        event, moment = "Clocked out", session.clock_out_at
    else:
        breaks = list(session.breaks.all())
        open_break = next((item for item in breaks if item.ended_at is None), None)
        if open_break:
            event, moment = "Break started", open_break.started_at
        else:
            completed_breaks = [item for item in breaks if item.ended_at is not None]
            latest_break = max(completed_breaks, key=lambda item: item.ended_at) if completed_breaks else None
            if latest_break and latest_break.ended_at > session.clock_in_at:
                event, moment = "Break ended", latest_break.ended_at
            else:
                event, moment = "Clocked in", session.clock_in_at
    local_moment = timezone.localtime(moment, org_timezone)
    time_label = local_moment.strftime("%I:%M %p").lstrip("0")
    return f"{event} {time_label}"


def _page_context(request, page):
    query = request.GET.copy()
    query.pop("page", None)
    return {
        "page_querystring": query.urlencode(),
        "pagination_items": page.paginator.get_elided_page_range(page.number),
        "showing_start": page.start_index() if page.paginator.count else 0,
        "showing_end": page.end_index() if page.paginator.count else 0,
    }


@require_GET
@employer_required
def report_home(request):
    organization = organization_for_user(request.user)
    report = request.GET.get("report", "attendance")
    if report not in REPORTS:
        report = "attendance"

    context = {
        "organization": organization,
        "active_report": report,
        "hide_topbar_context": True,
        "timezone_label": organization.timezone,
    }
    org_timezone = ZoneInfo(organization.timezone)
    local_today = timezone.localdate(timezone=org_timezone)

    if report == "attendance":
        daily_filters, daily_form = _filter_form_data(
            request,
            ("daily_date", "daily_employee", "daily_status"),
            form_class=DailyAttendanceFilterForm,
            organization=organization,
            initial={"daily_date": local_today, "daily_employee": None, "daily_status": ""},
        )
        daily_date = daily_filters["daily_date"]
        daily_status = daily_filters.get("daily_status", "")
        shifts = (
            Shift.objects.filter(organization=organization, work_date=daily_date)
            .select_related("employee", "attendance_session")
            .prefetch_related(
                Prefetch("attendance_session__breaks", queryset=BreakSession.objects.order_by("started_at"))
            )
            .order_by("scheduled_start", "employee__last_name", "employee__first_name")
        )
        if daily_filters.get("daily_employee"):
            shifts = shifts.filter(employee=daily_filters["daily_employee"])

        all_daily_rows = []
        now = timezone.now()
        for shift in shifts:
            session = getattr(shift, "attendance_session", None)
            state = attendance_state(shift, at=now)
            late_clock_in = bool(session and session.clock_in_at > shift.scheduled_start)
            display_state = state
            if state["code"] == AttendanceSession.Status.WORKING and late_clock_in:
                display_state = {**state, "code": "LATE", "label": "Late"}

            if late_clock_in:
                late_minutes = int((session.clock_in_at - shift.scheduled_start).total_seconds() // 60)
                exception = f"{late_minutes} min late"
            elif state["missing_clock_out"]:
                exception = "Missing clock-out"
            else:
                exception = "—"

            all_daily_rows.append(
                {
                    "shift": shift,
                    "session": session,
                    "state": display_state,
                    "filter_state": state["code"],
                    "last_activity_label": _activity_label(session, org_timezone),
                    "late_clock_in": late_clock_in,
                    "exception": exception,
                    "overnight": shift.scheduled_start.astimezone(org_timezone).date()
                    != shift.scheduled_end.astimezone(org_timezone).date(),
                }
            )

        if daily_status == "LATE":
            daily_rows = [
                row for row in all_daily_rows if row["filter_state"] == "LATE" or row["late_clock_in"]
            ]
        elif daily_status == "WORKING":
            daily_rows = [
                row for row in all_daily_rows if row["filter_state"] in ("WORKING", "ON_BREAK")
            ]
        elif daily_status:
            daily_rows = [row for row in all_daily_rows if row["filter_state"] == daily_status]
        else:
            daily_rows = all_daily_rows

        daily_page = Paginator(daily_rows, 30).get_page(request.GET.get("page"))
        present_count = sum(1 for row in all_daily_rows if row["session"] is not None)
        late_count = sum(
            1 for row in all_daily_rows if row["filter_state"] == "LATE" or row["late_clock_in"]
        )
        absent_count = sum(1 for row in all_daily_rows if row["filter_state"] == "ABSENT")
        context.update(
            {
                "daily_form": daily_form,
                "daily_date": daily_date,
                "daily_page": daily_page,
                "attendance_summary": {
                    "assigned_count": len(all_daily_rows),
                    "present_count": present_count,
                    "late_count": late_count,
                    "absent_count": absent_count,
                },
                **_page_context(request, daily_page),
            }
        )

    elif report == "hours":
        week_filters, week_form = _filter_form_data(
            request,
            ("week_of",),
            form_class=WeekReportFilterForm,
            initial={"week_of": local_today},
        )
        selected_week_of = week_filters["week_of"]
        selected_week_start = selected_week_of - timedelta(days=selected_week_of.weekday())
        selected_week_end = selected_week_start + timedelta(days=6)
        weekly_rows = (
            Timesheet.objects.filter(
                organization=organization,
                shift__work_date__range=(selected_week_start, selected_week_end),
            )
            .order_by()
            .values("employee_id")
            .annotate(worked_minutes=Sum("worked_minutes"), completed_shifts=Count("pk"))
        )
        weekly_by_employee = {row["employee_id"]: row for row in weekly_rows}
        weekly_employees = []
        for employee in Employee.objects.filter(organization=organization).order_by(
            "last_name", "first_name"
        ):
            row = weekly_by_employee.get(employee.pk, {})
            minutes = row.get("worked_minutes") or 0
            weekly_employees.append(
                {
                    "employee": employee,
                    "worked_minutes": minutes,
                    "worked_label": _duration_label(minutes),
                    "completed_shifts": row.get("completed_shifts", 0),
                }
            )
        weekly_employees.sort(
            key=lambda row: (-row["worked_minutes"], row["employee"].last_name, row["employee"].first_name)
        )
        total_worked_minutes = sum(row["worked_minutes"] for row in weekly_employees)
        total_completed_shifts = sum(row["completed_shifts"] for row in weekly_employees)
        context.update(
            {
                "week_form": week_form,
                "selected_week_start": selected_week_start,
                "selected_week_end": selected_week_end,
                "weekly_employees": weekly_employees,
                "weekly_summary": {
                    "worked_minutes": total_worked_minutes,
                    "worked_label": _duration_label(total_worked_minutes),
                    "completed_shifts": total_completed_shifts,
                },
            }
        )

    elif report == "timesheets":
        week_start = local_today - timedelta(days=local_today.weekday())
        timesheet_initial = {
            "start_date": week_start,
            "end_date": week_start + timedelta(days=6),
            "employee": None,
            "status": "",
        }
        report_filters, timesheet_form = _filter_form_data(
            request,
            ("start_date", "end_date", "employee", "status"),
            form_class=TimesheetReportFilterForm,
            organization=organization,
            initial=timesheet_initial,
        )
        timesheets = timesheet_report_queryset(organization, report_filters)
        timesheet_page = Paginator(timesheets, 30).get_page(request.GET.get("page"))
        summary_filters = {**report_filters, "status": ""}
        summary_values = timesheet_report_queryset(organization, summary_filters).order_by().values("status").annotate(
            count=Count("pk"), worked_minutes=Sum("worked_minutes")
        )
        status_by_code = {row["status"]: row for row in summary_values}
        timesheet_status_summary = [
            {
                "code": status,
                "label": label,
                "count": status_by_code.get(status, {}).get("count", 0),
                "worked_minutes": status_by_code.get(status, {}).get("worked_minutes") or 0,
                "worked_label": _duration_label(status_by_code.get(status, {}).get("worked_minutes")),
            }
            for status, label in Timesheet.Status.choices
        ]
        timesheet_rows = []
        for timesheet in timesheet_page.object_list:
            variance = timesheet.worked_minutes - timesheet.scheduled_minutes
            variance_sign = "+" if variance > 0 else "" if variance == 0 else "−"
            timesheet_rows.append(
                {
                    "timesheet": timesheet,
                    "scheduled_label": _duration_label(timesheet.scheduled_minutes),
                    "worked_label": _duration_label(timesheet.worked_minutes),
                    "variance_label": f"{variance_sign}{_duration_label(abs(variance))}",
                    "variance_tone": "positive" if variance > 0 else "negative" if variance < 0 else "neutral",
                }
            )
        context.update(
            {
                "timesheet_form": timesheet_form,
                "timesheet_page": timesheet_page,
                "timesheet_rows": timesheet_rows,
                "timesheet_status_summary": timesheet_status_summary,
                **_page_context(request, timesheet_page),
            }
        )

    else:
        context["recent_activity"] = (
            AuditEvent.objects.filter(organization=organization).select_related("actor")[:25]
        )

    return render(request, "reports/index.html", context)


@require_GET
@employer_required
def timesheet_csv(request):
    organization = organization_for_user(request.user)
    org_today = timezone.localdate(timezone=ZoneInfo(organization.timezone))
    week_start = org_today - timedelta(days=org_today.weekday())
    initial = {
        "start_date": week_start,
        "end_date": week_start + timedelta(days=6),
        "employee": None,
        "status": "",
    }
    keys = ("start_date", "end_date", "employee", "status")
    bound = any(key in request.GET for key in keys)
    form = TimesheetReportFilterForm(
        request.GET if bound else None,
        organization=organization,
        initial=initial,
    )
    if bound and not form.is_valid():
        return HttpResponseBadRequest("Invalid report filters. Return to Reports and correct the date range or employee.")
    filters = form.cleaned_data if bound else initial
    return export_timesheets_csv(organization=organization, filters=filters)
