from datetime import timedelta
from smtplib import SMTPException
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from audit.models import AuditEvent
from audit.services import record_event
from accounts.permissions import employer_required, organization_for_user
from attendance.services import attendance_state
from schedules.models import Shift
from timesheets.models import Timesheet
from .forms import EmployeeForm
from .models import Employee, EmployeeInvitation
from .services import issue_employee_invitation


def _employee_queryset(user):
    organization = organization_for_user(user)
    if organization is None:
        return Employee.objects.none()
    return Employee.objects.filter(organization=organization).select_related("user")


@employer_required
@require_GET
def employee_list(request):
    organization = organization_for_user(request.user)
    all_employees = _employee_queryset(request.user)
    summary = all_employees.aggregate(
        total_count=Count("id"),
        active_count=Count("id", filter=Q(status=Employee.Status.ACTIVE)),
        inactive_count=Count("id", filter=Q(status=Employee.Status.INACTIVE)),
    )
    employees = all_employees.prefetch_related(
        Prefetch(
            "invitations",
            queryset=EmployeeInvitation.objects.only(
                "id", "employee_id", "expires_at", "accepted_at", "revoked_at"
            ).order_by("-created_at")[:1],
            to_attr="latest_list_invitations",
        )
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        employees = employees.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(employee_code__icontains=query)
            | Q(email__icontains=query)
            | Q(job_title__icontains=query)
        )
    valid_statuses = {choice for choice, _label in Employee.Status.choices}
    if status in valid_statuses:
        employees = employees.filter(status=status)
    else:
        status = ""

    page_size_choices = (10, 20, 50)
    try:
        page_size = int(request.GET.get("per_page", 20))
    except (TypeError, ValueError):
        page_size = 20
    if page_size not in page_size_choices:
        page_size = 20

    page = Paginator(employees, page_size).get_page(request.GET.get("page"))
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

    now = timezone.now()
    for employee in page.object_list:
        invitation = employee.latest_list_invitations[0] if employee.latest_list_invitations else None
        if employee.user_id:
            if employee.user.is_active:
                employee.account_state_label = "Activated"
                employee.account_state_class = "activated"
            else:
                employee.account_state_label = "Access disabled"
                employee.account_state_class = "disabled"
        elif invitation is None:
            employee.account_state_label = "Not invited"
            employee.account_state_class = "not-invited"
        elif invitation.accepted_at:
            employee.account_state_label = "Invitation accepted"
            employee.account_state_class = "accepted"
        elif invitation.revoked_at:
            employee.account_state_label = "Invitation revoked"
            employee.account_state_class = "revoked"
        elif invitation.expires_at <= now:
            employee.account_state_label = "Invitation expired"
            employee.account_state_class = "expired"
        else:
            employee.account_state_label = "Invitation sent"
            employee.account_state_class = "sent"

    return render(
        request,
        "employees/list.html",
        {
            "page": page,
            "query": query,
            "status_filter": status,
            "statuses": Employee.Status.choices,
            **summary,
            "page_size": page_size,
            "page_size_choices": page_size_choices,
            "pagination_items": pagination_items,
            "organization": organization,
        },
    )


@employer_required
@require_http_methods(["GET", "POST"])
def employee_create(request):
    organization = organization_for_user(request.user)
    form = EmployeeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                employee = form.save(commit=False)
                employee.organization = organization
                employee.status = Employee.Status.ACTIVE
                employee.save()
                issue_employee_invitation(employee, request.user, request)
                record_event(
                    organization=organization,
                    actor=request.user,
                    action=AuditEvent.Action.EMPLOYEE_CREATED,
                    target_type="employee",
                    target_id=employee.pk,
                    summary=f"Created employee record {employee.employee_code}.",
                    metadata={"employee_code": employee.employee_code},
                )
        except ValidationError as error:
            form.add_error(None, error)
        except (SMTPException, OSError, IntegrityError):
            form.add_error(None, "The employee could not be created or the invitation could not be sent. Try again.")
        else:
            messages.success(request, f"Employee created. An activation link was sent to {employee.email}.")
            return redirect("employees:detail", pk=employee.pk)
    return render(request, "employees/form.html", {"form": form, "is_create": True, "organization": organization})


