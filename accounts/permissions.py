from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def organization_for_user(user):
    if not getattr(user, "is_authenticated", False):
        return None

    if user.role == user.Role.EMPLOYER:
        organization = getattr(user, "organization", None)
        if organization and organization.owner_id == user.pk:
            return organization
        return None

    if user.role == user.Role.EMPLOYEE:
        employee = getattr(user, "employee_profile", None)
        if employee and employee.status == employee.Status.ACTIVE:
            return employee.organization
    return None


def organization_scoped_queryset(user, queryset, field="organization"):
    organization = organization_for_user(user)
    if organization is None:
        return queryset.none()
    return queryset.filter(**{field: organization})


def role_required(role):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if request.user.role != role or organization_for_user(request.user) is None:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def employer_required(view_func):
    from accounts.models import User

    return role_required(User.Role.EMPLOYER)(view_func)


def employee_required(view_func):
    from accounts.models import User

    return role_required(User.Role.EMPLOYEE)(view_func)


organization_owner_required = employer_required
