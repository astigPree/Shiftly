"""Pure compensation calculations used by the payroll service.

The functions in this module have no database access.  They make the quantity
source and the conversion policy explicit so a reviewed workbook/register
import can be compared with the same deterministic calculation used in a run.
"""

from decimal import Decimal


def calculate_daily_pay(*, daily_rate, worked_day_units, planned_day_units,
                        undertime_minutes=0, overtime_minutes=0,
                        night_minutes=0, holiday_units=Decimal("0"),
                        regular_day_minutes=480, overtime_multiplier=Decimal("1"),
                        night_differential_rate=Decimal("0")):
    """Return daily-register amounts without double-counting absence/UT.

    ``worked_day_units`` is the approved paid quantity.  Planned units are
    retained for the absence explanation only; they are not subtracted again
    from the paid quantity.  Overtime and night values are premiums on top of
    the daily base, matching Shiftly's existing hourly line presentation.
    """
    daily_rate = Decimal(daily_rate)
    worked_day_units = Decimal(worked_day_units)
    planned_day_units = Decimal(planned_day_units)
    holiday_units = Decimal(holiday_units)
    day_minutes = Decimal(regular_day_minutes)
    if daily_rate <= 0 or day_minutes <= 0:
        raise ValueError("Daily rate and regular day length must be positive.")
    if worked_day_units < 0 or planned_day_units < 0:
        raise ValueError("Day quantities cannot be negative.")
    if worked_day_units > planned_day_units:
        raise ValueError("Worked day units cannot exceed planned day units.")
    if any(int(value) < 0 for value in (undertime_minutes, overtime_minutes, night_minutes)):
        raise ValueError("Minute quantities cannot be negative.")
    basic = daily_rate * worked_day_units
    undertime = daily_rate / day_minutes * Decimal(undertime_minutes)
    undertime = min(undertime, basic)
    overtime_premium = daily_rate / day_minutes * Decimal(overtime_minutes) * (Decimal(overtime_multiplier) - Decimal("1"))
    night_differential = daily_rate / day_minutes * Decimal(night_minutes) * Decimal(night_differential_rate)
    holiday_premium = daily_rate * holiday_units
    return {
        "basic": basic - undertime,
        "undertime": undertime,
        "overtime_premium": overtime_premium,
        "night_differential": night_differential,
        "holiday_premium": holiday_premium,
        "payable_hours": worked_day_units * day_minutes / Decimal("60"),
        "absence_units": max(Decimal("0"), planned_day_units - worked_day_units),
    }
