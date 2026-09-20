from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.forms import (
    EmployerProfileSettingsForm,
    EmployerSignupForm,
    EmployeeInvitationAcceptanceForm,
    OrganizationSettingsForm,
)
from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_event
from employees.forms import EmployeeProfileForm
from employees.models import EmployeeInvitation
from employees.services import (
    accept_employee_invitation as activate_employee_invitation,
    update_employee_profile,
)
from organizations.models import Organization
from .permissions import employee_required, employer_required, organization_for_user
from .services import (
    employer_dashboard_data,
    save_employer_profile,
    save_organization_settings,
)


class ShiftlyLoginView(LoginView):
    template_name = "registration/login.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.POST.get("remember_me"):
            self.request.session.set_expiry(None)
        else:
            self.request.session.set_expiry(0)
        messages.success(self.request, "Welcome back. You are signed in.")
        return response

    def form_invalid(self, form):
        messages.error(self.request, "We could not sign you in. Check your email and password.")
        return super().form_invalid(form)


class ShiftlyPasswordResetView(PasswordResetView):
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.info(
            self.request,
            "If an active account matches that email, a password reset link is on its way.",
        )
        return response


class ShiftlyPasswordResetConfirmView(PasswordResetConfirmView):
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Your password has been updated. You can now sign in.")
        return response


@require_GET
def index(request):
    if request.user.is_authenticated:
        return redirect("accounts:home")
    return redirect("accounts:login")


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("accounts:login")


@require_http_methods(["GET", "POST"])
def employer_signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:home")

    form = EmployerSignupForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        email=form.cleaned_data["email"],
                        password=form.cleaned_data["password1"],
                        first_name=form.cleaned_data["first_name"].strip(),
                        last_name=form.cleaned_data["last_name"].strip(),
                        role=User.Role.EMPLOYER,
                    )
                    organization = Organization.objects.create(
                        owner=user,
                        name=form.cleaned_data["organization_name"],
                        timezone=form.cleaned_data["timezone"],
                    )
                    record_event(
                        organization=organization,
                        actor=user,
                        action=AuditEvent.Action.ORGANIZATION_CREATED,
                        target_type="organization",
                        target_id=organization.pk,
                        summary="Created the organization workspace.",
                        metadata={"timezone": organization.timezone},
                    )
            except IntegrityError:
                form.add_error(
                    "email", "An account with this email address already exists."
                )
            else:
                login(request, user)
                messages.success(request, "Your Shiftly workspace is ready.")
                return redirect("accounts:home")
        messages.error(
            request,
            "We could not create your workspace. Review the highlighted fields and try again.",
        )

    return render(request, "accounts/signup.html", {"form": form})


@login_required
@require_GET
def home(request):
    organization = organization_for_user(request.user)
    if organization is None:
        raise PermissionDenied
    if request.user.role == User.Role.EMPLOYER:
        context = employer_dashboard_data(organization)
        return render(
            request,
            "accounts/dashboard.html",
            {
                "organization": organization,
                "greeting_name": request.user.get_full_name().strip()
                or request.user.email,
                **context,
            },
        )
    return redirect("attendance:my_attendance")


@require_http_methods(["GET", "POST"])
@employer_required
def workspace_settings(request):
    organization = organization_for_user(request.user)
    timezone_locked = organization.shifts.exists()
    active_section = request.GET.get("section", "organization")
    if active_section not in {"organization", "profile"}:
        active_section = "organization"

    if request.method == "POST":
        active_section = request.POST.get("settings_section", "organization")
    organization_form = OrganizationSettingsForm(
        request.POST if request.method == "POST" and active_section == "organization" else None,
        organization=organization,
        timezone_locked=timezone_locked,
    )
    profile_form = EmployerProfileSettingsForm(
        request.POST if request.method == "POST" and active_section == "profile" else None,
        user=request.user,
    )

    settings_form_invalid = False
    if request.method == "POST":
        if active_section == "organization":
            if organization_form.is_valid():
                try:
                    organization = save_organization_settings(
                        organization=organization,
                        user=request.user,
                        organization_name=organization_form.cleaned_data["organization_name"],
                        timezone_name=organization_form.cleaned_data["timezone"],
                    )
                except ValidationError as error:
                    for field, errors in error.error_dict.items():
                        for field_error in errors:
                            organization_form.add_error(field, field_error)
                else:
                    messages.success(request, "Organization settings saved.")
                    return redirect(
                        f"{reverse('accounts:settings')}?section=organization#organization-settings"
                    )
            settings_form_invalid = True
        elif active_section == "profile":
            if profile_form.is_valid():
                save_employer_profile(
                    user=request.user,
                    first_name=profile_form.cleaned_data["first_name"],
                    last_name=profile_form.cleaned_data["last_name"],
                )
                messages.success(request, "Your profile has been updated.")
                return redirect(
                    f"{reverse('accounts:settings')}?section=profile#profile-settings"
                )
            settings_form_invalid = True
        else:
            messages.error(request, "Choose a valid settings section and try again.")
            active_section = "organization"

    return render(
        request,
        "accounts/settings.html",
        {
            "organization_form": organization_form,
            "profile_form": profile_form,
            "organization": organization,
            "timezone_locked": timezone_locked,
            "active_settings_section": active_section,
            "settings_form_invalid": settings_form_invalid,
        },
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
            user = activate_employee_invitation(
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
