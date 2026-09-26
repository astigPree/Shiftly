"""Synthetic fixtures shared by workflow, security and deployment tests."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from accounts.models import User
from organizations.models import Organization
from employees.models import Employee
from schedules.services import create_shift
from attendance.services import clock_in, clock_out, start_break, end_break
from timesheets.services import review_timesheet
from timesheets.models import TimesheetApproval
from payroll.models import (EmployeePayProfile, EmployeePayRate, PayrollSettings,
                            PayrollRuleProfile, PayrollRuleSet)

PASSWORD = "Synthetic-test-password-736!"
DAY = date(2026, 9, 21)


def workspace(suffix="a", zone="Asia/Manila"):
    owner = User.objects.create_user(email=f"owner-{suffix}@example.test", password=PASSWORD,
                                     role=User.Role.EMPLOYER, first_name="Test", last_name="Owner")
    org = Organization.objects.create(owner=owner, name=f"Test company {suffix}", timezone=zone)
    return org, owner


def employee(org, suffix="a", active=True, account=True):
    user = User.objects.create_user(email=f"staff-{suffix}@example.test", password=PASSWORD,
                                    role=User.Role.EMPLOYEE, first_name="Test", last_name=suffix) if account else None
    return Employee.objects.create(organization=org, user=user, employee_code=suffix,
        email=f"staff-{suffix}@example.test", first_name="Test", last_name=suffix, job_title="Staff",
        status=Employee.Status.ACTIVE if active else Employee.Status.INACTIVE)


def instant(day=DAY, hour=9, minute=0, zone="Asia/Manila"):
    return datetime.combine(day, time(hour, minute), ZoneInfo(zone)).astimezone(timezone.utc)


def shift(org, emp, day=DAY, start=9, end=18, allowance=60):
    return create_shift(organization=org, employee=emp, work_date=day,
        scheduled_start=instant(day, start, zone=org.timezone),
        scheduled_end=instant(day + timedelta(days=end < start), end, zone=org.timezone),
        scheduled_break_minutes=allowance, actor=org.owner)


def completed(org, emp, day=DAY, start=9, end=18, break_minutes=60, approve=True):
    work = shift(org, emp, day, start, end, break_minutes)
    session = clock_in(shift=work, employee=emp, actor=emp.user, at=work.scheduled_start)
    if break_minutes:
        pause = work.scheduled_start + timedelta(hours=2)
        start_break(session=session, employee=emp, actor=emp.user, at=pause)
        end_break(session=session, employee=emp, actor=emp.user, at=pause + timedelta(minutes=break_minutes))
    session = clock_out(session=session, employee=emp, actor=emp.user, at=work.scheduled_end)
    sheet = work.timesheet
    if approve:
        sheet, _ = review_timesheet(timesheet=sheet, reviewer=org.owner,
                                   action=TimesheetApproval.Action.APPROVED)
    return work, session, sheet


def payroll_setup(org, emp, rate="100.0000"):
    PayrollSettings.objects.get_or_create(organization=org, defaults={"frequency": "MONTHLY"})
    profile, _ = PayrollRuleProfile.objects.get_or_create(organization=org, is_default=True,
        defaults={"code": "default", "name": "Organization default", "created_by": org.owner})
    rule = PayrollRuleSet.objects.create(organization=org, rule_profile=profile,
        effective_from=date(2026, 1, 1), source_references="Synthetic reviewed test rules",
        reviewed_by="Test reviewer", reviewed_at=instant(), created_by=org.owner)
    EmployeePayProfile.objects.create(employee=emp, work_location="Manila", payroll_region="NCR",
        payroll_timezone=org.timezone, wage_order_reference="TEST-ONLY", minimum_wage_confirmed=True,
        night_differential_eligible=True)
    EmployeePayRate.objects.create(employee=emp, hourly_rate=Decimal(rate), effective_from=date(2026, 1, 1),
        change_reason="Initial test rate", created_by=org.owner)
    return profile, rule
