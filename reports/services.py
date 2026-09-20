import csv
from zoneinfo import ZoneInfo

from django.http import HttpResponse
from django.db.models import Prefetch

from timesheets.models import Timesheet, TimesheetApproval


CSV_HEADERS = [
    "organization name",
    "employee code",
    "employee name",
    "local shift date",
    "scheduled start",
    "scheduled end",
    "clock-in",
    "clock-out",
    "break minutes",
    "scheduled minutes",
    "worked minutes",
    "payable minutes",
    "late minutes",
    "undertime minutes",
    "attendance status",
    "timesheet status",
    "reviewed by",
    "reviewed at",
]


def timesheet_report_queryset(organization, filters):
    timesheets = Timesheet.objects.filter(
        organization=organization,
        shift__work_date__range=(filters["start_date"], filters["end_date"]),
    ).select_related(
        "organization", "employee", "shift", "attendance_session"
    ).prefetch_related(
        Prefetch("approvals", queryset=TimesheetApproval.objects.select_related("reviewer"))
    )
    if filters.get("employee"):
        timesheets = timesheets.filter(employee=filters["employee"])
    if filters.get("status"):
        timesheets = timesheets.filter(status=filters["status"])
    return timesheets.order_by("shift__work_date", "employee__last_name", "employee__first_name")


def _csv_safe_text(value):
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _local_iso(value, org_timezone):
    if value is None:
        return ""
    return value.astimezone(org_timezone).isoformat()


def export_timesheets_csv(*, organization, filters):
    org_timezone = ZoneInfo(organization.timezone)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="shiftly-timesheets-{filters["start_date"]}-{filters["end_date"]}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response, lineterminator="\r\n")
    writer.writerow(CSV_HEADERS)
    for timesheet in timesheet_report_queryset(organization, filters):
        approval = next(iter(timesheet.approvals.all()), None)
        reviewer = ""
        reviewed_at = ""
        if approval:
            reviewer = approval.reviewer.get_full_name() or approval.reviewer.email
            reviewed_at = _local_iso(approval.reviewed_at, org_timezone)
        session = timesheet.attendance_session
        writer.writerow(
            [
                _csv_safe_text(organization.name),
                _csv_safe_text(timesheet.employee.employee_code),
                _csv_safe_text(timesheet.employee.full_name),
                timesheet.shift.work_date.isoformat(),
                _local_iso(timesheet.shift.scheduled_start, org_timezone),
                _local_iso(timesheet.shift.scheduled_end, org_timezone),
                _local_iso(session.clock_in_at, org_timezone),
                _local_iso(session.clock_out_at, org_timezone),
                timesheet.break_minutes,
                timesheet.scheduled_minutes,
                timesheet.worked_minutes,
                timesheet.payable_minutes,
                timesheet.late_minutes,
                timesheet.undertime_minutes,
                "Completed",
                _csv_safe_text(timesheet.get_status_display()),
                _csv_safe_text(reviewer),
                reviewed_at,
            ]
        )
    return response
