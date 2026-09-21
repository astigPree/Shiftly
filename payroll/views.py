import csv
import uuid
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.permissions import employee_required, employer_required, organization_for_user
from audit.models import AuditEvent
from audit.services import record_event
from employees.models import Employee

from .forms import (
    EmployeePayProfileForm,
    EmployeePayRateForm,
    FinalizePayrollForm,
    PayrollAdjustmentForm,
    PayrollExceptionResolutionForm,
    PayrollHolidayForm,
    PayrollRuleSetForm,
    PayrollRunForm,
    PayrollSettingsForm,
    VoidPayrollForm,
)
from .models import (
    EmployeePayProfile,
    EmployeePayRate,
    PayrollException,
    PayrollHoliday,
    PayrollLine,
    PayrollRuleSet,
    PayrollRun,
    PayrollSettings,
    PayrollStatement,
)
from .services import (
    add_adjustment,
    calculate_payroll_run,
    create_payroll_run,
    finalize_payroll_run,
    remove_adjustment,
    resolve_payroll_exception,
    submit_for_review,
    void_payroll_run,
)


def _organization(request):
    return organization_for_user(request.user)


def _message_error(request, error):
    if hasattr(error, "message_dict"):
        for errors in error.message_dict.values():
            for message in errors:
                messages.error(request, message)
    else:
        for message in getattr(error, "messages", [str(error)]):
            messages.error(request, message)


def _csv_cell(value):
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _page_querystring(request):
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


def _period_bounds(reference_date, frequency, period):
    """Return the current or previous payroll period for the configured frequency."""
    if frequency == PayrollSettings.Frequency.WEEKLY:
        current_start = reference_date - timedelta(days=reference_date.weekday())
        current_end = current_start + timedelta(days=6)
        if period == "previous":
            current_start -= timedelta(days=7)
            current_end -= timedelta(days=7)
        return current_start, current_end

    month_start = reference_date.replace(day=1)
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if frequency == PayrollSettings.Frequency.MONTHLY:
        if period == "previous":
            previous_end = month_start - timedelta(days=1)
            return previous_end.replace(day=1), previous_end
        return month_start, month_end

    if reference_date.day <= 15:
        current_start, current_end = month_start, reference_date.replace(day=15)
        previous_end = month_start - timedelta(days=1)
        previous_start = previous_end.replace(day=16)
    else:
        current_start, current_end = reference_date.replace(day=16), month_end
        previous_start, previous_end = month_start, reference_date.replace(day=15)
    return (previous_start, previous_end) if period == "previous" else (current_start, current_end)


