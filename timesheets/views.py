from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.permissions import employee_required, employer_required, organization_for_user
from .forms import RejectTimesheetForm, TimesheetFilterForm
from .models import Timesheet, TimesheetApproval
from .services import review_timesheet


def _duration_label(minutes):
    hours, remainder = divmod(max(0, minutes or 0), 60)
    return f"{hours}h {remainder:02d}m"


def _variance_label(minutes):
    sign = "+" if minutes > 0 else "-" if minutes < 0 else ""
    hours, remainder = divmod(abs(minutes), 60)
    duration = f"{hours}h {remainder:02d}m" if hours else f"{remainder}m"
    tone = "positive" if minutes > 0 else "negative" if minutes < 0 else "neutral"
    return f"{sign}{duration}", tone


def _with_details(queryset):
    return queryset.select_related(
        "employee", "organization", "shift", "attendance_session", "attendance_session__shift"
    ).prefetch_related(
        "attendance_session__breaks",
        Prefetch("approvals", queryset=TimesheetApproval.objects.select_related("reviewer")),
    )


@employer_required
@require_GET
def timesheet_list(request):
    organization = organization_for_user(request.user)
    filter_form = TimesheetFilterForm(request.GET or None, organization=organization)
    base_queryset = Timesheet.objects.filter(organization=organization).select_related("employee", "shift")
    filters_valid = not filter_form.is_bound or filter_form.is_valid()
    data = filter_form.cleaned_data if filter_form.is_bound and filters_valid else {}

    if data.get("start_date"):
        base_queryset = base_queryset.filter(shift__work_date__gte=data["start_date"])
    if data.get("end_date"):
        base_queryset = base_queryset.filter(shift__work_date__lte=data["end_date"])
    if data.get("employee"):
        base_queryset = base_queryset.filter(employee=data["employee"])

    summary = base_queryset.aggregate(
        total_count=Count("pk"),
        pending_count=Count("pk", filter=Q(status=Timesheet.Status.PENDING)),
        approved_count=Count("pk", filter=Q(status=Timesheet.Status.APPROVED)),
        rejected_count=Count("pk", filter=Q(status=Timesheet.Status.REJECTED)),
        worked_minutes=Sum("worked_minutes"),
    )

    timesheets = base_queryset
    if data.get("status"):
        timesheets = timesheets.filter(status=data["status"])
    page = Paginator(timesheets, 30).get_page(request.GET.get("page"))

    timesheet_rows = []
    for timesheet in page.object_list:
        variance_label, variance_tone = _variance_label(timesheet.worked_minutes - timesheet.scheduled_minutes)
        timesheet_rows.append(
            {
                "timesheet": timesheet,
                "scheduled_label": _duration_label(timesheet.scheduled_minutes),
                "worked_label": _duration_label(timesheet.worked_minutes),
                "variance_label": variance_label,
                "variance_tone": variance_tone,
            }
        )

    base_filter_params = {}
    if data.get("start_date"):
        base_filter_params["start_date"] = data["start_date"].isoformat()
    if data.get("end_date"):
        base_filter_params["end_date"] = data["end_date"].isoformat()
    if data.get("employee"):
        base_filter_params["employee"] = data["employee"].pk

    quick_filter_urls = {}
    for status in (Timesheet.Status.PENDING, Timesheet.Status.APPROVED, Timesheet.Status.REJECTED):
        params = {**base_filter_params, "status": status}
        quick_filter_urls[status] = f"{reverse('timesheets:list')}?{urlencode(params)}"

    export_url = ""
    if filters_valid:
        all_dates = Timesheet.objects.filter(organization=organization).aggregate(
            first_date=Min("shift__work_date"), last_date=Max("shift__work_date")
        )
        org_today = timezone.localdate(timezone=ZoneInfo(organization.timezone))
        export_start = data.get("start_date")
        export_end = data.get("end_date")
        if export_start is None and export_end is None:
            export_start = all_dates["first_date"] or org_today
            export_end = all_dates["last_date"] or org_today
        elif export_start is None:
            export_start = all_dates["first_date"] or export_end
            if export_start > export_end:
                export_start = export_end
        elif export_end is None:
            export_end = all_dates["last_date"] or export_start
            if export_end < export_start:
                export_end = export_start
        export_params = {
            "start_date": export_start.isoformat(),
            "end_date": export_end.isoformat(),
            "employee": data["employee"].pk if data.get("employee") else "",
            "status": data.get("status") or "",
        }
        export_url = f"{reverse('reports:timesheet_csv')}?{urlencode(export_params)}"

    page_query = request.GET.copy()
    page_query.pop("page", None)
    page_querystring = page_query.urlencode()
    has_filters = filters_valid and any(
        data.get(key) for key in ("start_date", "end_date", "employee", "status")
    )
    showing_start = page.start_index() if page.paginator.count else 0
    showing_end = page.end_index() if page.paginator.count else 0

    return render(
        request,
        "timesheets/list.html",
        {
            "page": page,
            "filter_form": filter_form,
            "can_review": True,
            "organization": organization,
            "layout_template": "layouts/employer.html",
            "summary": {
                "total_count": summary["total_count"] or 0,
                "pending_count": summary["pending_count"] or 0,
                "approved_count": summary["approved_count"] or 0,
                "rejected_count": summary["rejected_count"] or 0,
                "worked_minutes": summary["worked_minutes"] or 0,
                "worked_label": _duration_label(summary["worked_minutes"]),
            },
            "timesheet_rows": timesheet_rows,
            "quick_filter_urls": quick_filter_urls,
            "selected_status": data.get("status", ""),
            "export_url": export_url,
            "has_filters": has_filters,
            "showing_start": showing_start,
            "showing_end": showing_end,
            "page_querystring": page_querystring,
            "pagination_items": page.paginator.get_elided_page_range(page.number),
        },
    )


