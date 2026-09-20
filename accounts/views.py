from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.forms import EmployerSignupForm, EmployeeInvitationAcceptanceForm, OrganizationSettingsForm
from accounts.models import User
from employees.forms import EmployeeProfileForm
from employees.models import EmployeeInvitation
from employees.services import accept_employee_invitation, update_employee_profile
from organizations.models import Organization
from .permissions import employee_required, employer_required, organization_for_user
from .services import employer_dashboard_data, save_workspace_settings


def index(request):
    if request.user.is_authenticated:
        return redirect("accounts:home")
    return redirect("accounts:login")


@require_http_methods(["GET", "POST"])
def employer_signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:home")

    form = EmployerSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=form.cleaned_data["email"],
                    password=form.cleaned_data["password1"],
                    first_name=form.cleaned_data["first_name"].strip(),
                    last_name=form.cleaned_data["last_name"].strip(),
                    role=User.Role.EMPLOYER,
                )
                Organization.objects.create(
                    owner=user,
                    name=form.cleaned_data["organization_name"],
                    timezone=form.cleaned_data["timezone"],
                )
        except IntegrityError:
            form.add_error("email", "An account with this email address already exists.")
        else:
            login(request, user)
            messages.success(request, "Your Shiftly workspace is ready.")
            return redirect("accounts:home")

    return render(request, "accounts/signup.html", {"form": form})


@login_required
def home(request):
    organization = organization_for_user(request.user)
    if organization is None:
        raise PermissionDenied
    if request.user.role == User.Role.EMPLOYER:
        context = employer_dashboard_data(organization)
        return render(
            request,
            "accounts/dashboard.html",
            {"organization": organization, "greeting_name": request.user.first_name or request.user.email, **context},
        )
    return redirect("attendance:my_attendance")


@require_http_methods(["GET", "POST"])
@employer_required
def workspace_settings(request):
    organization = organization_for_user(request.user)
    timezone_locked = organization.shifts.exists()
    form = OrganizationSettingsForm(
        request.POST or None,
        organization=organization,
        user=request.user,
        timezone_locked=timezone_locked,
    )
    if request.method == "POST" and form.is_valid():
        try:
            organization = save_workspace_settings(
                organization=organization,
                user=request.user,
                organization_name=form.cleaned_data["organization_name"],
                timezone_name=form.cleaned_data["timezone"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
            )
        except ValidationError as error:
            for field, errors in error.error_dict.items():
                for field_error in errors:
                    form.add_error(field, field_error)
        else:
            messages.success(request, "Organization settings saved.")
            return redirect("accounts:settings")
    return render(
        request,
        "accounts/settings.html",
        {"form": form, "organization": organization, "timezone_locked": timezone_locked},
    )


@require_http_methods(["GET", "POST"])
@employee_required
def employee_profile(request):
    employee = request.user.employee_profile
    form = EmployeeProfileForm(
        request.POST or None,
        initial={"first_name": employee.first_name, "last_name": employee.last_name},
    )
    if request.method == "POST" and form.is_valid():
        try:
            employee = update_employee_profile(
                employee=employee,
                user=request.user,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Your profile has been updated.")
            return redirect("accounts:profile")
    return render(
        request,
        "accounts/profile.html",
        {"form": form, "organization": employee.organization, "employee": employee},
    )


def _open_invitation(token):
    from employees.services import invitation_digest

    invitation = (
        EmployeeInvitation.objects.select_related("employee", "employee__organization")
        .filter(
            token_digest=invitation_digest(token),
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if invitation is None:
        raise Http404("This invitation is invalid or has expired.")
    return invitation


@require_http_methods(["GET", "POST"])
def accept_employee_invitation(request, token):
    invitation = _open_invitation(token)
    employee = invitation.employee
    if employee.user_id or employee.status != employee.Status.ACTIVE:
        raise Http404("This invitation is no longer available.")

    if request.user.is_authenticated:
        return render(
            request,
            "employees/invitation_accept.html",
            {
                "employee": employee,
                "organization": employee.organization,
                "requires_logout": True,
            },
        )

    form = EmployeeInvitationAcceptanceForm(
        request.POST or None,
        employee=employee,
    )
    if request.method == "POST" and form.is_valid():
        try:
            user = accept_employee_invitation(
                token,
                password=form.cleaned_data["password1"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            login(request, user)
            messages.success(request, "Your employee account is active.")
            return redirect("accounts:home")

    return render(
        request,
        "employees/invitation_accept.html",
        {
            "form": form,
            "employee": employee,
            "organization": employee.organization,
            "requires_logout": False,
        },
    )
