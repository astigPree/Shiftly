from datetime import datetime, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError


def local_datetime_to_utc(value, timezone_name):
    """Convert an unambiguous local wall time to UTC, rejecting DST gaps/folds."""
    try:
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValidationError("The organization time zone is invalid.") from error

    candidates = []
    for fold in (0, 1):
        local = value.replace(tzinfo=zone, fold=fold)
        instant = local.astimezone(datetime_timezone.utc)
        round_trip = instant.astimezone(zone)
        if round_trip.replace(tzinfo=None) == value and round_trip.fold == fold:
            candidates.append(instant)

    if not candidates:
        raise ValidationError("This local time does not exist because of a daylight-saving change.")
    if len(candidates) > 1 and candidates[0] != candidates[1]:
        raise ValidationError("This local time is ambiguous because of a daylight-saving change.")
    return candidates[0]
