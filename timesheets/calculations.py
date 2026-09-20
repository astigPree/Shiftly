from dataclasses import dataclass


class TimesheetCalculationError(ValueError):
    """The recorded shift data cannot safely produce a final timesheet."""


@dataclass(frozen=True)
class TimesheetCalculation:
    scheduled_minutes: int
    break_minutes: int
    worked_minutes: int
    payable_minutes: int
    late_minutes: int
    undertime_minutes: int


def _minutes_floor(seconds):
    return max(0, int(seconds // 60))


def calculate_timesheet(shift, attendance_session, breaks):
    """Calculate whole minutes from the immutable UTC event instants."""
    if attendance_session.shift_id != shift.pk:
        raise TimesheetCalculationError("The attendance session does not belong to the shift.")
    if attendance_session.employee_id != shift.employee_id or attendance_session.organization_id != shift.organization_id:
        raise TimesheetCalculationError("The attendance session does not match the shift employee or organization.")
    if attendance_session.clock_out_at is None or attendance_session.status != attendance_session.Status.COMPLETED:
        raise TimesheetCalculationError("The attendance session is incomplete.")
    if shift.status != shift.Status.SCHEDULED:
        raise TimesheetCalculationError("An attended shift is marked cancelled.")

    shift_seconds = (shift.scheduled_end - shift.scheduled_start).total_seconds()
    if shift_seconds <= 0 or shift.scheduled_break_minutes * 60 > shift_seconds:
        raise TimesheetCalculationError("The scheduled shift duration or break allowance is inconsistent.")

    clock_in = attendance_session.clock_in_at
    clock_out = attendance_session.clock_out_at
    if clock_out <= clock_in:
        raise TimesheetCalculationError("Clock-out must be after clock-in.")
    elapsed_seconds = (clock_out - clock_in).total_seconds()

    sorted_breaks = sorted(breaks, key=lambda item: item.started_at)
    break_seconds = 0
    previous_end = None
    for break_session in sorted_breaks:
        if break_session.ended_at is None:
            raise TimesheetCalculationError("An open break remains on the completed attendance session.")
        if break_session.ended_at <= break_session.started_at:
            raise TimesheetCalculationError("A break has an invalid duration.")
        if break_session.started_at < clock_in or break_session.ended_at > clock_out:
            raise TimesheetCalculationError("A break falls outside the clock-in and clock-out interval.")
        if previous_end is not None and break_session.started_at < previous_end:
            raise TimesheetCalculationError("Break intervals overlap.")
        break_seconds += (break_session.ended_at - break_session.started_at).total_seconds()
        previous_end = break_session.ended_at

    if break_seconds > elapsed_seconds:
        raise TimesheetCalculationError("Recorded break time exceeds the clocked interval.")
    worked_seconds = max(0, elapsed_seconds - break_seconds)
    scheduled_seconds = max(0, shift_seconds - shift.scheduled_break_minutes * 60)
    late_seconds = max(0, (clock_in - shift.scheduled_start).total_seconds())
    undertime_seconds = max(0, (shift.scheduled_end - clock_out).total_seconds())

    worked_minutes = _minutes_floor(worked_seconds)
    return TimesheetCalculation(
        scheduled_minutes=_minutes_floor(scheduled_seconds),
        break_minutes=_minutes_floor(break_seconds),
        worked_minutes=worked_minutes,
        payable_minutes=worked_minutes,
        late_minutes=_minutes_floor(late_seconds),
        undertime_minutes=_minutes_floor(undertime_seconds),
    )