@employer_required
@require_GET
def timesheet_detail(request, pk):
    organization = organization_for_user(request.user)
    timesheet = get_object_or_404(_with_details(Timesheet.objects.filter(organization=organization)), pk=pk)
    return render(
        request,
        "timesheets/detail.html",
        {
            "timesheet": timesheet,
            "can_review": True,
            "reject_form": RejectTimesheetForm(),
            "organization": organization,
            "layout_template": "layouts/employer.html",
        },
    )


@employee_required
@require_GET
def my_timesheets(request):
    employee = request.user.employee_profile
    page = Paginator(
        _with_details(Timesheet.objects.filter(employee=employee, organization=employee.organization)),
        30,
    ).get_page(request.GET.get("page"))
    return render(
        request,
        "timesheets/list.html",
        {"page": page, "can_review": False, "employee_view": True, "organization": employee.organization, "layout_template": "layouts/employee.html"},
    )


@employee_required
@require_GET
def my_timesheet_detail(request, pk):
    employee = request.user.employee_profile
    timesheet = get_object_or_404(
        _with_details(Timesheet.objects.filter(employee=employee, organization=employee.organization)),
        pk=pk,
    )
    return render(
        request,
        "timesheets/detail.html",
        {
            "timesheet": timesheet,
            "can_review": False,
            "organization": employee.organization,
            "layout_template": "layouts/employee.html",
        },
    )


@employer_required
@require_POST
def approve_timesheet(request, pk):
    organization = organization_for_user(request.user)
    timesheet = get_object_or_404(Timesheet.objects.filter(organization=organization), pk=pk)
    try:
        review_timesheet(
            timesheet=timesheet,
            reviewer=request.user,
            action=TimesheetApproval.Action.APPROVED,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Timesheet approved.")
    return redirect("timesheets:detail", pk=timesheet.pk)


@employer_required
@require_POST
def reject_timesheet(request, pk):
    organization = organization_for_user(request.user)
    timesheet = get_object_or_404(Timesheet.objects.filter(organization=organization), pk=pk)
    form = RejectTimesheetForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Add a comment explaining why the timesheet is rejected.")
    else:
        try:
            review_timesheet(
                timesheet=timesheet,
                reviewer=request.user,
                action=TimesheetApproval.Action.REJECTED,
                comment=form.cleaned_data["comment"],
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Timesheet rejected. The decision is final in this MVP.")
    return redirect("timesheets:detail", pk=timesheet.pk)
