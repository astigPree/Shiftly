import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import organization_for_user
from accounts.models import User
from .models import Employee, EmployeeInvitation


def invitation_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@transaction.atomic
def issue_employee_invitation(employee, actor, request):
    organization = organization_for_user(actor)
    if actor.role != User.Role.EMPLOYER or organization is None:
        raise PermissionDenied
    if employee.organization_id != organization.pk:
        raise PermissionDenied
    if employee.user_id or employee.status != Employee.Status.ACTIVE:
        raise ValidationError("Only active employees without an account can be invited.")
    if get_user_model().objects.filter(email__iexact=employee.email).exists():
        raise ValidationError("An account with this email address already exists.")

    now = timezone.now()
    EmployeeInvitation.objects.filter(
        employee=employee,
        accepted_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=now)

    token = secrets.token_urlsafe(32)
    invitation = EmployeeInvitation.objects.create(
        employee=employee,
        email=employee.email,
        token_digest=invitation_digest(token),
        created_by=actor,
        expires_at=now + timedelta(hours=72),
    )
    invitation_url = request.build_absolute_uri(
        reverse("accounts:invite_accept", kwargs={"token": token})
    )
    send_mail(
        subject="Activate your Shiftly account",
        message=(
            f"Hello {employee.first_name},\n\n"
            f"{actor.get_full_name() or actor.email} invited you to join "
            f"{organization.name} on Shiftly. Set your password using this link:\n\n"
            f"{invitation_url}\n\nThis link expires in 72 hours."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[employee.email],
        fail_silently=False,
    )
    return invitation


@transaction.atomic
def accept_employee_invitation(token, password):
    now = timezone.now()
    invitation = (
        EmployeeInvitation.objects.select_for_update()
        .select_related("employee", "employee__organization")
        .filter(
            token_digest=invitation_digest(token),
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=now,
        )
        .first()
    )
    if invitation is None:
        raise ValidationError("This invitation is invalid or has expired.")

    employee = invitation.employee
    if employee.user_id or employee.status != Employee.Status.ACTIVE:
        raise ValidationError("This invitation is no longer available.")
    if employee.email.casefold() != invitation.email.casefold():
        raise ValidationError("The employee email changed after this invitation was sent.")

    try:
        user = get_user_model().objects.create_user(
            email=employee.email,
            password=password,
            first_name=employee.first_name,
            last_name=employee.last_name,
            role=User.Role.EMPLOYEE,
        )
    except IntegrityError as error:
        raise ValidationError("An account with this email address already exists.") from error

    employee.user = user
    employee.save(update_fields=["user", "updated_at"])
    invitation.accepted_at = now
    invitation.save(update_fields=["accepted_at"])
    return user
