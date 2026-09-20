from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.permissions import employee_required, employer_required, organization_for_user
from attendance.services import attendance_state
from .forms import ShiftForm
from .forms_filter import ShiftFilterForm
from .models import Shift
from .services import cancel_shift, create_shift, update_shift
from timesheets.models import Timesheet


def _scoped_shifts(user):
    organization = organization_for_user(user)
    return Shift.objects.none() if organization is None else Shift.objects.filter(organization=organization).select_related("employee")


@employer_required
@require_GET
def shift_list(request):
    organization = organization_for_user(request.user)
    filter_form = ShiftFilterForm(request.GET or None, organization=organization)
    shifts = _scoped_shifts(request.user)
    if filter_form.is_valid():
        data = filter_form.cleaned_data
        if data.get("start_date"):
            shifts = shifts.filter(work_date__gte=data["start_date"])
        if data.get("end_date"):
            shifts = shifts.filter(work_date__lte=data["end_date"])
        if data.get("employee"):
            shifts = shifts.filter(employee=data["employee"])
        if data.get("status"):
            shifts = shifts.filter(status=data["status"])
    page = Paginator(shifts, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "schedules/list.html",
        {"page": page, "filter_form": filter_form, "organization": organization},
    )


@employer_required
@require_http_methods(["GET", "POST"])
def shift_create(request):
    organization = organization_for_user(request.user)
    form = ShiftForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            shift = create_shift(
                organization=organization,
                employee=form.cleaned_data["employee"],
                work_date=form.cleaned_data["work_date"],
                scheduled_start=form.cleaned_data["scheduled_start"],
                scheduled_end=form.cleaned_data["scheduled_end"],
                scheduled_break_minutes=form.cleaned_data["scheduled_break_minutes"],
                actor=request.user,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"Shift scheduled for {shift.employee.full_name}.")
            return redirect("schedules:detail", pk=shift.pk)
    return render(
        request,
        "schedules/form.html",
        {
            "form": form,
            "is_create": True,
            "organization": organization,
            "has_employees": form.fields["employee"].queryset.exists(),
        },
    )


@employer_required
@require_GET
def shift_detail(request, pk):
    organization = organization_for_user(request.user)
    shift = get_object_or_404(_scoped_shifts(request.user), pk=pk)
    return render(request, "schedules/detail.html", {"shift": shift, "organization": organization})


@employer_required
@require_http_methods(["GET", "POST"])
def shift_edit(request, pk):
    organization = organization_for_user(request.user)
    shift = get_object_or_404(_scoped_shifts(request.user), pk=pk)
    if shift.status != Shift.Status.SCHEDULED:
        messages.error(request, "Cancelled shifts cannot be edited.")
        return redirect("schedules:detail", pk=shift.pk)
    form = ShiftForm(request.POST or None, organization=organization, instance=shift)
    if request.method == "POST" and form.is_valid():
        try:
            shift = update_shift(
                shift,
                organization=organization,
                employee=form.cleaned_data["employee"],
                work_date=form.cleaned_data["work_date"],
                scheduled_start=form.cleaned_data["scheduled_start"],
                scheduled_end=form.cleaned_data["scheduled_end"],
                scheduled_break_minutes=form.cleaned_data["scheduled_break_minutes"],
                actor=request.user,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Shift updated.")
            return redirect("schedules:detail", pk=shift.pk)
    return render(
        request,
        "schedules/form.html",
        {
            "form": form,
            "is_create": False,
            "shift": shift,
            "organization": organization,
            "has_employees": form.fields["employee"].queryset.exists(),
        },
    )


@employer_required
@require_POST
def shift_cancel(request, pk):
    organization = organization_for_user(request.user)
    shift = get_object_or_404(_scoped_shifts(request.user), pk=pk)
    try:
        cancel_shift(shift, organization=organization, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Shift cancelled.")
    return redirect("schedules:detail", pk=shift.pk)


@employee_required
@require_GET
def my_schedule(request):
    employee = request.user.employee_profile
    organization = employee.organization
    now = timezone.now()
    local_today = timezone.localdate(now, timezone=ZoneInfo(organization.timezone))
    week_start = local_today - timedelta(days=local_today.weekday())
    shifts = (
        Shift.objects.filter(organization=organization, employee=employee)
        .filter(
            Q(work_date__range=(local_today, local_today + timedelta(days=14)))
            | Q(attendance_session__isnull=False, attendance_session__clock_out_at__isnull=True)
        )
        .select_related("organization", "employee", "attendance_session")
        .order_by("work_date", "scheduled_start")
    )
    cards = [
        {
            "shift": shift,
            "session": getattr(shift, "attendance_session", None),
            "state": attendance_state(shift, at=now),
        }
        for shift in shifts
    ]
    weekly_minutes = Timesheet.objects.filter(
        organization=organization,
        employee=employee,
        shift__work_date__range=(week_start, week_start + timedelta(days=6)),
    ).aggregate(total=Sum("worked_minutes"))["total"] or 0
    weekly_hours, weekly_remainder = divmod(weekly_minutes, 60)
    return render(
        request,
        "schedules/my_schedule.html",
        {
            "cards": cards,
            "organization": organization,
            "local_today": local_today,
            "week_start": week_start,
            "weekly_minutes": weekly_minutes,
            "weekly_hours_label": f"{weekly_hours} hr {weekly_remainder:02d} min" if weekly_hours else f"{weekly_remainder} min",
        },
    )