def _payroll_readiness(organization):
    """Build actionable setup readiness from the same inputs payroll uses to calculate pay."""
    try:
        organization_today = timezone.localdate(timezone=ZoneInfo(organization.timezone))
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        organization_today = timezone.localdate()

    settings_row = PayrollSettings.objects.filter(organization=organization).first()
    effective_rule = PayrollRuleSet.objects.filter(
        organization=organization,
        effective_from__lte=organization_today,
    ).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gte=organization_today)
    ).order_by("-effective_from", "-pk").first()
    settings_complete = bool(settings_row and effective_rule and effective_rule.reviewed)
    if not settings_row:
        settings_detail = "Choose a pay frequency and configure reviewed pay rules."
    elif not effective_rule:
        settings_detail = f"{settings_row.currency} · No rule is effective today"
    elif not effective_rule.reviewed:
        settings_detail = f"{settings_row.currency} · Pay rules need review"
    else:
        settings_detail = f"{settings_row.currency} · Rules reviewed"

    active_employees = Employee.objects.filter(
        organization=organization,
        status=Employee.Status.ACTIVE,
    ).select_related("payroll_profile").prefetch_related("pay_rates")
    active_employee_count = active_employees.count()
    expected_count = 0
    ready_count = 0
    excluded_count = 0
    missing_profile_count = 0
    missing_rate_count = 0
    incomplete_profile_count = 0
    for employee in active_employees:
        profile = getattr(employee, "payroll_profile", None)
        if profile and not profile.active_for_payroll:
            excluded_count += 1
            continue
        expected_count += 1
        if not profile:
            missing_profile_count += 1
            continue

        profile_complete = bool(
            profile.work_location.strip()
            and profile.payroll_region.strip()
            and profile.wage_order_reference.strip()
            and profile.minimum_wage_confirmed
        )
        if not profile_complete:
            incomplete_profile_count += 1

        try:
            employee_zone = ZoneInfo(profile.payroll_timezone or organization.timezone)
            employee_work_date = timezone.localdate(employee_zone)
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            employee_work_date = organization_today
        current_rate = next((
            rate for rate in employee.pay_rates.all()
            if rate.effective_from <= employee_work_date
            and (rate.effective_until is None or rate.effective_until >= employee_work_date)
        ), None)
        if not current_rate:
            missing_rate_count += 1
        if profile_complete and current_rate:
            ready_count += 1

    employee_complete = expected_count > 0 and ready_count == expected_count
    if active_employee_count == 0:
        employee_detail = "No active employees are available to configure."
    elif expected_count == 0:
        employee_detail = f"{excluded_count} active employee(s) excluded · Include at least one employee in payroll"
    else:
        employee_detail = f"{ready_count} of {expected_count} employees configured"
        problems = []
        if missing_profile_count:
            problems.append(f"{missing_profile_count} missing profile(s)")
        if missing_rate_count:
            problems.append(f"{missing_rate_count} missing hourly rate(s)")
        if incomplete_profile_count:
            problems.append(f"{incomplete_profile_count} profile(s) need review")
        if problems:
            employee_detail += " · " + " · ".join(problems)
        if excluded_count:
            employee_detail += f" · {excluded_count} excluded from payroll"

    holidays = list(PayrollHoliday.objects.filter(
        organization=organization,
        date__year=organization_today.year,
    ))
    holiday_count = len(holidays)
    unreviewed_holiday_count = sum(not holiday.reviewed for holiday in holidays)
    holiday_complete = holiday_count > 0 and unreviewed_holiday_count == 0
    if holiday_count == 0:
        holiday_detail = f"No holidays configured for {organization_today.year}"
    elif unreviewed_holiday_count:
        holiday_detail = f"{holiday_count} holidays configured · {unreviewed_holiday_count} need review"
    else:
        holiday_detail = f"{holiday_count} holidays configured"

    items = [
        {
            "title": "Payroll settings",
            "description": "Set your pay frequency and review effective pay rules.",
            "detail": settings_detail,
            "complete": settings_complete,
            "url_name": "payroll:setup",
        },
        {
            "title": "Employee pay profiles",
            "description": "Add work locations, wage checks, and effective hourly rates.",
            "detail": employee_detail,
            "complete": employee_complete,
            "url_name": "payroll:employee_list",
        },
        {
            "title": "Holiday calendar",
            "description": "Configure reviewed regular and special holidays for this year.",
            "detail": holiday_detail,
            "complete": holiday_complete,
            "url_name": "payroll:holiday_calendar",
        },
    ]
    complete_count = sum(item["complete"] for item in items)
    next_item = next((item for item in items if not item["complete"]), None)
    return {
        "items": items,
        "complete_count": complete_count,
        "total_count": len(items),
        "progress_percent": round(complete_count * 100 / len(items)),
        "can_create_run": complete_count == len(items),
        "next_setup_url": next_item["url_name"] if next_item else "payroll:setup",
        "settings_complete": settings_complete,
        "employees_complete": employee_complete,
        "holidays_complete": holiday_complete,
        "holiday_count": holiday_count,
        "ready_employee_count": ready_count,
        "expected_employee_count": expected_count,
        "excluded_employee_count": excluded_count,
        "frequency": settings_row.frequency if settings_row else PayrollSettings.Frequency.SEMI_MONTHLY,
        "organization_today": organization_today,
    }


