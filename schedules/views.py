from datetime import timedelta
import hashlib
import json
import uuid
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Case, CharField, Count, Q, Sum, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.permissions import employee_required, employer_required, organization_for_user
from attendance.models import AttendanceSession
from attendance.services import attendance_state
from employees.models import Employee
from .forms import ShiftForm
from .forms_filter import ShiftFilterForm
from .models import Shift
from .services import cancel_shift, create_shifts, update_shift
from timesheets.models import Timesheet


def _shift_duration_label(minutes):
    hours, remainder = divmod(max(0, minutes), 60)
    return f"{hours}h {remainder:02d}m" if hours else f"{remainder}m"


def _break_allowance_label(minutes):
    hours, remainder = divmod(max(0, minutes), 60)
    if hours and remainder:
        return f"{hours}h {remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"


def _shift_batch_fingerprint(*, organization, actor, form):
    payload = {
        "organization": organization.pk,
        "actor": actor.pk,
        "employees": sorted(employee.pk for employee in form.cleaned_data["employees"]),
        "shift_intervals": [
            {
                "work_date": interval["work_date"].isoformat(),
                "scheduled_start": interval["scheduled_start"].isoformat(),
                "scheduled_end": interval["scheduled_end"].isoformat(),
            }
            for interval in form.cleaned_data["shift_intervals"]
        ],
        "break_minutes": form.cleaned_data["scheduled_break_minutes"],
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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
        initial["employees"] = [employee_id]
    form = ShiftForm(request.POST or None, organization=organization, initial=initial)
    review_batch = False
    review_token = request.POST.get("review_token", "") if request.method == "POST" else ""
    if len(review_token) != 32 or any(char not in "0123456789abcdef" for char in review_token):
        review_token = uuid.uuid4().hex

    if request.method == "POST" and form.is_valid():
        fingerprint = _shift_batch_fingerprint(
            organization=organization,
            actor=request.user,
            form=form,
        )
        session_key = "pending_schedule_shift_reviews"
        pending_reviews = request.session.get(session_key, {})
        has_matching_review = (
            request.POST.get("batch_step") == "create"
            and pending_reviews.get(review_token) == fingerprint
        )
        selected_employee_count = len(form.cleaned_data["employees"])
        selected_date_count = len(form.cleaned_data["shift_intervals"])
        planned_shift_count = selected_employee_count * selected_date_count
        create_single_shift = (
            planned_shift_count == 1
            and request.POST.get("batch_step") == "review"
        )
        if has_matching_review or create_single_shift:
            if has_matching_review:
                pending_reviews.pop(review_token, None)
                if pending_reviews:
                    request.session[session_key] = pending_reviews
                else:
                    request.session.pop(session_key, None)
            try:
                shifts = create_shifts(
                    organization=organization,
                    employees=form.cleaned_data["employees"],
                    shift_intervals=form.cleaned_data["shift_intervals"],
                    scheduled_break_minutes=form.cleaned_data["scheduled_break_minutes"],
                    actor=request.user,
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                if planned_shift_count == 1:
                    shift = shifts[0]
                    messages.success(
                        request,
                        f"Shift scheduled for {shift.employee.full_name}.",
                    )
                    return redirect("schedules:detail", pk=shift.pk)
                messages.success(
                    request,
                    f"Scheduled {len(shifts)} shifts for {selected_employee_count} "
                    f"employee{'s' if selected_employee_count != 1 else ''} across "
                    f"{selected_date_count} dates.",
                )
                return redirect("schedules:list")
        else:
            pending_reviews[review_token] = fingerprint
            while len(pending_reviews) > 5:
                pending_reviews.pop(next(iter(pending_reviews)))
            request.session[session_key] = pending_reviews
            review_batch = True

    has_employees = bool(form.employee_options)
    return render(
        request,
        "schedules/form.html",
        {
            "form": form,
            "is_create": True,
            "organization": organization,
            "has_employees": has_employees,
            "employee_count": len(form.employee_options),
            "selected_employee_count": len(form.selected_employee_ids),
            "selected_date_count": len(form.selected_work_dates),
            "planned_shift_count": (
                len(form.selected_employee_ids) * len(form.selected_work_dates)
            ),
            "review_batch": review_batch,
            "review_token": review_token,
            "max_bulk_shift_dates": form.max_bulk_shift_dates,
            "max_bulk_shift_assignments": form.max_bulk_shift_assignments,
            "shift_is_overnight": (
                review_batch
                and form.cleaned_data["end_time"] < form.cleaned_data["start_time"]
            ),
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
    has_open_session = AttendanceSession.objects.filter(
        organization=organization,
        employee=employee,
        clock_out_at__isnull=True,
    ).exists()
    shifts = (
        Shift.objects.filter(organization=organization, employee=employee)
        .filter(
            Q(work_date__range=(local_today, local_today + timedelta(days=14)))
            | Q(
                status=Shift.Status.SCHEDULED,
                scheduled_start__lte=now,
                scheduled_end__gt=now,
            )
            | Q(attendance_session__isnull=False, attendance_session__clock_out_at__isnull=True)
        )
        .select_related("organization", "employee", "attendance_session")
        .order_by("work_date", "scheduled_start")
    )
    cards = []
    for shift in shifts:
        session = getattr(shift, "attendance_session", None)
        state = attendance_state(shift, at=now)
        clock_in_opens_at = shift.scheduled_start - timedelta(minutes=30)
        show_clock_in = (
            session is None
            and shift.status == Shift.Status.SCHEDULED
            and now < shift.scheduled_end
        )
        blocked_by_open_session = show_clock_in and has_open_session
        can_clock_in = (
            show_clock_in
            and not has_open_session
            and now >= clock_in_opens_at
        )
        cards.append(
            {
                "shift": shift,
                "session": session,
                "state": state,
                "show_clock_in": show_clock_in,
                "can_clock_in": can_clock_in,
                "blocked_by_open_session": blocked_by_open_session,
                "needs_attention": bool(session and session.clock_out_at is None),
                "clock_in_opens_at": clock_in_opens_at,
                "clock_in_closes_at": shift.scheduled_end,
                "scheduled_duration_label": _shift_duration_label(shift.scheduled_minutes),
                "break_allowance_label": _break_allowance_label(shift.scheduled_break_minutes),
            }
        )

    today_cards = [card for card in cards if card["shift"].work_date == local_today]
    overnight_cards = [
        card for card in cards
        if card["shift"].work_date < local_today
        and card["shift"].status == Shift.Status.SCHEDULED
        and card["session"] is None
        and card["shift"].scheduled_start <= now < card["shift"].scheduled_end
    ]
    attention_cards = [
        card for card in cards
        if card["shift"].work_date != local_today and card["needs_attention"]
    ]
    upcoming_cards = [
        card for card in cards
        if card["shift"].work_date > local_today
        and card["shift"].status == Shift.Status.SCHEDULED
        and not card["needs_attention"]
    ]
    cancelled_cards = [
        card for card in cards
        if card["shift"].work_date > local_today
        and card["shift"].status == Shift.Status.CANCELLED
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
            "organization": organization,
            "now": now,
            "local_today": local_today,
            "week_start": week_start,
            "weekly_minutes": weekly_minutes,
            "weekly_hours_label": f"{weekly_hours}h {weekly_remainder:02d}m",
            "week_end": week_start + timedelta(days=6),
            "today_cards": today_cards,
            "overnight_cards": overnight_cards,
            "attention_cards": attention_cards,
            "upcoming_cards": upcoming_cards,
            "cancelled_cards": cancelled_cards,
        },
    )
