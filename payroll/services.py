from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal, ROUND_HALF_UP
import uuid
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from accounts.permissions import organization_for_user
from audit.models import AuditEvent
from audit.services import record_event
from attendance.models import AttendanceSession
from employees.models import Employee
from timesheets.models import Timesheet
from schedules.models import Shift

from .models import (
    EmployeePayProfile,
    EmployeePayRate,
    PayrollException,
    PayrollHoliday,
    PayrollLine,
    PayrollCalculationSnapshot,
    PayrollRuleAssignment,
    PayrollRuleProfile,
    PayrollRuleSet,
    PayrollRun,
    PayrollSettings,
    PayrollStatement,
    PayrollTimeEntry,
)


CENT = Decimal("0.01")
HOUR_SECONDS = Decimal("3600")


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _owner_organization(actor, organization_id=None):
    if not actor.is_authenticated or actor.role != User.Role.EMPLOYER:
        raise PermissionDenied("Only an employer can manage payroll.")
    organization = organization_for_user(actor)
    if organization is None or (organization_id and organization.pk != organization_id):
        raise PermissionDenied("You cannot manage payroll for this organization.")
    return organization


def resolve_rule_profile(organization, work_date, employee=None):
    """Resolve the employee override or organization default for a local work date."""
    if employee is not None:
        assignments = list(PayrollRuleAssignment.objects.filter(
            organization=organization,
            employee=employee,
            effective_from__lte=work_date,
        ).filter(
            Q(effective_until__isnull=True) | Q(effective_until__gte=work_date)
        ).select_related("rule_profile").order_by("-effective_from", "-pk")[:2])
        if len(assignments) > 1:
            raise ValidationError(
                f"{employee.full_name} has overlapping payroll rule assignments on {work_date}."
            )
        if assignments:
            assignment = assignments[0]
            if not assignment.rule_profile.active:
                raise ValidationError(
                    f"Payroll rule profile {assignment.rule_profile.name} is inactive for {employee.full_name}."
                )
            return assignment.rule_profile, assignment

    default_profile = PayrollRuleProfile.objects.filter(
        organization=organization, is_default=True, active=True,
    ).first()
    return default_profile, None


def resolve_effective_rule(organization, work_date, employee=None):
    profile, assignment = resolve_rule_profile(organization, work_date, employee=employee)
    if profile is not None:
        rule = PayrollRuleSet.objects.filter(
            rule_profile=profile,
            effective_from__lte=work_date,
        ).filter(
            Q(effective_until__isnull=True) | Q(effective_until__gte=work_date)
        ).order_by("-effective_from", "-pk").first()
        return rule, profile, assignment

    # Keep legacy rows readable if a database was upgraded without the data
    # migration completing. New rows always use a named rule profile.
    rule = PayrollRuleSet.objects.filter(
        organization=organization,
        rule_profile__isnull=True,
        effective_from__lte=work_date,
    ).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gte=work_date)
    ).order_by("-effective_from", "-pk").first()
    return rule, None, None


def effective_rule_set(organization, work_date, employee=None):
    return resolve_effective_rule(organization, work_date, employee=employee)[0]


def effective_pay_rate(employee, work_date):
    return EmployeePayRate.objects.filter(
        employee=employee,
        effective_from__lte=work_date,
    ).filter(Q(effective_until__isnull=True) | Q(effective_until__gte=work_date)).order_by("-effective_from").first()


def _worked_intervals(session, breaks):
    if session.clock_out_at is None or session.clock_out_at <= session.clock_in_at:
        raise ValidationError("A completed attendance interval is required for payroll.")
    cursor = session.clock_in_at
    result = []
    for pause in sorted(breaks, key=lambda item: item.started_at):
        if pause.ended_at is None or pause.started_at < cursor or pause.ended_at > session.clock_out_at:
            raise ValidationError("The attendance breaks are incomplete or inconsistent.")
        if pause.started_at > cursor:
            result.append((cursor, pause.started_at))
        cursor = pause.ended_at
    if cursor < session.clock_out_at:
        result.append((cursor, session.clock_out_at))
    return result


def _night_window_contains(local_time, start, end):
    if start == end:
        return True
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def _local_wall_boundaries(day, wall_time, zone):
    """Return real UTC instants for a local wall-time boundary, handling DST folds/gaps."""
    wall = datetime.combine(day, wall_time)
    instants = set()
    for fold in (0, 1):
        candidate = wall.replace(tzinfo=zone, fold=fold)
        instant = candidate.astimezone(datetime_timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) == wall:
            instants.add(instant)
    return sorted(instants)


def _offset_transition_boundaries(start, end, zone):
    """Find UTC offset changes inside an interval so DST jumps split work segments."""
    boundaries = []
    probe = start
    probe_offset = probe.astimezone(zone).utcoffset()
    step = timedelta(hours=3)
    while probe < end:
        sample = min(probe + step, end)
        sample_offset = sample.astimezone(zone).utcoffset()
        if sample_offset != probe_offset:
            low = int(probe.timestamp())
            high = int(sample.timestamp())
            while high - low > 1:
                middle = (low + high) // 2
                instant = datetime.fromtimestamp(middle, datetime_timezone.utc)
                if instant.astimezone(zone).utcoffset() == probe_offset:
                    low = middle
                else:
                    high = middle
            transition = datetime.fromtimestamp(high, datetime_timezone.utc)
            boundaries.append(transition)
            probe = transition
            probe_offset = probe.astimezone(zone).utcoffset()
        else:
            probe = sample
    return boundaries