def _period_shortcut_url(request, period):
    params = request.GET.copy()
    params.pop("page", None)
    params.pop("from", None)
    params.pop("to", None)
    params["period"] = period
    return f"?{params.urlencode()}"


@employer_required
@require_GET
def run_list(request):
    organization = _organization(request)
    readiness = _payroll_readiness(organization)
    matching_runs = PayrollRun.objects.filter(organization=organization)
    status = request.GET.get("status", "")
    if status not in PayrollRun.Status.values:
        status = ""
    selected_period = request.GET.get("period", "")
    if selected_period in ("current", "previous"):
        from_date, to_date = _period_bounds(
            readiness["organization_today"], readiness["frequency"], selected_period
        )
        from_date_raw, to_date_raw = from_date.isoformat(), to_date.isoformat()
    else:
        selected_period = ""
        from_date_raw = request.GET.get("from", "").strip()
        to_date_raw = request.GET.get("to", "").strip()
        from_date = parse_date(from_date_raw) if from_date_raw else None
        to_date = parse_date(to_date_raw) if to_date_raw else None
        from_date_raw = from_date.isoformat() if from_date else ""
        to_date_raw = to_date.isoformat() if to_date else ""
    if from_date:
        matching_runs = matching_runs.filter(period_end__gte=from_date)
    if to_date:
        matching_runs = matching_runs.filter(period_start__lte=to_date)
    employee_id = request.GET.get("employee", "")
    if employee_id.isdigit() and Employee.objects.filter(pk=employee_id, organization=organization).exists():
        matching_runs = matching_runs.filter(statements__employee_id=employee_id).distinct()
    else:
        employee_id = ""

    summary_status_counts = {
        row["status"]: row["count"]
        for row in matching_runs.values("status").annotate(count=Count("pk", distinct=True))
    }
    finalized_runs = matching_runs.filter(status=PayrollRun.Status.FINALIZED).values("pk")
    finalized_net = PayrollStatement.objects.filter(run_id__in=finalized_runs).aggregate(
        total=Sum("net_amount")
    )["total"] or Decimal("0.00")
    runs = matching_runs.filter(status=status) if status else matching_runs
    page = Paginator(runs, 20).get_page(request.GET.get("page"))
    run_ids = [run.pk for run in page.object_list]
    summary_by_run = {
        row["run_id"]: row for row in PayrollStatement.objects.filter(run_id__in=run_ids)
        .values("run_id").annotate(employee_count=Count("pk"), gross=Sum("gross_amount"), net=Sum("net_amount"))
    }
    exception_counts = dict(
        PayrollException.objects.filter(run_id__in=run_ids, resolved_at__isnull=True, superseded_at__isnull=True)
        .values_list("run_id").annotate(count=Count("pk"))
    )
    for run in page.object_list:
        summary = summary_by_run.get(run.pk, {})
        run.employee_count = summary.get("employee_count", 0)
        run.gross_total = summary.get("gross") or Decimal("0.00")
        run.net_total = summary.get("net") or Decimal("0.00")
        run.unresolved_count = exception_counts.get(run.pk, 0)
    has_any_runs = PayrollRun.objects.filter(organization=organization).exists()
    return render(request, "payroll/run_list.html", {
        "organization": organization,
        "page": page,
        "payroll_readiness": readiness,
        "has_any_runs": has_any_runs,
        "summary_status_counts": summary_status_counts,
        "finalized_net": finalized_net,
        "summary_run_count": sum(summary_status_counts.values()),
        "summary_scope": "Matching date and employee filters" if from_date or to_date or employee_id else "Across all payroll runs",
        "current_period_url": _period_shortcut_url(request, "current"),
        "previous_period_url": _period_shortcut_url(request, "previous"),
        "selected_period": selected_period,
        "results_start": page.start_index() if page.object_list else 0,
        "results_end": page.end_index() if page.object_list else 0,
        "selected_status": status,
        "status_choices": PayrollRun.Status.choices,
        "page_querystring": _page_querystring(request),
        "from_date": from_date_raw if from_date else "",
        "to_date": to_date_raw if to_date else "",
        "employee_id": employee_id,
        "employees": Employee.objects.filter(organization=organization).order_by("last_name", "first_name"),
    })


