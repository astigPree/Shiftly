from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Case, CharField, Count, Q, Sum, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.permissions import employee_required, employer_required, organization_for_user
from attendance.services import attendance_state
from employees.models import Employee
from .forms import ShiftForm
from .forms_filter import ShiftFilterForm
from .models import Shift
from .services import cancel_shift, create_shift, update_shift
from timesheets.models import Timesheet


def _shift_duration_label(minutes):
    hours, remainder = divmod(max(0, minutes), 60)
    return f"{hours}h {remainder:02d}m" if hours else f"{remainder}m"


def _scoped_shifts(user):
    organization = organization_for_user(user)
    return Shift.objects.none() if organization is None else Shift.objects.filter(organization=organization).select_related("employee")


@employer_required
@require_GET
def shift_list(request):
    organization = organization_for_user(request.user)
    filter_form = ShiftFilterForm(request.GET or None, organization=organization)
    now = timezone.now()
    base_shifts = _scoped_shifts(request.user).select_related(
        "employee", "organization", "attendance_session"
    )
    summary = base_shifts.aggregate(
        total_count=Count("pk"),
        upcoming_count=Count(
            "pk",
            filter=Q(
                status=Shift.Status.SCHEDULED,
                scheduled_start__gt=now,
                attendance_session__isnull=True,
            ),
        ),
        completed_count=Count(
            "pk",
            filter=Q(
                status=Shift.Status.SCHEDULED,
                attendance_session__clock_out_at__isnull=False,
            ),
        ),
        cancelled_count=Count("pk", filter=Q(status=Shift.Status.CANCELLED)),
    )
    shifts = base_shifts
    has_filters = False
    if filter_form.is_valid():
        data = filter_form.cleaned_data
        if data.get("start_date"):
            shifts = shifts.filter(work_date__gte=data["start_date"])
            has_filters = True
        if data.get("end_date"):
            shifts = shifts.filter(work_date__lte=data["end_date"])
            has_filters = True
        if data.get("employee"):
            shifts = shifts.filter(employee=data["employee"])
            has_filters = True
        status_filter = data.get("status")
        if status_filter:
            has_filters = True
            if status_filter == "SCHEDULED":
                shifts = shifts.filter(
                    status=Shift.Status.SCHEDULED,
                    scheduled_start__gt=now,
                    attendance_session__isnull=True,
                )
            elif status_filter == "WORKING":
                shifts = shifts.filter(
                    status=Shift.Status.SCHEDULED,
                    attendance_session__status="WORKING",
                    attendance_session__clock_out_at__isnull=True,
                )
            elif status_filter == "ON_BREAK":
                shifts = shifts.filter(
                    status=Shift.Status.SCHEDULED,
                    attendance_session__status="ON_BREAK",
                    attendance_session__clock_out_at__isnull=True,
                )
            elif status_filter == "LATE":
                shifts = shifts.filter(
                    status=Shift.Status.SCHEDULED,
                    attendance_session__isnull=True,
                    scheduled_start__lte=now,
                    scheduled_end__gt=now,
                )
            elif status_filter == "ABSENT":
                shifts = shifts.filter(
                    status=Shift.Status.SCHEDULED,
                    attendance_session__isnull=True,
                    scheduled_end__lte=now,
                )
            elif status_filter == "COMPLETED":
                shifts = shifts.filter(
                    status=Shift.Status.SCHEDULED,
                    attendance_session__clock_out_at__isnull=False,
                )
            elif status_filter == "CANCELLED":
                shifts = shifts.filter(status=Shift.Status.CANCELLED)

    sort_fields = {
        "work_date": "work_date",
        "employee": "employee__last_name",
        "shift": "scheduled_start",
        "break": "scheduled_break_minutes",
        "status": "display_status",
    }
    sort_key = request.GET.get("sort", "work_date")
    if sort_key not in sort_fields:
        sort_key = "work_date"
    direction = request.GET.get("direction", "asc").lower()
    if direction not in {"asc", "desc"}:
        direction = "asc"

    shifts = shifts.annotate(
        display_status=Case(
            When(status=Shift.Status.CANCELLED, then=Value("Cancelled")),
            When(attendance_session__clock_out_at__isnull=False, then=Value("Completed")),
            When(attendance_session__status="ON_BREAK", then=Value("On break")),
            When(attendance_session__isnull=False, then=Value("Working")),
            When(
                scheduled_start__lte=now,
                scheduled_end__gt=now,
                then=Value("Late"),
            ),
            When(scheduled_end__lte=now, then=Value("Absent")),
            default=Value("Scheduled"),
            output_field=CharField(),
        )
    )
    order_field = sort_fields[sort_key]
    if direction == "desc":
        order_field = f"-{order_field}"
    shifts = shifts.order_by(order_field, "work_date", "pk")

    page = Paginator(shifts, 3).get_page(request.GET.get("page"))
    for shift in page.object_list:
        shift.attendance_state = attendance_state(shift, at=now)
        shift.can_manage = (
            shift.status == Shift.Status.SCHEDULED
            and getattr(shift, "attendance_session", None) is None
        )

    query_without_page = request.GET.copy()
    query_without_page.pop("page", None)
    querystring = query_without_page.urlencode()
    sort_links = {}
    for key in sort_fields:
        sort_query = query_without_page.copy()
        next_direction = (
            "desc" if key == sort_key and direction == "asc" else "asc"
        )
        sort_query["sort"] = key
        sort_query["direction"] = next_direction
        sort_links[key] = f"?{sort_query.urlencode()}"

    page_count = page.paginator.num_pages
    if page_count <= 7:
        pagination_items = list(range(1, page_count + 1))
    else:
        first_page = max(1, min(page.number - 1, page_count - 2))
        last_page = min(page_count, max(page.number + 1, 3))
        pagination_items = [1]
        if first_page > 2:
            pagination_items.append(None)
        pagination_items.extend(range(max(2, first_page), min(page_count, last_page + 1)))
        if last_page < page_count - 1:
            pagination_items.append(None)
        pagination_items.append(page_count)
    return render(
        request,
        "schedules/list.html",
        {
            "page": page,
            "filter_form": filter_form,
            "organization": organization,
            "summary": summary,
            "has_filters": has_filters,
            "sort_key": sort_key,
            "direction": direction,
            "sort_links": sort_links,
            "querystring": querystring,
            "pagination_items": pagination_items,
            "showing_start": page.start_index() if page.paginator.count else 0,
            "showing_end": page.end_index() if page.paginator.count else 0,
        },
    )


@employer_required
@require_http_methods(["GET", "POST"])
def shift_create(request):
    organization = organization_for_user(request.user)
    initial = {}
    employee_id = request.GET.get("employee")
    if employee_id and Employee.objects.filter(
        organization=organization,
        status=Employee.Status.ACTIVE,
        pk=employee_id,
    ).exists():
        initial["employee"] = employee_id
    form = ShiftForm(request.POST or None, organization=organization, initial=initial)
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
    shift = get_object_or_404(
        _scoped_shifts(request.user).select_related("attendance_session"), pk=pk
    )
    shift_session = getattr(shift, "attendance_session", None)
    shift_state = attendance_state(shift)
    return render(
        request,
        "schedules/detail.html",
        {
            "shift": shift,
            "organization": organization,
            "shift_state": shift_state,
            "can_manage_shift": shift.status == Shift.Status.SCHEDULED and shift_session is None,
            "shift_session": shift_session,
            "scheduled_duration_label": _shift_duration_label(shift.scheduled_minutes),
            "gross_duration_label": _shift_duration_label(shift.scheduled_gross_minutes),
            "is_long_shift": shift.scheduled_gross_minutes > 12 * 60,
        },
    )


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