def split_worked_segments(session, breaks, *, zone_name, organization, rule_set, employee=None, period_start=None, period_end=None):
    """Split worked intervals at local midnight and night-window boundaries."""
    zone = ZoneInfo(zone_name)
    chunks = []
    for interval_start, interval_end in _worked_intervals(session, breaks):
        cursor = interval_start.astimezone(datetime_timezone.utc)
        interval_end = interval_end.astimezone(datetime_timezone.utc)
        offset_boundaries = _offset_transition_boundaries(cursor, interval_end, zone)
        while cursor < interval_end:
            local = cursor.astimezone(zone)
            current_rule = effective_rule_set(organization, local.date(), employee=employee) or rule_set
            next_date = local.date() + timedelta(days=1)
            boundaries = [boundary for boundary in offset_boundaries if boundary > cursor]
            boundaries.extend(_local_wall_boundaries(next_date, time.min, zone))
            for candidate_day in (local.date(), next_date):
                boundary_rule = effective_rule_set(organization, candidate_day, employee=employee) or current_rule
                for wall_time in (boundary_rule.night_start, boundary_rule.night_end):
                    boundaries.extend(_local_wall_boundaries(candidate_day, wall_time, zone))
            future = [boundary for boundary in boundaries if cursor < boundary < interval_end]
            end = min(future) if future else interval_end
            work_date = local.date()
            if (period_start is None or work_date >= period_start) and (period_end is None or work_date <= period_end):
                chunks.append({
                    "start": cursor,
                    "end": end,
                    "work_date": work_date,
                    "seconds": Decimal(str((end - cursor).total_seconds())),
                    "night": _night_window_contains(local.timetz().replace(tzinfo=None), current_rule.night_start, current_rule.night_end),
                })
            cursor = end
    return chunks


def _add_exception(run, *, code, description, employee=None, timesheet=None, work_date=None):
    return PayrollException.objects.create(
        run=run,
        employee=employee,
        timesheet=timesheet,
        code=code,
        description=description[:255],
        work_date=work_date,
    )


def _refresh_statement(statement):
    totals = defaultdict(Decimal)
    for line in statement.lines.all():
        totals[line.kind] += line.amount
    statement.gross_amount = _money(totals[PayrollLine.Kind.EARNING])
    statement.deduction_amount = _money(totals[PayrollLine.Kind.DEDUCTION])
    statement.employer_contribution_amount = _money(totals[PayrollLine.Kind.EMPLOYER_CONTRIBUTION])
    statement.net_amount = _money(statement.gross_amount - statement.deduction_amount)
    statement.save(update_fields=[
        "gross_amount", "deduction_amount", "employer_contribution_amount", "net_amount", "updated_at"
    ])


def _record_preview(run, actor):
    statements = []
    for statement in run.statements.select_related("employee").prefetch_related("lines", "time_entries"):
        statements.append({
            "employee_code": statement.employee.employee_code,
            "employee_name": statement.employee.full_name,
            "gross": str(statement.gross_amount),
            "deductions": str(statement.deduction_amount),
            "employer_contributions": str(statement.employer_contribution_amount),
            "net": str(statement.net_amount),
            "calculation_inputs": statement.snapshot,
            "time_entries": [{
                "timesheet_id": entry.timesheet_id,
                "work_date": entry.work_date.isoformat(),
                "payable_minutes": entry.payable_minutes,
                "night_minutes": entry.night_minutes,
                "overtime_minutes": entry.overtime_minutes,
                "rate_snapshot": str(entry.rate_snapshot),
                "snapshot": entry.snapshot,
            } for entry in statement.time_entries.all()],
            "lines": [{
                "kind": line.kind, "code": line.code, "label": line.label,
                "amount": str(line.amount), "effective_date": line.effective_date.isoformat() if line.effective_date else None,
                "source": line.source, "note": line.note,
                "created_by": (line.created_by.get_full_name() or line.created_by.email) if line.created_by_id else None,
                "created_at": line.created_at.isoformat(),
            } for line in statement.lines.all()],
        })
    exceptions = [{
        "code": item.code,
        "employee_code": item.employee.employee_code if item.employee_id else None,
        "work_date": item.work_date.isoformat() if item.work_date else None,
        "description": item.description,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "resolved_by": (item.resolved_by.get_full_name() or item.resolved_by.email) if item.resolved_by_id else None,
        "resolution_note": item.resolution_note,
        "resolution_line_id": item.resolution_line_id,
    } for item in run.exceptions.filter(superseded_at__isnull=True).select_related("employee")]
    sequence = run.calculation_previews.count() + 1
    PayrollCalculationSnapshot.objects.create(
        run=run,
        sequence=sequence,
        created_by=actor,
        data={"run": run.reference, "sequence": sequence, "calculation_version": 1, "pay_frequency": run.pay_frequency, "statements": statements, "exceptions": exceptions},
    )


def _employee_payroll_timezone(employee, organization):
    profile = getattr(employee, "payroll_profile", None)
    return (profile.payroll_timezone if profile and profile.payroll_timezone else organization.timezone)


def _validate_pay_period(settings_row, period_start, period_end, pay_date, run_type):
    if period_end < period_start:
        raise ValidationError({"period_end": "The period end must be on or after the period start."})
    if pay_date < period_end:
        raise ValidationError({"pay_date": "Pay date must be on or after the end of the payroll period."})
    if run_type != PayrollRun.RunType.REGULAR:
        return
    frequency = settings_row.frequency
    if frequency == PayrollSettings.Frequency.WEEKLY:
        if period_start.weekday() != 0 or period_end != period_start + timedelta(days=6):
            raise ValidationError("Weekly payroll periods run Monday through Sunday.")
    elif frequency == PayrollSettings.Frequency.SEMI_MONTHLY:
        last_day = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        valid = (period_start.day == 1 and period_end == period_start.replace(day=15)) or (
            period_start.day == 16 and period_end == last_day
        )
        if not valid:
            raise ValidationError("Semi-monthly periods run from the 1st–15th or 16th–month end.")
    elif frequency == PayrollSettings.Frequency.MONTHLY:
        last_day = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if period_start.day != 1 or period_end != last_day:
            raise ValidationError("Monthly payroll periods run from the first through the last day of a month.")


