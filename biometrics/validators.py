from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, TypeError):
        raise ValidationError("Enter a valid IANA time zone, such as Asia/Manila.")