@employer_required
@require_GET
def employee_payroll_list(request):
    organization = _organization(request)
    employees = Employee.objects.filter(organization=organization).select_related("payroll_profile").prefetch_related("pay_rates")
    query = request.GET.get("q", "").strip()
    if query:
        employees = employees.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(employee_code__icontains=query)
            | Q(email__icontains=query)
        )
    page = Paginator(employees.order_by("last_name", "first_name", "pk"), 30).get_page(request.GET.get("page"))
    rows = []
    for employee in page.object_list:
        profile = getattr(employee, "payroll_profile", None)
        employee_zone = ZoneInfo(profile.payroll_timezone or organization.timezone) if profile else ZoneInfo(organization.timezone)
        work_date = timezone.localdate(timezone=employee_zone)
        rate = next((item for item in employee.pay_rates.all() if item.effective_from <= work_date and (item.effective_until is None or item.effective_until >= work_date)), None)
        rows.append({"employee": employee, "profile": profile, "rate": rate})
    return render(request, "payroll/employee_list.html", {
        "organization": organization,
        "rows": rows,
        "page": page,
        "query": query,
        "page_querystring": _page_querystring(request),
        "currency": PayrollSettings.objects.filter(organization=organization).values_list("currency", flat=True).first() or "PHP",
    })


@employer_required
@require_http_methods(["GET", "POST"])
def setup(request):
    organization = _organization(request)
    settings_row = PayrollSettings.objects.filter(organization=organization).first()
    if settings_row is None:
        settings_row = PayrollSettings(organization=organization)
    latest_rule = PayrollRuleSet.objects.filter(organization=organization).order_by("-effective_from").first()
    add_version = request.GET.get("new_rules") == "1" or bool(latest_rule and latest_rule.reviewed)
    rule_instance = latest_rule if latest_rule and not add_version else PayrollRuleSet(
        organization=organization,
        created_by=request.user,
        effective_from=timezone.localdate(timezone=ZoneInfo("Asia/Manila")) + timedelta(days=1 if latest_rule else 0),
        source_references=(
            "DOLE Labor Code, Book III: https://dole.gov.ph/book-3-conditions-of-employment/\n"
            "Confirm applicable work location, employee coverage, and current rules with a qualified payroll adviser before use."
        ),
    )
    action = request.POST.get("action") if request.method == "POST" else ""
    settings_form = PayrollSettingsForm(
        request.POST if action == "settings" else None,
        instance=settings_row,
        prefix="settings",
    )
    rule_form = PayrollRuleSetForm(
        request.POST if action == "rules" else None,
        instance=rule_instance,
        organization=organization,
        prefix="rules",
    )
    if action == "settings" and request.method == "POST" and settings_form.is_valid():
        settings_form.save()
        record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_RULES_UPDATED, target_type="payroll_settings", target_id=settings_row.pk, summary="Updated payroll currency and frequency.", metadata={"currency": settings_row.currency, "frequency": settings_row.frequency})
        messages.success(request, "Payroll settings saved.")
        return redirect("payroll:setup")
    if action == "rules" and request.method == "POST" and rule_form.is_valid():
        try:
            with transaction.atomic():
                new_rule = rule_form.save(commit=False, actor=request.user)
                new_rule.created_by = request.user
                new_rule.organization = organization
                if new_rule.pk is None:
                    if PayrollRun.objects.filter(
                        organization=organization,
                        status=PayrollRun.Status.FINALIZED,
                        period_end__gte=new_rule.effective_from,
                    ).exists():
                        raise ValidationError({"effective_from": "This effective date could change inputs for finalized payroll. Use an off-cycle adjustment for a correction."})
                    if latest_rule and latest_rule.effective_until is None:
                        if new_rule.effective_from <= latest_rule.effective_from:
                            raise ValidationError({"effective_from": "A new rule version must start after the current version."})
                        latest_rule.effective_until = new_rule.effective_from - timedelta(days=1)
                        latest_rule.save(update_fields=["effective_until"])
                new_rule.full_clean()
                new_rule.save()
            record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_RULES_UPDATED, target_type="payroll_rule_set", target_id=new_rule.pk, summary=f"Added payroll rules effective {new_rule.effective_from}.", metadata={"effective_from": new_rule.effective_from.isoformat(), "reviewed": new_rule.reviewed})
            messages.success(request, "Payroll rule version saved. A run cannot be finalized until the effective rules have review evidence.")
            return redirect("payroll:setup")
        except ValidationError as error:
            _message_error(request, error)
    return render(request, "payroll/setup.html", {
        "organization": organization,
        "settings_form": settings_form,
        "rule_form": rule_form,
        "rule_history": PayrollRuleSet.objects.filter(organization=organization),
        "settings": settings_row,
    })


