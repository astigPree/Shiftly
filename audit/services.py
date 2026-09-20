import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from accounts.models import User
from employees.models import Employee
from .models import AuditEvent


logger = logging.getLogger("shiftly.audit")


@transaction.atomic
def record_event(*, organization, actor, action, target_type, target_id, summary, metadata=None):
    if not actor.is_authenticated:
        raise PermissionDenied("An authenticated actor is required for audit history.")
    is_owner = organization.owner_id == actor.pk and actor.role == User.Role.EMPLOYER
    is_member = actor.role == User.Role.EMPLOYEE and Employee.objects.filter(
        organization=organization, user=actor
    ).exists()
    if not (is_owner or is_member):
        raise PermissionDenied("The actor does not belong to this organization.")
    if action not in AuditEvent.Action.values:
        raise ValidationError({"action": "Choose a valid audit action."})
    if not isinstance(metadata if metadata is not None else {}, dict):
        raise ValidationError({"metadata": "Audit metadata must be an object."})

    event = AuditEvent.objects.create(
        organization=organization,
        actor=actor,
        action=action,
        target_type=target_type[:32],
        target_id=str(target_id)[:64],
        summary=summary.strip()[:255],
        metadata=metadata or {},
    )
    transaction.on_commit(
        lambda: logger.info(
            "Audit event %s recorded for organization %s (event %s)",
            event.action,
            event.organization_id,
            event.pk,
        )
    )
    return event
