from django.conf import settings
from django.utils import timezone

from accounts.permissions import organization_for_user


def _timezone_city_name(timezone_name):
    city = timezone_name.rsplit("/", 1)[-1].replace("_", " ")
    if city.startswith("Etc/"):
        city = city[4:]
    return city


def timezone_preferences(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    organization = organization_for_user(user)
    organization_timezone = (
        organization.timezone if organization else settings.TIME_ZONE
    )
    viewer_timezone = user.preferred_timezone or organization_timezone
    now = timezone.now()

    return {
        "timezone_now": now,
        "company_timezone": organization_timezone,
        "company_timezone_label": _timezone_city_name(organization_timezone),
        "viewer_timezone": viewer_timezone,
        "viewer_timezone_label": _timezone_city_name(viewer_timezone),
    }
