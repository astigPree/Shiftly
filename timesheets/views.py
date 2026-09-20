from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import employee_required, employer_required, organization_for_user
from .forms import RejectTimesheetForm, TimesheetFilterForm
from .models import Timesheet, TimesheetApproval
from .services import review_timesheet


def _with_details(queryset):
    return queryset.select_related(
        "employee", "organization", "shift", "attendance_session", "attendance_session__shift"
    ).prefetch_related(
        "attendance_session__breaks",
        Prefetch("approvals", queryset=TimesheetApproval.objects.select_related("reviewer")),
    )


@employer_required
def timesheet_list(request):
    organization = organization_for_user(request.user)
    filter_form = TimesheetFilterForm(request.GET or None, organization=organization)
    timesheets = Timesheet.objects.filter(organization=organization).select_related("employee", "shift")
    if filter_form.is_valid():
        data = filter_form.cleaned_data
        if data.get("start_date"):
            timesheets = timesheets.filter(shift__work_date__gte=data["start_date"])
        if data.get("end_date"):
            timesheets = timesheets.filter(shift__work_date__lte=data["end_date"])
        if data.get("employee"):
            timesheets = timesheets.filter(employee=data["employee"])
        if data.get("status"):
            timesheets = timesheets.filter(status=data["status"])
    page = Paginator(timesheets, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "timesheets/list.html",
        {"page": page, "filter_form": filter_form, "can_review": True},
    )


@employer_required
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
        },
    )


@employee_required
def my_timesheets(request):
    employee = request.user.employee_profile
    page = Paginator(
        _with_details(Timesheet.objects.filter(employee=employee, organization=employee.organization)),
        30,
    ).get_page(request.GET.get("page"))
    return render(request, "timesheets/list.html", {"page": page, "can_review": False, "employee_view": True})


@employee_required
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