@transaction.atomic
def create_payroll_run(*, organization, actor, period_start, period_end, pay_date, run_type=PayrollRun.RunType.REGULAR, parent_run=None, idempotency_key=None):
    organization = _owner_organization(actor, organization.pk)
    settings_row = PayrollSettings.objects.filter(organization=organization).first()
    if settings_row is None:
        raise ValidationError("Save payroll settings before creating a payroll run.")
    # Serialize run creation for this organization so overlapping-period checks are safe under concurrency.
    settings_row = PayrollSettings.objects.select_for_update().get(pk=settings_row.pk)
    _validate_pay_period(settings_row, period_start, period_end, pay_date, run_type)
    if idempotency_key:
        existing = PayrollRun.objects.filter(organization=organization, idempotency_key=idempotency_key).first()
        if existing:
            if (existing.period_start, existing.period_end, existing.pay_date, existing.run_type, existing.parent_run_id) != (
                period_start, period_end, pay_date, run_type, getattr(parent_run, "pk", None)
            ):
                raise ValidationError("This payroll submission token was already used for different run details.")
            return existing
    if run_type == PayrollRun.RunType.REGULAR:
        overlaps = PayrollRun.objects.select_for_update().filter(
            organization=organization,
            run_type=PayrollRun.RunType.REGULAR,
            status__in=[PayrollRun.Status.DRAFT, PayrollRun.Status.REVIEW, PayrollRun.Status.FINALIZED],
            period_start__lte=period_end,
            period_end__gte=period_start,
        )
        if overlaps.exists():
            raise ValidationError("A regular payroll run already covers some or all of these dates.")
    if run_type == PayrollRun.RunType.OFF_CYCLE:
        if not parent_run:
            raise ValidationError("An off-cycle run must link to a finalized run in this organization.")
        parent_run = PayrollRun.objects.select_for_update().filter(
            organization=organization, pk=parent_run.pk, status=PayrollRun.Status.FINALIZED
        ).first()
        if not parent_run:
            raise ValidationError("An off-cycle run must link to a finalized run in this organization.")
        if (period_start, period_end) != (parent_run.period_start, parent_run.period_end):
            raise ValidationError("An off-cycle correction must use the linked run's pay period.")
    elif parent_run:
        raise ValidationError("Only an off-cycle run can be linked to a prior run.")
    reference = f"PAY-{period_start:%Y%m%d}-{period_end:%Y%m%d}"
    if run_type == PayrollRun.RunType.OFF_CYCLE:
        reference = f"{reference}-OFF-{timezone.now():%H%M%S%f}"[-40:]
    elif PayrollRun.objects.filter(organization=organization, reference=reference).exists():
        suffix = 2
        base_reference = reference
        while PayrollRun.objects.filter(organization=organization, reference=reference).exists():
            reference = f"{base_reference}-R{suffix}"
            suffix += 1
    try:
        with transaction.atomic():
            run = PayrollRun.objects.create(
                organization=organization,
                reference=reference,
                idempotency_key=idempotency_key or uuid.uuid4(),
                run_type=run_type,
                parent_run=parent_run,
                period_start=period_start,
                period_end=period_end,
                pay_date=pay_date,
                pay_frequency=settings_row.frequency,
                currency=settings_row.currency,
                prepared_by=actor,
            )
    except IntegrityError as error:
        if idempotency_key:
            existing = PayrollRun.objects.filter(organization=organization, idempotency_key=idempotency_key).first()
            if existing:
                return existing
        raise ValidationError("A payroll run with this reference already exists.") from error
    record_event(
        organization=organization,
        actor=actor,
        action=AuditEvent.Action.PAYROLL_RUN_CREATED,
        target_type="payroll_run",
        target_id=run.pk,
        summary=f"Created payroll run {run.reference}.",
        metadata={"period_start": period_start.isoformat(), "period_end": period_end.isoformat(), "run_type": run_type},
    )
    calculate_payroll_run(run, actor=actor)
    return run