@employer_required
@require_http_methods(["GET", "POST"])
def employee_profile(request, pk):
    organization = _organization(request)
    employee = get_object_or_404(Employee, pk=pk, organization=organization)
    profile = EmployeePayProfile.objects.filter(employee=employee).first()
    if profile is None:
        preferred_timezone = employee.user.preferred_timezone if employee.user_id else ""
        profile = EmployeePayProfile(
            employee=employee,
            payroll_timezone=preferred_timezone or organization.timezone,
        )
    form = EmployeePayProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_PROFILE_UPDATED, target_type="employee_pay_profile", target_id=profile.pk, summary=f"Updated payroll profile for {employee.employee_code}.", metadata={"region": profile.payroll_region, "timezone": profile.payroll_timezone, "minimum_wage_confirmed": profile.minimum_wage_confirmed})
        messages.success(request, "Employee payroll profile saved.")
        return redirect("payroll:employee_profile", pk=employee.pk)
    return render(request, "payroll/employee_profile.html", {
        "organization": organization,
        "employee": employee,
        "profile": profile,
        "form": form,
        "rates": employee.pay_rates.all(),
    })


@employer_required
@require_http_methods(["GET", "POST"])
def add_pay_rate(request, pk):
    organization = _organization(request)
    employee = get_object_or_404(Employee, pk=pk, organization=organization)
    form = EmployeePayRateForm(request.POST or None, employee=employee, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                rate = form.save(commit=False)
                if PayrollRun.objects.filter(
                    organization=organization,
                    status=PayrollRun.Status.FINALIZED,
                    statements__employee=employee,
                    period_end__gte=rate.effective_from,
                ).exists():
                    raise ValidationError("This effective date could change a finalized payroll period. Create an adjustment run instead.")
                prior = EmployeePayRate.objects.select_for_update().filter(
                    employee=employee,
                    effective_from__lt=rate.effective_from,
                    effective_until__isnull=True,
                ).order_by("-effective_from").first()
                if prior:
                    prior.effective_until = rate.effective_from - timedelta(days=1)
                    prior.save(update_fields=["effective_until"])
                rate.full_clean()
                rate.save()
            record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_RATE_ADDED, target_type="employee_pay_rate", target_id=rate.pk, summary=f"Added an effective hourly rate for {employee.employee_code}.", metadata={"effective_from": rate.effective_from.isoformat(), "currency": PayrollSettings.objects.filter(organization=organization).values_list("currency", flat=True).first() or "PHP"})
            messages.success(request, "Hourly rate added to the employee's pay history.")
            return redirect("payroll:employee_profile", pk=employee.pk)
        except ValidationError as error:
            _message_error(request, error)
    return render(request, "payroll/pay_rate_form.html", {"organization": organization, "employee": employee, "form": form})


