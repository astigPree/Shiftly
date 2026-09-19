from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.forms import EmployerSignupForm, EmployeeInvitationAcceptanceForm
from accounts.models import User
from employees.models import EmployeeInvitation
from employees.services import accept_employee_invitation
from organizations.models import Organization
from .permissions import organization_for_user


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
    employee = getattr(request.user, "employee_profile", None)
    return render(
        request,
        "accounts/home.html",
        {"organization": organization, "employee": employee},
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