@transaction.atomic
def calculate_payroll_run(run, *, actor):
    organization = _owner_organization(actor, run.organization_id)
    run = PayrollRun.objects.select_for_update().select_related("organization").get(pk=run.pk, organization=organization)
    if run.status != PayrollRun.Status.DRAFT:
        raise ValidationError("Only a draft payroll run can be recalculated.")

    # Recalculation is repeatable: remove the old machine preview but keep manual adjustments.
    PayrollLine.objects.filter(statement__run=run, source="CALCULATED").delete()
    PayrollTimeEntry.objects.filter(statement__run=run).delete()
    PayrollException.objects.filter(run=run, superseded_at__isnull=True).update(superseded_at=timezone.now())

    statements_by_employee = {
        item.employee_id: item
        for item in PayrollStatement.objects.filter(run=run).select_related("employee")
    }

    if run.run_type == PayrollRun.RunType.OFF_CYCLE:
        for statement in statements_by_employee.values():
            _refresh_statement(statement)
        _record_preview(run, actor)
        record_event(organization=organization, actor=actor, action=AuditEvent.Action.PAYROLL_RUN_RECALCULATED, target_type="payroll_run", target_id=run.pk, summary=f"Recorded payroll preview {run.reference}.")
        return run

    zone = ZoneInfo(organization.timezone)
    # Search a two-day margin because employee work-location dates can differ from
    # the organization's calendar date around midnight.
    start_local = datetime.combine(run.period_start - timedelta(days=2), time.min).replace(tzinfo=zone)
    end_local = datetime.combine(run.period_end + timedelta(days=3), time.min).replace(tzinfo=zone)
    timesheets = Timesheet.objects.filter(
        organization=organization,
        attendance_session__clock_out_at__gt=start_local.astimezone(datetime_timezone.utc),
        attendance_session__clock_in_at__lt=end_local.astimezone(datetime_timezone.utc),
    ).select_related("employee", "employee__payroll_profile", "shift", "attendance_session", "employee__organization").prefetch_related("attendance_session__breaks").order_by("employee_id", "shift__work_date", "pk")

    # Scheduled absences and sessions that have not produced a complete timesheet must not disappear from the preview.
    now = timezone.now()
    absent_shifts = Shift.objects.filter(
        organization=organization,
        status=Shift.Status.SCHEDULED,
        work_date__range=(run.period_start - timedelta(days=2), run.period_end + timedelta(days=2)),
        scheduled_end__lte=now,
        attendance_session__isnull=True,
        timesheet__isnull=True,
    ).select_related("employee", "employee__payroll_profile")
    for shift in absent_shifts:
        payroll_timezone = _employee_payroll_timezone(shift.employee, organization)
        work_date = shift.scheduled_start.astimezone(ZoneInfo(payroll_timezone)).date()
        if run.period_start <= work_date <= run.period_end:
            _add_exception(run, code="NO_ATTENDANCE", description=f"{shift.employee.full_name} has no attendance session for the scheduled shift on {work_date}.", employee=shift.employee, work_date=work_date)

    incomplete_sessions = AttendanceSession.objects.filter(
        organization=organization,
        shift__work_date__range=(run.period_start - timedelta(days=2), run.period_end + timedelta(days=2)),
        clock_out_at__isnull=True,
    ).select_related("employee", "shift", "employee__payroll_profile")
    for session in incomplete_sessions:
        payroll_timezone = _employee_payroll_timezone(session.employee, organization)
        work_date = session.shift.scheduled_start.astimezone(ZoneInfo(payroll_timezone)).date()
        if run.period_start <= work_date <= run.period_end:
            _add_exception(run, code="INCOMPLETE_ATTENDANCE", description=f"{session.employee.full_name} has an attendance session without clock-out for {work_date}.", employee=session.employee, work_date=work_date)

    completed_without_timesheet = AttendanceSession.objects.filter(
        organization=organization,
        shift__work_date__range=(run.period_start - timedelta(days=2), run.period_end + timedelta(days=2)),
        clock_out_at__isnull=False,
        shift__timesheet__isnull=True,
    ).select_related("employee", "shift", "employee__payroll_profile")
    for session in completed_without_timesheet:
        payroll_timezone = _employee_payroll_timezone(session.employee, organization)
        work_date = session.shift.scheduled_start.astimezone(ZoneInfo(payroll_timezone)).date()
        if run.period_start <= work_date <= run.period_end:
            _add_exception(run, code="MISSING_TIMESHEET", description=f"{session.employee.full_name} has a completed attendance session without a generated timesheet for {work_date}.", employee=session.employee, work_date=work_date)

    grouped = defaultdict(lambda: {"segments": [], "entries": [], "worked_dates": set()})
    for timesheet in timesheets:
        profile = getattr(timesheet.employee, "payroll_profile", None)
        payroll_timezone = profile.payroll_timezone if profile and profile.payroll_timezone else organization.timezone
        payroll_zone = ZoneInfo(payroll_timezone)
        local_start_date = timesheet.attendance_session.clock_in_at.astimezone(payroll_zone).date()
        local_end_date = timesheet.attendance_session.clock_out_at.astimezone(payroll_zone).date()
        if local_end_date < run.period_start or local_start_date > run.period_end:
            continue
        if timesheet.status != Timesheet.Status.APPROVED:
            _add_exception(
                run,
                code="TIMESHEET_REJECTED" if timesheet.status == Timesheet.Status.REJECTED else f"TIMESHEET_{timesheet.status}",
                description=f"{timesheet.employee.full_name}: timesheet for {local_start_date} is {timesheet.get_status_display().lower()}.",
                employee=timesheet.employee,
                timesheet=timesheet,
                work_date=local_start_date,
            )
            continue
        if not profile or not profile.active_for_payroll:
            _add_exception(run, code="PAY_PROFILE_MISSING", description=f"{timesheet.employee.full_name} needs an active payroll profile.", employee=timesheet.employee, timesheet=timesheet, work_date=local_start_date)
            continue
        if not profile.work_location or not profile.payroll_region or not profile.minimum_wage_confirmed or not profile.wage_order_reference:
            _add_exception(run, code="WORK_LOCATION_MISSING", description=f"Add {timesheet.employee.full_name}'s work location and wage-order reference, then confirm the effective rate was checked against it.", employee=timesheet.employee, timesheet=timesheet, work_date=local_start_date)
            continue
        # Split using the rule version in force for each local work date.
        all_segments = []
        try:
            payroll_start_date = timesheet.attendance_session.clock_in_at.astimezone(payroll_zone).date()
            broad_rule = effective_rule_set(organization, payroll_start_date, employee=timesheet.employee) or PayrollRuleSet.objects.filter(
                organization=organization,
                effective_from__lte=run.period_end,
            ).filter(Q(effective_until__isnull=True) | Q(effective_until__gte=run.period_start)).order_by("-effective_from").first()
            if not broad_rule:
                raise ValidationError("No payroll rule version covers this employee's shift date.")
            all_segments = split_worked_segments(
                timesheet.attendance_session,
                list(timesheet.attendance_session.breaks.all()),
                zone_name=payroll_timezone,
                organization=organization,
                rule_set=broad_rule,
                employee=timesheet.employee,
                period_start=run.period_start,
                period_end=run.period_end,
            )
        except (ValidationError, ValueError) as error:
            _add_exception(run, code="ATTENDANCE_DATA_INVALID", description=f"{timesheet.employee.full_name}: {error}", employee=timesheet.employee, timesheet=timesheet, work_date=local_start_date)
            continue
        if not all_segments:
            continue

        finalized_entries = PayrollTimeEntry.objects.filter(
            timesheet=timesheet,
            statement__run__status=PayrollRun.Status.FINALIZED,
        )
        previously_paid_dates = set()
        for entry in finalized_entries:
            previously_paid_dates.update(entry.snapshot.get("included_work_dates", []))
        available_segments = []
        for segment in all_segments:
            if segment["work_date"].isoformat() in previously_paid_dates:
                _add_exception(run, code="TIME_ALREADY_FINALIZED", description=f"{timesheet.employee.full_name} already has finalized payroll for {segment['work_date']}.", employee=timesheet.employee, timesheet=timesheet, work_date=segment["work_date"])
                continue
            try:
                rule, rule_profile, rule_assignment = resolve_effective_rule(
                    organization, segment["work_date"], employee=timesheet.employee
                )
            except ValidationError as error:
                _add_exception(run, code="PAYROLL_RULE_ASSIGNMENT_CONFLICT", description=f"{timesheet.employee.full_name}: {error}", employee=timesheet.employee, timesheet=timesheet, work_date=segment["work_date"])
                continue
            if not rule or not rule.reviewed:
                code = "PAYROLL_RULE_PROFILE_MISSING" if not rule_profile else "PAYROLL_RULES_NOT_REVIEWED"
                description = (
                    f"Assign a default or employee payroll rule profile covering {segment['work_date']}."
                    if not rule_profile else
                    f"Review the effective payroll rules for {segment['work_date']} before running payroll."
                )
                _add_exception(run, code=code, description=description, employee=timesheet.employee, timesheet=timesheet, work_date=segment["work_date"])
                continue
            rate = effective_pay_rate(timesheet.employee, segment["work_date"])
            if not rate:
                _add_exception(run, code="PAY_RATE_MISSING", description=f"Add an effective hourly rate for {timesheet.employee.full_name} on {segment['work_date']}.", employee=timesheet.employee, timesheet=timesheet, work_date=segment["work_date"])
                continue
            segment["rule"] = rule
            segment["rule_profile"] = rule_profile
            segment["rule_assignment"] = rule_assignment
            segment["rate"] = rate.hourly_rate
            segment["timesheet"] = timesheet
            segment["profile"] = profile
            available_segments.append(segment)
        if available_segments:
            employee_bucket = grouped[timesheet.employee_id]
            employee_bucket["segments"].extend(available_segments)
            employee_bucket["entries"].append((timesheet, available_segments))
            employee_bucket["worked_dates"].update(segment["work_date"] for segment in available_segments)

    if not grouped:
        _add_exception(run, code="NO_PAYROLL_TIME", description="No approved, eligible worked time was found for this period. Review the period before confirming a zero-pay run.")

    for employee_id, bucket in grouped.items():
        employee = Employee.objects.get(pk=employee_id, organization=organization)
        statement = statements_by_employee.get(employee_id)
        if statement is None:
            statement = PayrollStatement.objects.create(run=run, employee=employee)
            statements_by_employee[employee_id] = statement
        by_day = defaultdict(list)
        for segment in bucket["segments"]:
            by_day[segment["work_date"]].append(segment)
        totals = defaultdict(Decimal)
        holiday_versions = {}
        for work_date, day_segments in by_day.items():
            day_segments.sort(key=lambda item: item["start"])
            profile = day_segments[0]["profile"]
            rule = day_segments[0]["rule"]
            rate = day_segments[0]["rate"]
            total_seconds = sum((item["seconds"] for item in day_segments), Decimal("0"))
            ot_seconds_remaining = max(Decimal("0"), total_seconds - Decimal(rule.regular_day_minutes * 60))
            for segment in reversed(day_segments):
                segment["overtime_seconds"] = min(segment["seconds"], ot_seconds_remaining)
                ot_seconds_remaining -= segment["overtime_seconds"]
            rest_day = profile.rest_day == work_date.weekday()
            holiday = PayrollHoliday.objects.filter(organization=organization, date=work_date).first()
            if holiday:
                holiday_versions[work_date.isoformat()] = {
                    "id": holiday.pk,
                    "name": holiday.name,
                    "kind": holiday.kind,
                    "worked_multiplier": str(holiday.worked_multiplier),
                    "overtime_multiplier": str(holiday.overtime_multiplier),
                    "source_reference": holiday.source_reference,
                    "reviewed_by": holiday.reviewed_by,
                    "reviewed_at": holiday.reviewed_at.isoformat() if holiday.reviewed_at else None,
                }
            holiday_not_reviewed = False
            rest_day_holiday_stack = rest_day and holiday is not None
            if rest_day_holiday_stack:
                _add_exception(run, code="HOLIDAY_REST_DAY_STACKING", description=f"Review overlapping holiday and rest-day premiums for {employee.full_name} on {work_date}; add the reviewed premium as a manual earning line.", employee=employee, work_date=work_date)
            if holiday and not holiday.reviewed:
                _add_exception(run, code="HOLIDAY_NOT_REVIEWED", description=f"Add official source/reviewer details for {holiday.name} on {work_date}, or add a reviewed manual premium line.", employee=employee, work_date=work_date)
                holiday_not_reviewed = True
            multiplier = Decimal("1")
            ot_multiplier = rule.overtime_multiplier
            if rest_day and not rest_day_holiday_stack:
                multiplier = rule.rest_day_multiplier
                ot_multiplier = rule.rest_day_overtime_multiplier
            elif holiday and holiday.reviewed and not rest_day_holiday_stack:
                multiplier = holiday.worked_multiplier
                ot_multiplier = holiday.overtime_multiplier
            if (rest_day or holiday) and not rest_day_holiday_stack and not holiday_not_reviewed:
                ordinary_seconds = max(Decimal("0"), total_seconds - sum((item["overtime_seconds"] for item in day_segments), Decimal("0")))
                overtime_seconds = sum((item["overtime_seconds"] for item in day_segments), Decimal("0"))
                totals["premium"] += rate * (
                    ordinary_seconds / HOUR_SECONDS * (multiplier - 1)
                    + overtime_seconds / HOUR_SECONDS * (ot_multiplier - 1)
                )
            else:
                overtime_seconds = sum((item["overtime_seconds"] for item in day_segments), Decimal("0"))
                totals["overtime"] += rate * overtime_seconds / HOUR_SECONDS * (ot_multiplier - 1)
            totals["base"] += rate * total_seconds / HOUR_SECONDS
            for segment in day_segments:
                if segment["night"]:
                    if not profile.night_differential_eligible:
                        _add_exception(run, code="NIGHT_ELIGIBILITY_UNCONFIRMED", description=f"Confirm {employee.full_name}'s eligibility for night shift differential before valuing night work on {work_date}.", employee=employee, timesheet=segment["timesheet"], work_date=work_date)
                    elif rest_day or holiday or segment["overtime_seconds"]:
                        _add_exception(run, code="NIGHT_PREMIUM_STACKING_REVIEW", description=f"Review combined night differential and overtime/holiday premium for {employee.full_name} on {work_date}; add a reviewed manual earning line.", employee=employee, timesheet=segment["timesheet"], work_date=work_date)
                    else:
                        totals["night"] += rate * segment["seconds"] / HOUR_SECONDS * rule.night_differential_rate
            totals["hours"] += total_seconds / HOUR_SECONDS

        rule_versions = {}
        rate_versions = {}
        time_inputs = []
        for timesheet, segments in bucket["entries"]:
            session = timesheet.attendance_session
            for item in segments:
                rule = item["rule"]
                rule_profile = item.get("rule_profile")
                rule_assignment = item.get("rule_assignment")
                rule_versions[str(rule.pk)] = {
                    "profile_id": rule_profile.pk if rule_profile else None,
                    "profile_code": rule_profile.code if rule_profile else None,
                    "profile_name": rule_profile.name if rule_profile else None,
                    "assignment_id": rule_assignment.pk if rule_assignment else None,
                    "assignment_effective_from": rule_assignment.effective_from.isoformat() if rule_assignment else None,
                    "assignment_effective_until": rule_assignment.effective_until.isoformat() if rule_assignment and rule_assignment.effective_until else None,
                    "effective_from": rule.effective_from.isoformat(),
                    "effective_until": rule.effective_until.isoformat() if rule.effective_until else None,
                    "regular_day_minutes": rule.regular_day_minutes,
                    "overtime_multiplier": str(rule.overtime_multiplier),
                    "rest_day_multiplier": str(rule.rest_day_multiplier),
                    "rest_day_overtime_multiplier": str(rule.rest_day_overtime_multiplier),
                    "night_start": rule.night_start.isoformat(),
                    "night_end": rule.night_end.isoformat(),
                    "night_differential_rate": str(rule.night_differential_rate),
                    "source_references": rule.source_references,
                    "reviewed_by": rule.reviewed_by,
                    "reviewed_at": rule.reviewed_at.isoformat() if rule.reviewed_at else None,
                }
                rate = effective_pay_rate(employee, item["work_date"])
                if rate:
                    rate_versions[str(rate.pk)] = {
                        "effective_from": rate.effective_from.isoformat(),
                        "effective_until": rate.effective_until.isoformat() if rate.effective_until else None,
                        "hourly_rate": str(rate.hourly_rate),
                        "change_reason": rate.change_reason,
                    }
            time_inputs.append({
                "timesheet_id": timesheet.pk,
                "status": timesheet.status,
                "source_payable_minutes": timesheet.payable_minutes,
                "attendance": {
                    "clock_in_utc": session.clock_in_at.astimezone(datetime_timezone.utc).isoformat(),
                    "clock_out_utc": session.clock_out_at.astimezone(datetime_timezone.utc).isoformat(),
                    "breaks": [{
                        "start_utc": pause.started_at.astimezone(datetime_timezone.utc).isoformat(),
                        "end_utc": pause.ended_at.astimezone(datetime_timezone.utc).isoformat() if pause.ended_at else None,
                    } for pause in session.breaks.all()],
                },
                "segments": [{
                    "work_date": item["work_date"].isoformat(),
                    "start_utc": item["start"].isoformat(),
                    "end_utc": item["end"].isoformat(),
                    "seconds": str(item["seconds"]),
                    "night": item["night"],
                    "overtime_seconds": str(item.get("overtime_seconds", Decimal("0"))),
                    "hourly_rate": str(item["rate"]),
                    "rule_set_id": item["rule"].pk,
                    "rule_profile_id": item["rule_profile"].pk if item.get("rule_profile") else None,
                    "rule_assignment_id": item["rule_assignment"].pk if item.get("rule_assignment") else None,
                } for item in segments],
            })
        statement.snapshot = {
            "country_code": "PH",
            "currency": run.currency,
            "pay_frequency": run.pay_frequency,
            "timezone": profile.payroll_timezone or organization.timezone,
            "period_start": run.period_start.isoformat(),
            "period_end": run.period_end.isoformat(),
            "time_work_dates": sorted(day.isoformat() for day in bucket["worked_dates"]),
            "employee": {
                "id": employee.pk,
                "code": employee.employee_code,
                "name": employee.full_name,
                "work_location": profile.work_location,
                "timezone": profile.payroll_timezone or organization.timezone,
                "payroll_region": profile.payroll_region,
                "wage_order_reference": profile.wage_order_reference,
                "minimum_wage_confirmed": profile.minimum_wage_confirmed,
                "night_differential_eligible": profile.night_differential_eligible,
                "rest_day": profile.rest_day,
                "rank_and_file": profile.rank_and_file,
            },
            "rule_versions": rule_versions,
            "rate_versions": rate_versions,
            "holiday_versions": holiday_versions,
            "time_inputs": time_inputs,
            "rounding": "Exact attendance seconds are valued with Decimal arithmetic; each line total is rounded to the currency cent using ROUND_HALF_UP. Duration display minutes are floored.",
        }
        statement.save(update_fields=["snapshot", "updated_at"])

        for code, label in (("REGULAR_PAY", "Basic hourly pay"), ("OVERTIME_PREMIUM", "Overtime premium"), ("NIGHT_DIFFERENTIAL", "Night shift differential"), ("DAY_PREMIUM", "Rest-day / holiday premium")):
            amount = _money(totals[{"REGULAR_PAY": "base", "OVERTIME_PREMIUM": "overtime", "NIGHT_DIFFERENTIAL": "night", "DAY_PREMIUM": "premium"}[code]])
            if amount:
                PayrollLine.objects.create(
                    statement=statement,
                    kind=PayrollLine.Kind.EARNING,
                    code=code,
                    label=label,
                    amount=amount,
                    source="CALCULATED",
                    note=f"Computed from approved timesheets and effective-dated rules for {run.period_start}–{run.period_end}.",
                    created_by=actor,
                )

        for timesheet, segments in bucket["entries"]:
            included_dates = sorted({segment["work_date"].isoformat() for segment in segments})
            payable_seconds = sum((segment["seconds"] for segment in segments), Decimal("0"))
            night_seconds = sum((segment["seconds"] for segment in segments if segment["night"]), Decimal("0"))
            ot_seconds = sum((segment.get("overtime_seconds", Decimal("0")) for segment in segments), Decimal("0"))
            PayrollTimeEntry.objects.create(
                statement=statement,
                timesheet=timesheet,
                work_date=segments[0]["work_date"],
                payable_minutes=int(payable_seconds // 60),
                night_minutes=int(night_seconds // 60),
                overtime_minutes=int(ot_seconds // 60),
                rate_snapshot=segments[0]["rate"],
                snapshot={
                    "included_work_dates": included_dates,
                    "segments": [{
                        "date": item["work_date"].isoformat(),
                        "start_utc": item["start"].isoformat(),
                        "end_utc": item["end"].isoformat(),
                        "seconds": str(item["seconds"]),
                        "night": item["night"],
                        "overtime_seconds": str(item.get("overtime_seconds", Decimal("0"))),
                        "hourly_rate": str(item["rate"]),
                        "rule_set_id": item["rule"].pk,
                        "rule_profile_id": item["rule_profile"].pk if item.get("rule_profile") else None,
                        "rule_assignment_id": item["rule_assignment"].pk if item.get("rule_assignment") else None,
                    } for item in segments],
                    "source_payable_minutes": timesheet.payable_minutes,
                    "work_timezone": profile.payroll_timezone or organization.timezone,
                    "rule_profiles": [{
                        "id": item["rule_profile"].pk,
                        "code": item["rule_profile"].code,
                        "name": item["rule_profile"].name,
                        "assignment_id": item["rule_assignment"].pk if item.get("rule_assignment") else None,
                    } for item in segments if item.get("rule_profile")],
                },
            )
        _refresh_statement(statement)

    for statement in statements_by_employee.values():
        if statement.run_id == run.pk:
            _refresh_statement(statement)
    _record_preview(run, actor)
    record_event(organization=organization, actor=actor, action=AuditEvent.Action.PAYROLL_RUN_RECALCULATED, target_type="payroll_run", target_id=run.pk, summary=f"Recorded payroll preview {run.reference}.", metadata={"preview": run.calculation_previews.count()})
    return run


@transaction.atomic
def add_adjustment(*, run, actor, employee, kind, label, amount, effective_date, note):
    organization = _owner_organization(actor, run.organization_id)
    run = PayrollRun.objects.select_for_update().get(pk=run.pk, organization=organization)
    if run.status != PayrollRun.Status.DRAFT:
        raise ValidationError("Adjustments can only be added to a draft payroll run.")
    if employee.organization_id != organization.pk:
        raise ValidationError("Choose an employee in this organization.")
    if kind not in PayrollLine.Kind.values:
        raise ValidationError("Choose a valid adjustment type.")
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError("Adjustment amount must be greater than zero.")
    if effective_date < run.period_start or effective_date > run.period_end:
        raise ValidationError("The adjustment date must fall within this payroll run's period.")
    statement, _ = PayrollStatement.objects.get_or_create(run=run, employee=employee)
    PayrollLine.objects.create(
        statement=statement,
        kind=kind,
        code="MANUAL_ADJUSTMENT",
        label=label.strip()[:120],
        amount=_money(amount),
        effective_date=effective_date,
        source="MANUAL",
        note=note.strip()[:255],
        created_by=actor,
    )
    _refresh_statement(statement)
    _record_preview(run, actor)
    record_event(
        organization=organization,
        actor=actor,
        action=AuditEvent.Action.PAYROLL_ADJUSTMENT_ADDED,
        target_type="payroll_statement",
        target_id=statement.pk,
        summary=f"Added a payroll adjustment for {employee.employee_code}.",
        metadata={"kind": kind, "amount": str(_money(amount)), "run": run.reference},
    )
    return statement


@transaction.atomic
def remove_adjustment(*, run, line_id, actor):
    organization = _owner_organization(actor, run.organization_id)
    run = PayrollRun.objects.select_for_update().get(pk=run.pk, organization=organization)
    if run.status != PayrollRun.Status.DRAFT:
        raise ValidationError("Adjustments can only be removed from a draft payroll run.")
    line = PayrollLine.objects.select_for_update().filter(
        pk=line_id,
        statement__run=run,
        source="MANUAL",
    ).select_related("statement", "statement__employee").first()
    if not line:
        raise ValidationError("Choose a manual adjustment in this payroll run.")
    if line.exception_resolutions.exists():
        raise ValidationError("This adjustment is linked to a resolved exception and must remain in the audit record.")
    statement = line.statement
    removed = {
        "employee_code": statement.employee.employee_code,
        "kind": line.kind,
        "label": line.label,
        "amount": str(line.amount),
        "effective_date": line.effective_date.isoformat() if line.effective_date else None,
        "reason": line.note,
    }
    line.delete()
    _refresh_statement(statement)
    _record_preview(run, actor)
    record_event(
        organization=organization,
        actor=actor,
        action=AuditEvent.Action.PAYROLL_ADJUSTMENT_REMOVED,
        target_type="payroll_statement",
        target_id=statement.pk,
        summary=f"Removed a manual payroll adjustment for {statement.employee.employee_code}.",
        metadata={**removed, "run": run.reference},
    )
    return statement


@transaction.atomic
def submit_for_review(*, run, actor):
    organization = _owner_organization(actor, run.organization_id)
    run = PayrollRun.objects.select_for_update().get(pk=run.pk, organization=organization)
    if run.status != PayrollRun.Status.DRAFT:
        raise ValidationError("Only a draft payroll run can be submitted for review.")
    if run.exceptions.filter(resolved_at__isnull=True, superseded_at__isnull=True).exists():
        raise ValidationError("Resolve all payroll exceptions before submitting this run for review.")
    if run.run_type == PayrollRun.RunType.OFF_CYCLE and not run.statements.exists():
        raise ValidationError("A payroll run needs at least one employee statement.")
    for statement in run.statements.all():
        _assert_statement_reconciles(statement)
    if not PayrollSettings.objects.filter(organization=organization).exists():
        raise ValidationError("Complete payroll settings before submitting a run.")
    run.status = PayrollRun.Status.REVIEW
    run.reviewed_by = actor
    run.reviewed_at = timezone.now()
    run.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
    record_event(organization=organization, actor=actor, action=AuditEvent.Action.PAYROLL_RUN_REVIEWED, target_type="payroll_run", target_id=run.pk, summary=f"Submitted payroll run {run.reference} for review.")
    return run


@transaction.atomic
def finalize_payroll_run(*, run, actor, review_note):
    organization = _owner_organization(actor, run.organization_id)
    run = PayrollRun.objects.select_for_update().get(pk=run.pk, organization=organization)
    if run.status != PayrollRun.Status.REVIEW:
        raise ValidationError("Only a run in review can be finalized.")
    if run.exceptions.filter(resolved_at__isnull=True, superseded_at__isnull=True).exists():
        raise ValidationError("This run has unresolved payroll exceptions.")
    if not review_note.strip():
        raise ValidationError("Record who checked the payroll calculations and the review evidence.")
    if run.run_type == PayrollRun.RunType.OFF_CYCLE and not run.statements.exists():
        raise ValidationError("A payroll run needs at least one employee statement.")
    for statement in run.statements.all():
        _assert_statement_reconciles(statement)
    run.status = PayrollRun.Status.FINALIZED
    run.finalized_by = actor
    run.finalized_at = timezone.now()
    run.review_note = review_note.strip()
    run.save(update_fields=["status", "finalized_by", "finalized_at", "review_note", "updated_at"])
    record_event(organization=organization, actor=actor, action=AuditEvent.Action.PAYROLL_RUN_FINALIZED, target_type="payroll_run", target_id=run.pk, summary=f"Finalized payroll run {run.reference}.", metadata={"statements": run.statements.count(), "review_note": review_note.strip()[:200]})
    return run


@transaction.atomic
def void_payroll_run(*, run, actor, reason):
    organization = _owner_organization(actor, run.organization_id)
    run = PayrollRun.objects.select_for_update().get(pk=run.pk, organization=organization)
    if run.status not in (PayrollRun.Status.DRAFT, PayrollRun.Status.REVIEW):
        raise ValidationError("Only draft or in-review payroll runs can be voided.")
    if not reason.strip():
        raise ValidationError("Add a reason for voiding this payroll run.")
    run.status = PayrollRun.Status.VOID
    run.void_reason = reason.strip()
    run.save(update_fields=["status", "void_reason", "updated_at"])
    record_event(organization=organization, actor=actor, action=AuditEvent.Action.PAYROLL_RUN_VOIDED, target_type="payroll_run", target_id=run.pk, summary=f"Voided payroll run {run.reference}.", metadata={"reason": reason.strip()[:200]})
    return run


def _assert_statement_reconciles(statement):
    totals = defaultdict(Decimal)
    for line in statement.lines.all():
        totals[line.kind] += line.amount
    gross = _money(totals[PayrollLine.Kind.EARNING])
    deductions = _money(totals[PayrollLine.Kind.DEDUCTION])
    contributions = _money(totals[PayrollLine.Kind.EMPLOYER_CONTRIBUTION])
    if (statement.gross_amount, statement.deduction_amount, statement.employer_contribution_amount) != (gross, deductions, contributions):
        raise ValidationError(f"Reconcile the itemized lines for {statement.employee.full_name} before review.")
    if statement.net_amount != _money(gross - deductions):
        raise ValidationError(f"The net amount for {statement.employee.full_name} does not match gross less deductions.")
    if statement.net_amount < 0:
        raise ValidationError(f"Employee deductions exceed gross pay for {statement.employee.full_name}.")


@transaction.atomic
def resolve_payroll_exception(*, exception, actor, note, resolution_line=None):
    organization = _owner_organization(actor, exception.run.organization_id)
    run = PayrollRun.objects.select_for_update().get(pk=exception.run_id, organization=organization)
    if run.status != PayrollRun.Status.DRAFT:
        raise ValidationError("Exceptions can only be reviewed while the payroll run is a draft.")
    exception = PayrollException.objects.select_for_update().get(pk=exception.pk, run=run)
    if exception.resolved_at or exception.superseded_at:
        raise ValidationError("This payroll exception has already been resolved.")
    if not note.strip():
        raise ValidationError("Record how this exception was handled.")
    if exception.needs_manual_pay_line:
        if resolution_line is None:
            raise ValidationError("Add a manual earning line for the affected work date before resolving this exception.")
        if (
            resolution_line.statement.run_id != run.pk
            or resolution_line.statement.employee_id != exception.employee_id
            or resolution_line.kind != PayrollLine.Kind.EARNING
            or resolution_line.source != "MANUAL"
            or resolution_line.effective_date != exception.work_date
        ):
            raise ValidationError("Choose a manual earning line for this employee and work date.")
    elif exception.code not in {"NO_ATTENDANCE", "NO_PAYROLL_TIME", "TIMESHEET_REJECTED"}:
        raise ValidationError("Correct the source record and recalculate the draft to clear this exception.")
    exception.resolved_at = timezone.now()
    exception.resolved_by = actor
    exception.resolution_note = note.strip()[:500]
    exception.resolution_line = resolution_line
    exception.save(update_fields=["resolved_at", "resolved_by", "resolution_note", "resolution_line"])
    _record_preview(run, actor)
    record_event(
        organization=organization,
        actor=actor,
        action=AuditEvent.Action.PAYROLL_EXCEPTION_RESOLVED,
        target_type="payroll_exception",
        target_id=exception.pk,
        summary=f"Resolved a payroll exception for {exception.employee.employee_code if exception.employee_id else run.reference}.",
        metadata={"code": exception.code, "note": exception.resolution_note[:200], "run": run.reference, "resolution_line_id": resolution_line.pk if resolution_line else None},
    )
    return exception