@employer_required
@require_http_methods(["GET", "POST"])
def holiday_calendar(request):
    organization = _organization(request)
    form = PayrollHolidayForm(request.POST or None, organization=organization, actor=request.user)
    if request.method == "POST" and form.is_valid():
        holiday_date = form.cleaned_data["date"]
        if PayrollRun.objects.filter(
            organization=organization,
            status=PayrollRun.Status.FINALIZED,
            period_start__lte=holiday_date,
            period_end__gte=holiday_date,
        ).exists():
            messages.error(request, "This date is part of finalized payroll. Use a linked off-cycle adjustment if its amount needs correction.")
            return redirect("payroll:holiday_calendar")
        holiday = form.save()
        record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_RULES_UPDATED, target_type="payroll_holiday", target_id=holiday.pk, summary=f"Added {holiday.name} to the payroll calendar.", metadata={"date": holiday.date.isoformat(), "kind": holiday.kind, "reviewed": holiday.reviewed})
        messages.success(request, "Holiday saved. Payroll blocks finalization if the holiday's source and review details are missing.")
        return redirect("payroll:holiday_calendar")
    return render(request, "payroll/holiday_calendar.html", {
        "organization": organization,
        "form": form,
        "holidays": PayrollHoliday.objects.filter(organization=organization),
    })


@employer_required
@require_http_methods(["GET", "POST"])
def holiday_edit(request, pk):
    organization = _organization(request)
    holiday = get_object_or_404(PayrollHoliday, pk=pk, organization=organization)
    if PayrollRun.objects.filter(
        organization=organization,
        status=PayrollRun.Status.FINALIZED,
        period_start__lte=holiday.date,
        period_end__gte=holiday.date,
    ).exists():
        messages.error(request, "This holiday date is part of finalized payroll and cannot be changed. Use an off-cycle correction if the finalized amount needs adjustment.")
        return redirect("payroll:holiday_calendar")
    form = PayrollHolidayForm(request.POST or None, instance=holiday, organization=organization, actor=request.user)
    if request.method == "POST" and form.is_valid():
        proposed_date = form.cleaned_data["date"]
        if PayrollRun.objects.filter(
            organization=organization,
            status=PayrollRun.Status.FINALIZED,
            period_start__lte=proposed_date,
            period_end__gte=proposed_date,
        ).exists():
            messages.error(request, "The updated holiday date is part of finalized payroll and cannot be changed.")
            return redirect("payroll:holiday_calendar")
        original_date = holiday.date
        holiday = form.save()
        record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_RULES_UPDATED, target_type="payroll_holiday", target_id=holiday.pk, summary=f"Updated {holiday.name} in the payroll calendar.", metadata={"original_date": original_date.isoformat(), "date": holiday.date.isoformat(), "kind": holiday.kind, "reviewed": holiday.reviewed})
        messages.success(request, "Holiday updated. Recalculate any affected draft payroll previews.")
        return redirect("payroll:holiday_calendar")
    return render(request, "payroll/holiday_edit.html", {"organization": organization, "holiday": holiday, "form": form})


@employer_required
@require_GET
def run_create(request):
    organization = _organization(request)
    form = PayrollRunForm(organization=organization, initial={"run_type": PayrollRun.RunType.REGULAR, "request_key": uuid.uuid4()})
    return render(request, "payroll/run_form.html", {
        "organization": organization,
        "form": form,
        "payroll_readiness": _payroll_readiness(organization),
    })


@employer_required
@require_POST
def run_create_submit(request):
    organization = _organization(request)
    form = PayrollRunForm(request.POST, organization=organization)
    if form.is_valid():
        try:
            run = create_payroll_run(
                organization=organization,
                actor=request.user,
                period_start=form.cleaned_data["period_start"],
                period_end=form.cleaned_data["period_end"],
                pay_date=form.cleaned_data["pay_date"],
                run_type=form.cleaned_data["run_type"],
                parent_run=form.cleaned_data["parent_run"],
                idempotency_key=form.cleaned_data["request_key"],
            )
            messages.success(request, "Payroll draft created. Review exceptions and add any itemized manual adjustments.")
            return redirect("payroll:run_detail", pk=run.pk)
        except ValidationError as error:
            _message_error(request, error)
    return render(request, "payroll/run_form.html", {
        "organization": organization,
        "form": form,
        "payroll_readiness": _payroll_readiness(organization),
    })