@employer_required
@require_GET
def employee_detail(request, pk):
    employee = get_object_or_404(_employee_queryset(request.user), pk=pk)
    context = _employee_profile_context(employee, "overview")
    now = timezone.now()
    local_today = timezone.localdate(now, timezone=ZoneInfo(employee.organization.timezone))
    week_start = local_today - timedelta(days=local_today.weekday())
    next_shift = (
        Shift.objects.filter(
            organization=employee.organization,
            employee=employee,
            status=Shift.Status.SCHEDULED,
            scheduled_end__gt=now,
        )
        .order_by("scheduled_start", "pk")
        .first()
    )
    weekly_minutes = Timesheet.objects.filter(
        organization=employee.organization,
        employee=employee,
        shift__work_date__range=(week_start, week_start + timedelta(days=6)),
    ).aggregate(total=Sum("worked_minutes"))["total"] or 0
    weekly_hours, weekly_remainder = divmod(weekly_minutes, 60)
    sheet_counts = Timesheet.objects.filter(
        organization=employee.organization, employee=employee
    ).aggregate(
        approved=Count("pk", filter=Q(status=Timesheet.Status.APPROVED)),
        pending=Count("pk", filter=Q(status=Timesheet.Status.PENDING)),
        needs_review=Count("pk", filter=Q(status=Timesheet.Status.NEEDS_REVIEW)),
    )
    context.update({
        "next_shift": next_shift,
        "weekly_hours_label": f"{weekly_hours}h {weekly_remainder:02d}m" if weekly_hours else f"{weekly_remainder}m",
        "timesheet_counts": sheet_counts,
        "active_tab": "overview",
    })
    return render(
        request,
        "employees/detail.html",
        context,
    )


def _employee_profile_context(employee, active_tab):
    now = timezone.now()
    local_today = timezone.localdate(now, timezone=ZoneInfo(employee.organization.timezone))
    invitation = employee.invitations.order_by("-created_at").first()
    if employee.user_id:
        account_state = "Activated" if employee.user.is_active else "Access disabled"
        sign_in_state = "Enabled" if employee.user.is_active else "Disabled"
        invitation_state = "Account setup completed" if employee.user.is_active else "Account access is disabled"
    elif invitation is None:
        account_state = "Not invited"
        sign_in_state = "Not available"
        invitation_state = "No activation invitation has been sent."
    elif invitation.accepted_at:
        account_state = "Invitation accepted"
        sign_in_state = "Account setup required"
        invitation_state = "Invitation accepted"
    elif invitation.revoked_at:
        account_state = "Invitation revoked"
        sign_in_state = "Not available"
        invitation_state = "This activation link was revoked."
    elif invitation.expires_at <= now:
        account_state = "Invitation expired"
        sign_in_state = "Not available"
        invitation_state = "This activation link has expired."
    else:
        account_state = "Invitation sent"
        sign_in_state = "Awaiting activation"
        invitation_state = "Activation link sent"
    return {
        "employee": employee,
        "organization": employee.organization,
        "latest_invitation": invitation,
        "account_state": account_state,
        "sign_in_state": sign_in_state,
        "invitation_state": invitation_state,
        "can_send_invitation": not employee.user_id and employee.status == Employee.Status.ACTIVE,
        "active_tab": active_tab,
        "local_today": local_today,
    }


@employer_required
@require_GET
def employee_schedules(request, pk):
    employee = get_object_or_404(_employee_queryset(request.user), pk=pk)
    shifts = employee.shifts.filter(organization=employee.organization).select_related("organization")
    page = Paginator(shifts, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "employees/profile_schedules.html",
        {**_employee_profile_context(employee, "schedules"), "page": page},
    )


@employer_required
@require_GET
def employee_attendance(request, pk):
    employee = get_object_or_404(_employee_queryset(request.user), pk=pk)
    shifts = (
        employee.shifts.filter(organization=employee.organization)
        .select_related("organization", "attendance_session")
        .order_by("-work_date", "-scheduled_start", "-pk")
    )
    page = Paginator(shifts, 20).get_page(request.GET.get("page"))
    now = timezone.now()
    for shift in page.object_list:
        shift.profile_attendance_state = attendance_state(shift, at=now)
        shift.profile_attendance_session = getattr(shift, "attendance_session", None)
    return render(
        request,
        "employees/profile_attendance.html",
        {**_employee_profile_context(employee, "attendance"), "page": page},
    )


