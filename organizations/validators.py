from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError


def validate_iana_timezone(value):
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValidationError("Select a valid IANA time zone.")