@employer_required
@require_http_methods(["GET", "POST"])
def run_detail(request, pk):
    organization = _organization(request)
    run = get_object_or_404(PayrollRun.objects.filter(organization=organization), pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "recalculate":
                calculate_payroll_run(run, actor=request.user)
                messages.success(request, "Payroll preview recalculated from the current approved timesheets and rules.")
            elif action == "adjustment":
                form = PayrollAdjustmentForm(request.POST, organization=organization)
                if form.is_valid():
                    add_adjustment(run=run, actor=request.user, **form.cleaned_data)
                    messages.success(request, "Payroll line added to the draft.")
                else:
                    for errors in form.errors.values():
                        for error in errors:
                            messages.error(request, error)
            elif action == "submit_review":
                submit_for_review(run=run, actor=request.user)
                messages.success(request, "Payroll run submitted for review.")
            elif action == "finalize":
                form = FinalizePayrollForm(request.POST)
                if form.is_valid():
                    finalize_payroll_run(run=run, actor=request.user, **form.cleaned_data)
                    messages.success(request, "Payroll run finalized. Employee payslips are now available.")
                else:
                    messages.error(request, "Add review evidence before finalizing this payroll run.")
            elif action == "void":
                form = VoidPayrollForm(request.POST)
                if form.is_valid():
                    void_payroll_run(run=run, actor=request.user, **form.cleaned_data)
                    messages.success(request, "Payroll run voided and retained in history.")
                else:
                    messages.error(request, "Add a reason before voiding this payroll run.")
            elif action == "resolve_exception":
                exception = get_object_or_404(PayrollException, pk=request.POST.get("exception_id"), run=run)
                form = PayrollExceptionResolutionForm(
                    request.POST,
                    run=run,
                    exception=exception,
                    prefix=f"exception-{exception.pk}",
                )
                if form.is_valid():
                    resolve_payroll_exception(
                        exception=exception,
                        actor=request.user,
                        note=form.cleaned_data["resolution_note"],
                        resolution_line=form.cleaned_data["resolution_line"],
                    )
                    messages.success(request, "Exception review recorded with its resolution evidence.")
                else:
                    for errors in form.errors.values():
                        for error in errors:
                            messages.error(request, error)
            elif action == "remove_line":
                remove_adjustment(run=run, line_id=request.POST.get("line_id"), actor=request.user)
                messages.success(request, "Manual payroll line removed.")
            else:
                messages.error(request, "Choose a valid payroll action.")
        except ValidationError as error:
            _message_error(request, error)
        return redirect("payroll:run_detail", pk=run.pk)

    statement_query = run.statements.select_related("employee").prefetch_related("lines", "time_entries")
    statement_page = Paginator(statement_query, 30).get_page(request.GET.get("page"))
    exceptions = list(run.exceptions.select_related("employee", "timesheet", "resolution_line").order_by("superseded_at", "resolved_at", "employee__last_name", "pk"))
    exception_rows = [{
        "exception": item,
        "form": PayrollExceptionResolutionForm(run=run, exception=item, prefix=f"exception-{item.pk}"),
    } for item in exceptions if not item.resolved_at and not item.superseded_at]
    adjustment_form = PayrollAdjustmentForm(organization=organization, initial={"effective_date": run.period_start})
    totals = run.statements.aggregate(
        gross=Sum("gross_amount"), deductions=Sum("deduction_amount"),
        contributions=Sum("employer_contribution_amount"), net=Sum("net_amount"),
    )
    return render(request, "payroll/run_detail.html", {
        "organization": organization,
        "run": run,
        "statements": statement_page,
        "exceptions": exceptions,
        "exception_rows": exception_rows,
        "unresolved_exception_count": sum(1 for item in exceptions if not item.resolved_at and not item.superseded_at),
        "preview_history": run.calculation_previews.all()[:5],
        "adjustment_form": adjustment_form,
        "finalize_form": FinalizePayrollForm(),
        "void_form": VoidPayrollForm(),
        "totals": {key: value or Decimal("0.00") for key, value in totals.items()},
    })


@employer_required
@require_GET
def run_export(request, pk):
    organization = _organization(request)
    run = get_object_or_404(PayrollRun.objects.filter(organization=organization), pk=pk)
    if run.status != PayrollRun.Status.FINALIZED:
        messages.error(request, "Only finalized payroll can be exported.")
        return redirect("payroll:run_detail", pk=run.pk)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{run.reference.lower()}-payroll.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Employee code", "Employee", "Period start", "Period end", "Pay date", "Pay frequency", "Currency", "Basic pay", "Overtime premium", "Night differential", "Other earnings", "Employee deductions", "Employer contributions", "Gross pay", "Net pay"])
    for statement in run.statements.select_related("employee").prefetch_related("lines"):
        grouped = {kind: Decimal("0.00") for kind in PayrollLine.Kind.values}
        for line in statement.lines.all():
            grouped[line.kind] += line.amount
        basic = sum((line.amount for line in statement.lines.all() if line.code == "REGULAR_PAY"), Decimal("0.00"))
        overtime = sum((line.amount for line in statement.lines.all() if line.code == "OVERTIME_PREMIUM"), Decimal("0.00"))
        night = sum((line.amount for line in statement.lines.all() if line.code == "NIGHT_DIFFERENTIAL"), Decimal("0.00"))
        writer.writerow([
            _csv_cell(statement.employee.employee_code), _csv_cell(statement.employee.full_name),
            run.period_start.isoformat(), run.period_end.isoformat(), run.pay_date.isoformat(), run.get_pay_frequency_display(), run.currency,
            f"{basic:.2f}", f"{overtime:.2f}", f"{night:.2f}",
            f"{grouped[PayrollLine.Kind.EARNING] - basic - overtime - night:.2f}",
            f"{statement.deduction_amount:.2f}", f"{statement.employer_contribution_amount:.2f}",
            f"{statement.gross_amount:.2f}", f"{statement.net_amount:.2f}",
        ])
    record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_EXPORT_ACCESSED, target_type="payroll_run", target_id=run.pk, summary=f"Exported finalized payroll run {run.reference}.", metadata={"statement_count": run.statements.count(), "format": "csv"})
    return response