@employer_required
@require_GET
def employee_timesheets(request, pk):
    employee = get_object_or_404(_employee_queryset(request.user), pk=pk)
    timesheets = (
        Timesheet.objects.filter(organization=employee.organization, employee=employee)
        .select_related("shift")
    )
    page = Paginator(timesheets, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "employees/profile_timesheets.html",
        {**_employee_profile_context(employee, "timesheets"), "page": page},
    )


@employer_required
@require_http_methods(["GET", "POST"])
def employee_edit(request, pk):
    organization = organization_for_user(request.user)
    employee = get_object_or_404(_employee_queryset(request.user), pk=pk)
    form = EmployeeForm(request.POST or None, instance=employee)
    if request.method == "POST" and form.is_valid():
        email_changed = form.cleaned_data["email"].casefold() != employee.email.casefold()
        previous_values = {
            field: getattr(employee, field)
            for field in ("employee_code", "first_name", "last_name", "email", "job_title")
        }
        try:
            with transaction.atomic():
                employee = form.save(commit=False)
                employee.organization = organization
                employee.save()

                if employee.user_id:
                    user = get_user_model().objects.select_for_update().get(pk=employee.user_id)
                    user.email = employee.email
                    user.first_name = employee.first_name
                    user.last_name = employee.last_name
                    user.is_active = employee.status == Employee.Status.ACTIVE
                    user.save(update_fields=["email", "first_name", "last_name", "is_active"])

                if email_changed:
                    EmployeeInvitation.objects.filter(
                        employee=employee,
                        accepted_at__isnull=True,
                        revoked_at__isnull=True,
                    ).update(revoked_at=timezone.now())
                    if not employee.user_id and employee.status == Employee.Status.ACTIVE:
                        issue_employee_invitation(employee, request.user, request)
                changed_fields = [
                    field for field, old_value in previous_values.items()
                    if old_value != getattr(employee, field)
                ]
                if changed_fields:
                    record_event(
                        organization=organization,
                        actor=request.user,
                        action=AuditEvent.Action.EMPLOYEE_UPDATED,
                        target_type="employee",
                        target_id=employee.pk,
                        summary=f"Updated employee record {employee.employee_code}.",
                        metadata={"changed_fields": changed_fields},
                    )
        except ValidationError as error:
            form.add_error(None, error)
        except (SMTPException, OSError, IntegrityError):
            form.add_error(None, "The employee could not be updated or the new invitation could not be sent. Try again.")
        else:
            messages.success(request, "Employee details updated.")
            return redirect("employees:detail", pk=employee.pk)
    return render(
        request,
        "employees/form.html",
        {"form": form, "is_create": False, "employee": employee, "organization": organization},
    )


@employer_required
@require_POST
def employee_toggle_status(request, pk):
    with transaction.atomic():
        employee = get_object_or_404(
            _employee_queryset(request.user).select_for_update(of=("self",)), pk=pk
        )
        if employee.status == Employee.Status.ACTIVE:
            employee.status = Employee.Status.INACTIVE
            audit_action = AuditEvent.Action.EMPLOYEE_DEACTIVATED
        else:
            employee.status = Employee.Status.ACTIVE
            audit_action = AuditEvent.Action.EMPLOYEE_ACTIVATED
        employee.save(update_fields=["status", "updated_at"])
        if employee.user_id:
            user = get_user_model().objects.select_for_update().get(pk=employee.user_id)
            user.is_active = employee.status == Employee.Status.ACTIVE
            user.save(update_fields=["is_active"])
        if employee.status == Employee.Status.INACTIVE:
            EmployeeInvitation.objects.filter(
                employee=employee,
                accepted_at__isnull=True,
                revoked_at__isnull=True,
            ).update(revoked_at=timezone.now())
        record_event(
            organization=employee.organization,
            actor=request.user,
            action=audit_action,
            target_type="employee",
            target_id=employee.pk,
            summary=f"{employee.get_status_display()} employee {employee.employee_code}.",
            metadata={"status": employee.status},
        )
    messages.success(request, f"{employee.full_name} is now {employee.get_status_display().lower()}.")
    return redirect("employees:detail", pk=employee.pk)


@employer_required
@require_POST
def employee_resend_invitation(request, pk):
    employee = get_object_or_404(_employee_queryset(request.user), pk=pk)
    try:
        issue_employee_invitation(employee, request.user, request)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    except (SMTPException, OSError):
        messages.error(request, "The activation email could not be sent. Try again.")
    else:
        messages.success(request, f"A new activation link was sent to {employee.email}.")
    return redirect("employees:detail", pk=employee.pk)
