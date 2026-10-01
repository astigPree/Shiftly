"""Seed two payroll employees and four months of attendance for a local employer.

This script is intentionally scoped to one organization and uses stable employee
codes so it can be run repeatedly without creating duplicate employees, shifts,
attendance sessions, or timesheets.

Run from the project root with:

    $env:DJANGO_SETTINGS_MODULE='config.settings'
    .venv\Scripts\python.exe scripts\seed_max_payroll_employees.py

The seed is synthetic test data. Replace the wage-order references before using
the records for a real payroll run.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
import os
import sys
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from accounts.permissions import organization_for_user
from audit.models import AuditEvent
from audit.services import record_event
from attendance.models import AttendanceSession, BreakSession
from employees.models import Employee
from payroll.models import (
    EmployeeCompensationVersion,
    EmployeePayProfile,
    PayrollRuleProfile,
    PayrollRuleSet,
)
from schedules.models import Shift
from timesheets.models import Timesheet, TimesheetApproval
from timesheets.services import generate_timesheet, recalculate_timesheet, review_timesheet


EMPLOYER_EMAIL = "max@gmail.com"
WORK_TIMEZONE = ZoneInfo("Asia/Manila")
WORK_LOCATION = "Seed work location (replace with actual location)"
PAYROLL_REGION = "NCR"
WAGE_ORDER_REFERENCE = "TEST SEED - replace with official wage-order reference"
SEED_REVIEWER = "Payroll seed reviewer"


EMPLOYEE_SPECS = (
    {
        "code": "REG-SEED-001",
        "first_name": "Regular",
        "last_name": "Seed Employee",
        "email": "regular.seed.max@example.test",
        "job_title": "Regular Staff",
        "employment_status": EmployeePayProfile.EmploymentStatus.REGULAR,
        "hourly_rate": Decimal("150.0000"),
        "workdays": {0, 1, 2, 3, 4},  # Monday through Friday
        "start_time": time(9, 0),
        "end_time": time(18, 0),
        "break_minutes": 60,
        "clock_in_delta": 5,
        "clock_out_delta": -5,
        "rest_day": 6,  # Sunday
    },
    {
        "code": "PT-SEED-001",
        "first_name": "Part-time",
        "last_name": "Seed Employee",
        "email": "parttime.seed.max@example.test",
        "job_title": "Part-time Staff",
        "employment_status": EmployeePayProfile.EmploymentStatus.PART_TIME,
        "hourly_rate": Decimal("120.0000"),
        "workdays": {0, 2, 4},  # Monday, Wednesday, Friday
        "start_time": time(9, 0),
        "end_time": time(13, 0),
        "break_minutes": 0,
        "clock_in_delta": 0,
        "clock_out_delta": 0,
        "rest_day": 1,  # Tuesday
    },
)


def first_day_four_month_window(today):
    """Return the first day of the month four months including this month."""
    month_index = today.year * 12 + today.month - 1 - 3
    year, month_zero_based = divmod(month_index, 12)
    return date(year, month_zero_based + 1, 1)


def local_datetime(work_date, clock_time, minute_delta=0):
    value = datetime.combine(work_date, clock_time, tzinfo=WORK_TIMEZONE)
    return value + timedelta(minutes=minute_delta)


def iter_workdays(start, end, weekdays):
    cursor = start
    while cursor <= end:
        if cursor.weekday() in weekdays:
            yield cursor
        cursor += timedelta(days=1)


def ensure_historical_rules(organization, actor, start, end):
    """Cover the seeded dates without changing the existing current rule version."""
    profile = PayrollRuleProfile.objects.get(
        organization=organization,
        is_default=True,
        active=True,
    )
    # Leave the existing current/future version untouched. The historical row
    # ends the day before it so effective-date resolution remains unambiguous.
    historical_end = end
    future_rules = (
        PayrollRuleSet.objects.filter(
            organization=organization,
            rule_profile=profile,
            effective_from__gt=start,
        )
        .order_by("effective_from", "pk")
        .first()
    )
    if future_rules:
        historical_end = min(historical_end, future_rules.effective_from - timedelta(days=1))
        source = future_rules.source_references
        values = {
            "regular_day_minutes": future_rules.regular_day_minutes,
            "overtime_multiplier": future_rules.overtime_multiplier,
            "rest_day_multiplier": future_rules.rest_day_multiplier,
            "rest_day_overtime_multiplier": future_rules.rest_day_overtime_multiplier,
            "night_start": future_rules.night_start,
            "night_end": future_rules.night_end,
            "night_differential_rate": future_rules.night_differential_rate,
        }
    else:
        source = "TEST SEED - replace with official payroll rule source"
        values = {
            "regular_day_minutes": 480,
            "overtime_multiplier": Decimal("1.250"),
            "rest_day_multiplier": Decimal("1.300"),
            "rest_day_overtime_multiplier": Decimal("1.690"),
            "night_start": time(22, 0),
            "night_end": time(6, 0),
            "night_differential_rate": Decimal("0.1000"),
        }
    if historical_end < start:
        return None, False

    rules, created = PayrollRuleSet.objects.get_or_create(
        organization=organization,
        rule_profile=profile,
        effective_from=start,
        defaults={
            **values,
            "effective_until": historical_end,
            "source_references": source,
            "reviewed_by": SEED_REVIEWER,
            "reviewed_at": timezone.now(),
            "created_by": actor,
        },
    )
    return rules, created


def ensure_employee(organization, actor, spec):
    employee, created = Employee.objects.get_or_create(
        organization=organization,
        employee_code=spec["code"],
        defaults={
            "first_name": spec["first_name"],
            "last_name": spec["last_name"],
            "email": spec["email"],
            "job_title": spec["job_title"],
            "status": Employee.Status.ACTIVE,
        },
    )
    if created:
        record_event(
            organization=organization,
            actor=actor,
            action=AuditEvent.Action.EMPLOYEE_CREATED,
            target_type="employee",
            target_id=employee.pk,
            summary=f"Created seeded employee {employee.employee_code}.",
            metadata={"seed": True, "employment_status": spec["employment_status"]},
        )
    return employee, created


def ensure_payroll_profile(organization, actor, employee, spec):
    profile, _ = EmployeePayProfile.objects.update_or_create(
        employee=employee,
        defaults={
            "employment_status": spec["employment_status"],
            "pay_basis": EmployeePayProfile.PayBasis.HOURLY,
            "minimum_daily_rate": None,
            "work_location": WORK_LOCATION,
            "payroll_region": PAYROLL_REGION,
            "payroll_timezone": "Asia/Manila",
            "wage_order_reference": WAGE_ORDER_REFERENCE,
            "minimum_wage_confirmed": True,
            "night_differential_eligible": True,
            "rest_day": spec["rest_day"],
            "rank_and_file": True,
            "active_for_payroll": True,
        },
    )
    EmployeeCompensationVersion.objects.get_or_create(
        organization=organization,
        employee=employee,
        effective_from=first_day_four_month_window(timezone.localdate()),
        defaults={
            "basis": EmployeeCompensationVersion.Basis.HOURLY,
            "amount": spec["hourly_rate"],
            "regular_day_minutes": 480,
            "currency": "PHP",
            "source_reference": WAGE_ORDER_REFERENCE,
            "reviewed_by": SEED_REVIEWER,
            "reviewed_at": timezone.now(),
            "created_by": actor,
        },
    )
    return profile


def ensure_shift_and_attendance(organization, actor, employee, spec, work_date):
    scheduled_start = local_datetime(work_date, spec["start_time"])
    scheduled_end = local_datetime(work_date, spec["end_time"])
    shift, _ = Shift.objects.get_or_create(
        organization=organization,
        employee=employee,
        work_date=work_date,
        defaults={
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "scheduled_break_minutes": spec["break_minutes"],
            "status": Shift.Status.SCHEDULED,
        },
    )
    session, session_created = AttendanceSession.objects.get_or_create(
        organization=organization,
        employee=employee,
        shift=shift,
        defaults={
            "clock_in_at": local_datetime(work_date, spec["start_time"], spec["clock_in_delta"]),
            "clock_out_at": local_datetime(work_date, spec["end_time"], spec["clock_out_delta"]),
            "status": AttendanceSession.Status.COMPLETED,
        },
    )
    if session_created and spec["break_minutes"]:
        break_start = local_datetime(work_date, time(13, 0))
        BreakSession.objects.create(
            attendance_session=session,
            started_at=break_start,
            ended_at=break_start + timedelta(minutes=spec["break_minutes"]),
        )
    # Let the application service create and calculate a new timesheet. Calling
    # get_or_create first would leave a newly inserted row with zeroed details,
    # because generate_timesheet correctly returns any existing row unchanged.
    try:
        timesheet = Timesheet.objects.get(shift=shift)
        timesheet_created = False
    except Timesheet.DoesNotExist:
        timesheet = generate_timesheet(session)
        timesheet_created = True
    expected_scheduled_minutes = shift.scheduled_minutes
    if timesheet.scheduled_minutes != expected_scheduled_minutes:
        timesheet = recalculate_timesheet(timesheet, attendance_session=session)
    if timesheet.status == Timesheet.Status.PENDING:
        review_timesheet(
            timesheet=timesheet,
            reviewer=actor,
            action=TimesheetApproval.Action.APPROVED,
            comment="Approved seeded attendance for payroll testing.",
        )
    return shift, session, timesheet


@transaction.atomic
def seed():
    User = get_user_model()
    actor = User.objects.get(email__iexact=EMPLOYER_EMAIL)
    organization = organization_for_user(actor)
    if organization is None:
        raise RuntimeError(f"No organization is linked to {EMPLOYER_EMAIL}.")

    today = timezone.localdate()
    start = first_day_four_month_window(today)
    end = today
    rules, rules_created = ensure_historical_rules(organization, actor, start, end)
    results = []
    for spec in EMPLOYEE_SPECS:
        employee, employee_created = ensure_employee(organization, actor, spec)
        ensure_payroll_profile(organization, actor, employee, spec)
        shifts_created = sessions_created = timesheets_created = 0
        for work_date in iter_workdays(start, end, spec["workdays"]):
            shift_before = Shift.objects.filter(employee=employee, work_date=work_date).exists()
            session_before = AttendanceSession.objects.filter(employee=employee, shift__work_date=work_date).exists()
            timesheet_before = Timesheet.objects.filter(employee=employee, shift__work_date=work_date).exists()
            ensure_shift_and_attendance(organization, actor, employee, spec, work_date)
            shifts_created += int(not shift_before)
            sessions_created += int(not session_before)
            timesheets_created += int(not timesheet_before)
        results.append((employee, employee_created, shifts_created, sessions_created, timesheets_created))

    print(f"Employer: {actor.email}")
    print(f"Organization: {organization.name} (#{organization.pk})")
    print(f"Seed window: {start} through {end}")
    print(f"Historical payroll rules: {'created' if rules_created else 'already present'} ({rules and rules.effective_from}–{rules and rules.effective_until})")
    for employee, created, shift_count, session_count, timesheet_count in results:
        print(
            f"{employee.employee_code} | {employee.full_name} | "
            f"{'created' if created else 'existing'} | "
            f"new shifts={shift_count}, attendance={session_count}, timesheets={timesheet_count}"
        )


if __name__ == "__main__":
    seed()
