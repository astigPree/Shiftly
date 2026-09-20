from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from accounts.permissions import employer_required, organization_for_user
from attendance.models import BreakSession
from attendance.services import attendance_state, last_activity
from audit.models import AuditEvent
from employees.models import Employee
from schedules.models import Shift
from timesheets.models import Timesheet
from .forms import DailyAttendanceFilterForm, TimesheetReportFilterForm, WeekReportFilterForm
from .services import export_timesheets_csv, timesheet_report_queryset


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


@require_GET
@employer_required
def report_home(request):
    organization = organization_for_user(request.user)
    org_timezone = ZoneInfo(organization.timezone)
    local_today = timezone.localdate(timezone=org_timezone)
    week_start = local_today - timedelta(days=local_today.weekday())
    week_end = week_start + timedelta(days=6)

    daily_filters, daily_form = _filter_form_data(
        request,
        ("daily_date", "daily_employee", "daily_status"),
        form_class=DailyAttendanceFilterForm,
        organization=organization,
        initial={"daily_date": local_today, "daily_employee": None, "daily_status": ""},
    )
    daily_date = daily_filters["daily_date"]
    daily_employee = daily_filters.get("daily_employee")
    daily_status = daily_filters.get("daily_status", "")
    shifts = (
        Shift.objects.filter(organization=organization, work_date=daily_date)
        .select_related("organization", "employee", "attendance_session")
        .prefetch_related(
            Prefetch("attendance_session__breaks", queryset=BreakSession.objects.order_by("started_at"))
        )
        .order_by("scheduled_start", "employee__last_name", "employee__first_name")
    )
    if daily_employee:
        shifts = shifts.filter(employee=daily_employee)
    daily_rows = []
    now = timezone.now()
    for shift in shifts:
        session = getattr(shift, "attendance_session", None)
        state = attendance_state(shift, at=now)
        late_clock_in = bool(session and session.clock_in_at > shift.scheduled_start)
        if daily_status == "LATE":
            if state["code"] != "LATE" and not late_clock_in:
                continue
        elif daily_status == "WORKING":
            if state["code"] not in ("WORKING", "ON_BREAK"):
                continue
        elif daily_status and daily_status != state["code"]:
            continue
        daily_rows.append(
            {
                "shift": shift,
                "session": session,
                "state": state,
                "last_activity": last_activity(session),
                "late_clock_in": late_clock_in,
            }
        )

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
    for employee in Employee.objects.filter(organization=organization).order_by("last_name", "first_name"):
        row = weekly_by_employee.get(employee.pk, {})
        minutes = row.get("worked_minutes") or 0
        hours, remaining_minutes = divmod(minutes, 60)
        weekly_employees.append(
            {
                "employee": employee,
                "worked_minutes": minutes,
                "worked_label": f"{hours} hr {remaining_minutes:02d} min" if hours else f"{remaining_minutes} min",
                "completed_shifts": row.get("completed_shifts", 0),
            }
        )

    timesheet_initial = {
        "start_date": week_start,
        "end_date": week_end,
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
    status_values = timesheets.order_by().values("status").annotate(
        count=Count("pk"), worked_minutes=Sum("worked_minutes")
    )
    status_by_code = {row["status"]: row for row in status_values}
    timesheet_status_summary = [
        {
            "code": status,
            "label": label,
            "count": status_by_code.get(status, {}).get("count", 0),
            "worked_minutes": status_by_code.get(status, {}).get("worked_minutes") or 0,
        }
        for status, label in Timesheet.Status.choices
    ]
    recent_activity = AuditEvent.objects.filter(organization=organization).select_related("actor")[:25]
    return render(
        request,
        "reports/index.html",
        {
            "organization": organization,
            "local_today": local_today,
            "daily_form": daily_form,
            "daily_rows": daily_rows,
            "daily_date": daily_date,
            "week_form": week_form,
            "selected_week_start": selected_week_start,
            "selected_week_end": selected_week_end,
            "weekly_employees": weekly_employees,
            "timesheet_form": timesheet_form,
            "timesheet_page": timesheet_page,
            "timesheet_status_summary": timesheet_status_summary,
            "recent_activity": recent_activity,
        },
    )


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