@employee_required
@require_GET
def my_statements(request):
    employee = request.user.employee_profile
    statements = PayrollStatement.objects.filter(
        employee=employee,
        run__organization=employee.organization,
        run__status=PayrollRun.Status.FINALIZED,
    ).select_related("run").order_by("-run__pay_date", "-pk")
    page = Paginator(statements, 20).get_page(request.GET.get("page"))
    record_event(organization=employee.organization, actor=request.user, action=AuditEvent.Action.PAYROLL_STATEMENT_ACCESSED, target_type="payroll_history", target_id=employee.pk, summary="Viewed employee payroll history.", metadata={"page": page.number})
    return render(request, "payroll/my_statements.html", {"organization": employee.organization, "page": page})


@employee_required
@require_GET
def my_statement_detail(request, pk):
    employee = request.user.employee_profile
    statement = get_object_or_404(
        PayrollStatement.objects.select_related("run", "employee").prefetch_related("lines", "time_entries"),
        pk=pk,
        employee=employee,
        run__organization=employee.organization,
        run__status=PayrollRun.Status.FINALIZED,
    )
    record_event(organization=employee.organization, actor=request.user, action=AuditEvent.Action.PAYROLL_STATEMENT_ACCESSED, target_type="payroll_statement", target_id=statement.pk, summary=f"Viewed finalized payslip for {statement.run.reference}.")
    return render(request, "payroll/statement.html", {"organization": employee.organization, "statement": statement, "printable": True})
