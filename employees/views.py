from smtplib import SMTPException

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.models import AuditEvent
from audit.services import record_event
from accounts.permissions import employer_required, organization_for_user
from .forms import EmployeeForm
from .models import Employee, EmployeeInvitation
from .services import issue_employee_invitation


def _employee_queryset(user):
    organization = organization_for_user(user)
    if organization is None:
        return Employee.objects.none()
    return Employee.objects.filter(organization=organization).select_related("user")


@employer_required
def employee_list(request):
    organization = organization_for_user(request.user)
    employees = _employee_queryset(request.user)
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
    page = Paginator(employees, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "employees/list.html",
        {
            "page": page,
            "query": query,
            "status_filter": status,
            "statuses": Employee.Status.choices,
            "total_count": employees.count(),
            "organization": organization,
        },
    )


@employer_required
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
def employee_detail(request, pk):
    employee = get_object_or_404(_employee_queryset(request.user), pk=pk)
    invitation = employee.invitations.order_by("-created_at").first()
    return render(
        request,
        "employees/detail.html",
        {"employee": employee, "latest_invitation": invitation, "organization": employee.organization},
    )


@employer_required
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
            _employee_queryset(request.user).select_for_update(), pk=pk
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
