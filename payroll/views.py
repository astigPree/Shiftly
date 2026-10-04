import csv
import uuid
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, DateField, Exists, OuterRef, Q, Subquery, Sum, Value, When
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.permissions import employee_required, employer_required, organization_for_user
from audit.models import AuditEvent
from audit.services import record_event
from employees.models import Employee
from .statutory import AGENCIES, record_statutory_review, statutory_review_rows

from .forms import (
    EmployeeCompensationForm,
    EmployeeComponentAssignmentForm,
    EmployeePayProfileForm,
    EmployeePayRateForm,
    FinalizePayrollForm,
    PayrollAdjustmentForm,
    PayrollComponentDefinitionForm,
    PayrollExceptionResolutionForm,
    PayrollBulkRuleAssignmentForm,
    PayrollHolidayForm,
    PayrollRuleAssignmentForm,
    PayrollRuleProfileForm,
    PayrollRuleSetForm,
    PayrollRunForm,
    PayrollStatutoryBulkReviewForm,
    PayrollSettingsForm,
    PayrollPeriodInputForm,
    StatutoryReviewForm,
    VoidPayrollForm,
)
from .models import (
    EmployeeCompensationVersion,
    EmployeeComponentAssignment,
    EmployeePayProfile,
    EmployeePayRate,
    PayrollException,
    PayrollComponentDefinition,
    PayrollHoliday,
    PayrollLine,
    PayrollRuleAssignment,
    PayrollRuleProfile,
    PayrollRuleSet,
    PayrollRun,
    PayrollSettings,
    PayrollStatement,
    PayrollStatutoryAssessment,
    PayrollPeriodInput,
)
from .services import (
    add_adjustment,
    calculate_payroll_run,
    create_payroll_run,
    effective_compensation,
    finalize_payroll_run,
    remove_adjustment,
    resolve_payroll_exception,
    submit_for_review,
    return_payroll_to_draft,
    void_payroll_run,
)
from .statutory_assessments import (
    bulk_review_statutory_assessments,
    generate_statutory_assessments,
)
from timesheets.models import Timesheet


def _organization(request):
    return organization_for_user(request.user)


def _message_error(request, error, form=None):
    """Expose validation failures in the page message area and, when possible, on the form."""
    message_dict = getattr(error, "message_dict", None)
    if message_dict:
        for field_name, errors in message_dict.items():
            for message in errors:
                if form is not None:
                    form.add_error(field_name if field_name in form.fields else None, message)
                messages.error(request, message)
        return

    error_messages = getattr(error, "messages", None) or [str(error)]
    for message in error_messages:
        if message:
            if form is not None:
                form.add_error(None, message)
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


def _statutory_assessment_queryset(run):
    return PayrollStatutoryAssessment.objects.filter(
        statement__run=run,
    ).select_related(
        "statement__employee", "employee_line", "employer_line", "reviewed_by",
    )


def _statutory_workspace_context(run, request, *, form=None):
    """Build the paginated bulk workspace without loading every row into a template."""
    assessments = _statutory_assessment_queryset(run).order_by(
        "statement__employee__last_name", "statement__employee__first_name", "agency", "pk"
    )
    search = request.GET.get("stat_q", "").strip() if request.method == "GET" else request.POST.get("stat_q", "").strip()
    agency = request.GET.get("stat_agency", "").strip() if request.method == "GET" else request.POST.get("stat_agency", "").strip()
    status = request.GET.get("stat_status", "").strip() if request.method == "GET" else request.POST.get("stat_status", "").strip()
    source = request.GET.get("stat_source", "").strip() if request.method == "GET" else request.POST.get("stat_source", "").strip()
    if search:
        assessments = assessments.filter(
            Q(statement__employee__first_name__icontains=search)
            | Q(statement__employee__last_name__icontains=search)
            | Q(statement__employee__employee_code__icontains=search)
        )
    if agency:
        assessments = assessments.filter(agency=agency)
    if status:
        assessments = assessments.filter(status=status)
    if source:
        assessments = assessments.filter(source_type=source)
    all_assessments = _statutory_assessment_queryset(run)
    counts = {
        "total": all_assessments.count(),
        "ready": all_assessments.filter(status=PayrollStatutoryAssessment.Status.READY).count(),
        "attention": all_assessments.filter(status__in=[PayrollStatutoryAssessment.Status.NEEDS_REVIEW, PayrollStatutoryAssessment.Status.SUPERSEDED]).count(),
        "reviewed": all_assessments.filter(status=PayrollStatutoryAssessment.Status.REVIEWED).count(),
        "proposed": all_assessments.filter(status=PayrollStatutoryAssessment.Status.PROPOSED).count(),
    }
    page_size = request.GET.get("stat_page_size", "25") if request.method == "GET" else request.POST.get("stat_page_size", "25")
    if page_size not in {"25", "50", "100"}:
        page_size = "25"
    page = Paginator(assessments, int(page_size)).get_page(
        request.GET.get("stat_page") if request.method == "GET" else request.POST.get("stat_page")
    )
    return {
        "statutory_assessment_page": page,
        "statutory_assessment_filters": {"q": search, "agency": agency, "status": status, "source": source},
        "statutory_assessment_counts": counts,
        "statutory_assessment_page_size": page_size,
        "statutory_bulk_form": form or PayrollStatutoryBulkReviewForm(),
        "statutory_assessment_count": counts["total"],
        "statutory_agencies": AGENCIES,
        "statutory_assessment_statuses": PayrollStatutoryAssessment.Status.choices,
        "statutory_assessment_sources": PayrollStatutoryAssessment.SourceType.choices,
    }


def _ensure_default_rule_profile(organization, actor):
    profile = PayrollRuleProfile.objects.filter(organization=organization, is_default=True).first()
    if profile:
        return profile
    return PayrollRuleProfile.objects.create(
        organization=organization,
        code="default",
        name="Organization default",
        description="Default payroll rules inherited by employees without an override.",
        is_default=True,
        active=True,
        created_by=actor,
    )


def _statement_rule_profile_summary(statement):
    versions = (statement.snapshot or {}).get("rule_versions", {}).values()
    summaries = []
    seen = set()
    for version in versions:
        name = version.get("profile_name") or "Legacy organization rules"
        assignment_id = version.get("assignment_id")
        label = f"{name} (employee override)" if assignment_id else f"{name} (inherited)"
        if label not in seen:
            seen.add(label)
            summaries.append(label)
    return ", ".join(summaries) or "No resolved rule profile recorded"


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


def _organization_local_date(organization):
    try:
        return timezone.localdate(timezone=ZoneInfo(organization.timezone))
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        return timezone.localdate()


def _run_form_context(organization, form, payroll_readiness):
    """Build the reviewable, server-rendered data used by the create-run preflight."""
    organization_today = _organization_local_date(organization)
    settings_row = PayrollSettings.objects.filter(organization=organization).first()
    frequency = settings_row.frequency if settings_row else PayrollSettings.Frequency.SEMI_MONTHLY
    preview_start, preview_end = _period_bounds(organization_today, frequency, "previous")
    preview_pay_date = preview_end + timedelta(days=5)

    employees = form.fields["employees"].queryset.select_related("payroll_profile")
    employee_options = []
    for employee in employees:
        profile = getattr(employee, "payroll_profile", None)
        compensation = effective_compensation(employee, organization_today)
        warnings = []
        if not profile or not profile.work_location.strip() or not profile.payroll_region.strip():
            warnings.append("Work details incomplete")
        if not profile or not profile.wage_order_reference.strip() or not profile.minimum_wage_confirmed:
            warnings.append("Wage review required")
        if not compensation:
            warnings.append("Compensation missing")
        basis = compensation["basis"] if compensation else (profile.pay_basis if profile else "")
        amount = compensation["amount"] if compensation else None
        if basis == EmployeeCompensationVersion.Basis.MONTHLY:
            warnings.append("Monthly calculation is not configured")
        employee_options.append({
            "employee": employee,
            "basis": basis,
            "amount": amount,
            "warnings": warnings,
            "status": "needs-review" if warnings else "ready",
            "status_label": "Needs attention" if warnings else "Ready",
        })

    timesheet_scope = Timesheet.objects.filter(
        organization=organization,
        employee__status=Employee.Status.ACTIVE,
        shift__work_date__range=(preview_start, preview_end),
    )
    approved_timesheets = timesheet_scope.filter(status=Timesheet.Status.APPROVED).count()
    timesheets_needing_review = timesheet_scope.exclude(status=Timesheet.Status.APPROVED).count()
    timesheet_counts = {
        row["employee_id"]: row
        for row in timesheet_scope.values("employee_id").annotate(
            approved=Count("id", filter=Q(status=Timesheet.Status.APPROVED)),
            needs_review=Count("id", filter=~Q(status=Timesheet.Status.APPROVED)),
        )
    }
    for option in employee_options:
        counts = timesheet_counts.get(option["employee"].pk, {})
        option["approved_timesheets"] = counts.get("approved", 0)
        option["timesheets_needing_review"] = counts.get("needs_review", 0)
    period_input_count = PayrollPeriodInput.objects.filter(
        organization=organization,
        period_start=preview_start,
        period_end=preview_end,
        reviewed_at__isnull=False,
    ).count()
    selected_employee_ids = {
        str(value) for value in (form["employees"].value() or [])
    }
    for option in employee_options:
        option["selected"] = str(option["employee"].pk) in selected_employee_ids
    return {
        "payroll_readiness": payroll_readiness,
        "payroll_frequency_label": settings_row.get_frequency_display() if settings_row else "Semi-monthly",
        "payroll_frequency": frequency,
        "payroll_currency": settings_row.currency if settings_row else "PHP",
        "eligible_employee_count": len(employee_options),
        "preview_start": preview_start,
        "preview_end": preview_end,
        "preview_pay_date": preview_pay_date,
        "preview_approved_timesheets": approved_timesheets,
        "preview_timesheets_needing_review": timesheets_needing_review,
        "preview_period_inputs": period_input_count,
        "employee_options": employee_options,
        "selected_employee_ids": selected_employee_ids,
        "organization_today": organization_today,
        "finalized_run_count": form.fields["parent_run"].queryset.count(),
    }


def _payroll_readiness(organization):
    """Build actionable setup readiness from the same inputs payroll uses to calculate pay."""
    try:
        organization_today = timezone.localdate(timezone=ZoneInfo(organization.timezone))
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        organization_today = timezone.localdate()

    settings_row = PayrollSettings.objects.filter(organization=organization).first()
    default_rule_profile = PayrollRuleProfile.objects.filter(
        organization=organization, is_default=True, active=True,
    ).first()
    effective_rule = PayrollRuleSet.objects.filter(
        rule_profile=default_rule_profile,
        effective_from__lte=organization_today,
    ).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gte=organization_today)
    ).order_by("-effective_from", "-pk").first() if default_rule_profile else None
    settings_complete = bool(settings_row and default_rule_profile and effective_rule and effective_rule.reviewed)
    if not settings_row:
        settings_detail = "Choose a pay frequency and configure reviewed pay rules."
    elif not default_rule_profile:
        settings_detail = f"{settings_row.currency} - Create an organization default rule profile"
    elif not effective_rule:
        settings_detail = f"{settings_row.currency} - No default rule is effective today"
    elif not effective_rule.reviewed:
        settings_detail = f"{settings_row.currency} · Pay rules need review"
    else:
        settings_detail = f"{settings_row.currency} · Rules reviewed"

    active_employees = Employee.objects.filter(
        organization=organization,
        status=Employee.Status.ACTIVE,
    ).select_related("payroll_profile").prefetch_related("pay_rates", "compensation_versions")
    active_employee_count = active_employees.count()
    expected_count = 0
    ready_count = 0
    excluded_count = 0
    missing_profile_count = 0
    missing_rate_count = 0
    incomplete_profile_count = 0
    unsupported_monthly_count = 0
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
        current_compensation = next((
            item for item in employee.compensation_versions.all()
            if item.effective_from <= employee_work_date
            and (item.effective_until is None or item.effective_until >= employee_work_date)
        ), None)
        if not current_rate and not current_compensation:
            missing_rate_count += 1
        monthly_unsupported = bool(
            current_compensation
            and current_compensation.basis == EmployeeCompensationVersion.Basis.MONTHLY
        )
        if monthly_unsupported:
            unsupported_monthly_count += 1
        supported_compensation = bool(
            current_compensation
            and current_compensation.basis in {
                EmployeeCompensationVersion.Basis.HOURLY,
                EmployeeCompensationVersion.Basis.DAILY,
            }
        ) or bool(current_rate and not current_compensation)
        if profile_complete and supported_compensation:
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
            problems.append(f"{missing_rate_count} missing compensation record(s)")
        if incomplete_profile_count:
            problems.append(f"{incomplete_profile_count} profile(s) need review")
        if unsupported_monthly_count:
            problems.append(f"{unsupported_monthly_count} monthly calculation(s) unavailable")
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
            "description": "Add work locations, wage checks, and effective hourly or daily compensation.",
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
    employee_query = request.GET.get("employee_q", "").strip()[:100]
    if employee_id.isdigit() and Employee.objects.filter(pk=employee_id, organization=organization).exists():
        matching_runs = matching_runs.filter(statements__employee_id=employee_id).distinct()
    elif employee_query:
        matching_runs = matching_runs.filter(
            Q(statements__employee__first_name__icontains=employee_query)
            | Q(statements__employee__last_name__icontains=employee_query)
            | Q(statements__employee__employee_code__icontains=employee_query)
        ).distinct()
        employee_id = ""
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
        .values("run_id").annotate(statement_count=Count("pk"), gross=Sum("gross_amount"), net=Sum("net_amount"))
    }
    membership_counts = dict(
        PayrollRun.objects.filter(pk__in=run_ids)
        .values_list("pk")
        .annotate(count=Count("employee_memberships"))
    )
    exception_counts = dict(
        PayrollException.objects.filter(run_id__in=run_ids, resolved_at__isnull=True, superseded_at__isnull=True)
        .values_list("run_id").annotate(count=Count("pk"))
    )
    for run in page.object_list:
        summary = summary_by_run.get(run.pk, {})
        # Selected runs snapshot their full employee scope in memberships. A
        # statement count can be smaller when some employees are blocked, so
        # it must never be presented as the run's employee scope.
        run.statement_count = summary.get("statement_count", 0)
        run.employee_count = membership_counts.get(run.pk) or run.statement_count
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
        "summary_scope": "Matching date and employee filters" if from_date or to_date or employee_id or employee_query else "Across all payroll runs",
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
        "employee_query": employee_query,
    })


@employer_required
@require_http_methods(["GET", "POST"])
def employee_payroll_list(request):
    selected_employee_ids = {
        value for value in request.POST.getlist("employees")
        if value.isdigit()
    } if request.method == "POST" and request.POST.get("action") == "bulk_assignment" else set()
    organization = _organization(request)
    bulk_form = PayrollBulkRuleAssignmentForm(
        request.POST if request.method == "POST" and request.POST.get("action") == "bulk_assignment" else None,
        organization=organization,
    )
    if request.method == "POST" and request.POST.get("action") == "bulk_assignment" and bulk_form.is_valid():
        employees_to_assign = list(bulk_form.cleaned_data["employees"])
        start = bulk_form.cleaned_data["effective_from"]
        end = bulk_form.cleaned_data["effective_until"]
        profile = bulk_form.cleaned_data["rule_profile"]
        try:
            with transaction.atomic():
                for employee in employees_to_assign:
                    prior = PayrollRuleAssignment.objects.select_for_update().filter(
                        employee=employee,
                        effective_from__lt=start,
                        effective_until__isnull=True,
                    ).order_by("-effective_from").first()
                    if prior:
                        prior.effective_until = start - timedelta(days=1)
                        prior.save(update_fields=["effective_until"])
                    assignment = PayrollRuleAssignment(
                        organization=organization,
                        employee=employee,
                        rule_profile=profile,
                        effective_from=start,
                        effective_until=end,
                        reason=bulk_form.cleaned_data["reason"].strip(),
                        assigned_by=request.user,
                    )
                    assignment.save()
            record_event(
                organization=organization,
                actor=request.user,
                action=AuditEvent.Action.PAYROLL_RULES_UPDATED,
                target_type="payroll_rule_assignment_bulk",
                target_id=profile.pk,
                summary=f"Assigned {profile.name} to {len(employees_to_assign)} employees.",
                metadata={
                    "employee_ids": [employee.pk for employee in employees_to_assign],
                    "profile": profile.code,
                    "effective_from": start.isoformat(),
                    "effective_until": end.isoformat() if end else None,
                },
            )
            messages.success(request, f"Assigned {profile.name} to {len(employees_to_assign)} employees.")
            return redirect("payroll:employee_list")
        except ValidationError as error:
            _message_error(request, error, bulk_form)
    try:
        organization_today = timezone.localdate(timezone=ZoneInfo(organization.timezone))
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        organization_today = timezone.localdate()

    profile_timezones = EmployeePayProfile.objects.filter(
        employee__organization=organization,
    ).exclude(payroll_timezone="").values_list("payroll_timezone", flat=True).distinct()
    timezone_dates = []
    for zone_name in profile_timezones:
        try:
            local_date = timezone.localdate(timezone=ZoneInfo(zone_name))
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            local_date = organization_today
        timezone_dates.append(When(payroll_profile__payroll_timezone=zone_name, then=Value(local_date)))
    payroll_work_date = (
        Case(*timezone_dates, default=Value(organization_today), output_field=DateField())
        if timezone_dates else Value(organization_today, output_field=DateField())
    )

    current_rate_query = EmployeePayRate.objects.filter(
        employee_id=OuterRef("pk"),
        effective_from__lte=OuterRef("_payroll_work_date"),
    ).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gte=OuterRef("_payroll_work_date"))
    ).order_by("-effective_from", "-pk")
    current_compensation_query = EmployeeCompensationVersion.objects.filter(
        employee_id=OuterRef("pk"),
        effective_from__lte=OuterRef("_payroll_work_date"),
    ).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gte=OuterRef("_payroll_work_date"))
    ).order_by("-effective_from", "-pk")
    default_rule_profile = PayrollRuleProfile.objects.filter(
        organization=organization, is_default=True, active=True,
    ).first()
    employees = Employee.objects.filter(organization=organization).select_related("payroll_profile").prefetch_related(
        "payroll_rule_assignments__rule_profile",
    ).annotate(
        _payroll_work_date=payroll_work_date,
        _has_current_rate=Exists(current_rate_query),
        _current_rate=Subquery(current_rate_query.values("hourly_rate")[:1]),
        _current_rate_from=Subquery(current_rate_query.values("effective_from")[:1]),
        _has_current_compensation=Exists(current_compensation_query),
        _current_comp_amount=Subquery(current_compensation_query.values("amount")[:1]),
        _current_comp_basis=Subquery(current_compensation_query.values("basis")[:1]),
        _current_comp_from=Subquery(current_compensation_query.values("effective_from")[:1]),
    )

    required_profile_missing = (
        Q(payroll_profile__isnull=True)
        | Q(payroll_profile__work_location="")
        | Q(payroll_profile__payroll_region="")
        | Q(payroll_profile__wage_order_reference="")
    )
    payroll_enabled = Q(payroll_profile__isnull=True) | Q(payroll_profile__active_for_payroll=True)
    active_employee = Q(status=Employee.Status.ACTIVE)
    has_compensation = Q(_has_current_rate=True) | Q(_has_current_compensation=True)
    supported_compensation = (
        Q(_has_current_compensation=True, _current_comp_basis__in=[
            EmployeeCompensationVersion.Basis.HOURLY,
            EmployeeCompensationVersion.Basis.DAILY,
        ])
        | Q(_has_current_compensation=False, _has_current_rate=True)
    )
    monthly_unsupported = Q(
        _has_current_compensation=True,
        _current_comp_basis=EmployeeCompensationVersion.Basis.MONTHLY,
    )
    setup_query = active_employee & payroll_enabled & (
        required_profile_missing | ~has_compensation | monthly_unsupported
    )
    review_query = (
        active_employee & payroll_enabled & ~required_profile_missing
        & supported_compensation & Q(payroll_profile__minimum_wage_confirmed=False)
    )
    ready_query = (
        active_employee & payroll_enabled & ~required_profile_missing
        & supported_compensation & Q(payroll_profile__minimum_wage_confirmed=True)
    )
    excluded_query = Q(status=Employee.Status.INACTIVE) | Q(payroll_profile__active_for_payroll=False)

    summary = employees.aggregate(
        total=Count("pk"),
        ready=Count("pk", filter=ready_query),
        needs_setup=Count("pk", filter=setup_query),
        needs_review=Count("pk", filter=review_query),
        excluded=Count("pk", filter=excluded_query),
    )

    query = request.GET.get("q", "").strip()
    if query:
        employees = employees.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(employee_code__icontains=query)
            | Q(email__icontains=query)
        )
    status = request.GET.get("status", "")
    status_filters = {
        "ready": ready_query,
        "needs_setup": setup_query,
        "missing_rate": active_employee & payroll_enabled & ~has_compensation,
        "unsupported_monthly": active_employee & payroll_enabled & monthly_unsupported,
        "missing_location": active_employee & payroll_enabled & (Q(payroll_profile__isnull=True) | Q(payroll_profile__work_location="")),
        "needs_review": review_query,
        "excluded": excluded_query,
    }
    if status not in ("", *status_filters.keys()):
        status = ""
    if status:
        employees = employees.filter(status_filters[status])
    page = Paginator(employees.order_by("last_name", "first_name", "pk"), 30).get_page(request.GET.get("page"))
    rows = []
    for employee in page.object_list:
        profile = getattr(employee, "payroll_profile", None)
        assignment = next((item for item in employee.payroll_rule_assignments.all() if (
            item.effective_from <= employee._payroll_work_date
            and (item.effective_until is None or item.effective_until >= employee._payroll_work_date)
        )), None)
        resolved_rule_profile = assignment.rule_profile if assignment else default_rule_profile
        if employee.status != Employee.Status.ACTIVE or (profile and not profile.active_for_payroll):
            payroll_status, status_detail = "excluded", "Excluded from payroll"
        elif employee._has_current_compensation and employee._current_comp_basis == EmployeeCompensationVersion.Basis.MONTHLY:
            payroll_status, status_detail = "needs-setup", "Monthly calculation unavailable"
        elif not profile or not profile.work_location.strip() or not profile.payroll_region.strip() or not profile.wage_order_reference.strip() or not (employee._has_current_rate or employee._has_current_compensation):
            payroll_status, status_detail = "needs-setup", "Add missing pay details"
        elif not profile.minimum_wage_confirmed:
            payroll_status, status_detail = "needs-review", "Confirm wage-order review"
        else:
            payroll_status, status_detail = "ready", "Pay profile complete"
        rows.append({
            "employee": employee,
            "selected": str(employee.pk) in selected_employee_ids,
            "profile": profile,
            "rate": employee._current_rate,
            "rate_effective_from": employee._current_rate_from,
            "compensation_amount": employee._current_comp_amount,
            "compensation_basis": employee._current_comp_basis,
            "compensation_effective_from": employee._current_comp_from,
            "payroll_status": payroll_status,
            "status_detail": status_detail,
            "rule_profile": resolved_rule_profile,
            "rule_profile_source": "Assigned override" if assignment else "Inherited default",
        })
    return render(request, "payroll/employee_list.html", {
        "organization": organization,
        "rows": rows,
        "page": page,
        "query": query,
        "selected_status": status,
        "status_choices": [
            ("", "All employees"),
            ("ready", "Payroll ready"),
            ("missing_rate", "Missing compensation"),
            ("unsupported_monthly", "Monthly calculation unavailable"),
            ("missing_location", "Missing work location"),
            ("needs_review", "Needs wage review"),
            ("needs_setup", "Needs setup"),
            ("excluded", "Excluded from payroll"),
        ],
        "summary": summary,
        "bulk_assignment_form": bulk_form,
        "page_querystring": _page_querystring(request),
        "currency": PayrollSettings.objects.filter(organization=organization).values_list("currency", flat=True).first() or "PHP",
    })


@employer_required
@require_http_methods(["GET", "POST"])
def setup(request):
    organization = _organization(request)
    try:
        organization_today = timezone.localdate(timezone=ZoneInfo(organization.timezone))
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        organization_today = timezone.localdate()
    settings_row = PayrollSettings.objects.filter(organization=organization).first()
    if settings_row is None:
        settings_row = PayrollSettings(organization=organization)
    profiles = PayrollRuleProfile.objects.filter(organization=organization).annotate(
        version_count=Count("rule_versions", distinct=True), employee_count=Count("employee_assignments", distinct=True),
    )
    employees_with_current_override = PayrollRuleAssignment.objects.filter(
        organization=organization,
        effective_from__lte=organization_today,
    ).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gte=organization_today)
    ).values("employee_id")
    inherited_default_count = Employee.objects.filter(
        organization=organization,
        status=Employee.Status.ACTIVE,
        payroll_profile__active_for_payroll=True,
    ).exclude(pk__in=employees_with_current_override).count()
    for profile in profiles:
        profile.display_employee_count = profile.employee_count + (
            inherited_default_count if profile.is_default else 0
        )
    selected_profile_id = request.POST.get("rule_profile") if request.method == "POST" else request.GET.get("profile")
    if selected_profile_id and selected_profile_id.isdigit():
        selected_rule_profile = profiles.filter(pk=selected_profile_id).first()
    else:
        selected_rule_profile = profiles.filter(is_default=True).first()
    latest_rule = PayrollRuleSet.objects.filter(
        organization=organization,
        rule_profile=selected_rule_profile,
    ).order_by("-effective_from").first() if selected_rule_profile else PayrollRuleSet.objects.filter(
        organization=organization, rule_profile__isnull=True,
    ).order_by("-effective_from").first()
    add_version = request.GET.get("new_rules") == "1" or bool(latest_rule and latest_rule.reviewed)
    rule_instance = latest_rule if latest_rule and not add_version else PayrollRuleSet(
        organization=organization,
        created_by=request.user,
        effective_from=organization_today + timedelta(days=1 if latest_rule else 0),
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
    profile_form = PayrollRuleProfileForm(
        request.POST if action == "profile" else None,
        organization=organization,
        actor=request.user,
        prefix="profile",
    )
    if action == "settings" and request.method == "POST" and settings_form.is_valid():
        settings_form.save()
        record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_RULES_UPDATED, target_type="payroll_settings", target_id=settings_row.pk, summary="Updated payroll currency and frequency.", metadata={"currency": settings_row.currency, "frequency": settings_row.frequency})
        messages.success(request, "Payroll settings saved.")
        return redirect("payroll:setup")
    if action == "profile" and request.method == "POST" and profile_form.is_valid():
        try:
            profile = profile_form.save()
            record_event(
                organization=organization,
                actor=request.user,
                action=AuditEvent.Action.PAYROLL_RULES_UPDATED,
                target_type="payroll_rule_profile",
                target_id=profile.pk,
                summary=f"Created payroll rule profile {profile.name}.",
                metadata={"code": profile.code, "is_default": profile.is_default},
            )
            messages.success(request, f"Payroll rule profile {profile.name} was created.")
            return redirect(f"{reverse('payroll:setup')}?profile={profile.pk}")
        except ValidationError as error:
            _message_error(request, error, profile_form)
    if action == "rules" and request.method == "POST" and rule_form.is_valid():
        try:
            with transaction.atomic():
                selected_rule_profile = selected_rule_profile or _ensure_default_rule_profile(organization, request.user)
                new_rule = rule_form.save(commit=False, actor=request.user)
                new_rule.created_by = request.user
                new_rule.organization = organization
                new_rule.rule_profile = selected_rule_profile
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
            _message_error(request, error, rule_form)
    return render(request, "payroll/setup.html", {
        "organization": organization,
        "settings_form": settings_form,
        "rule_form": rule_form,
        "profile_form": profile_form,
        "rule_profiles": profiles,
        "selected_rule_profile": selected_rule_profile,
        "rule_history": PayrollRuleSet.objects.filter(organization=organization, rule_profile=selected_rule_profile) if selected_rule_profile else PayrollRuleSet.objects.filter(organization=organization, rule_profile__isnull=True),
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

    work_timezone = profile.payroll_timezone or organization.timezone
    try:
        employee_zone = ZoneInfo(work_timezone)
        employee_work_date = timezone.localdate(employee_zone)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        work_timezone = organization.timezone
        try:
            employee_zone = ZoneInfo(organization.timezone)
            employee_work_date = timezone.localdate(employee_zone)
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            employee_work_date = timezone.localdate()

    current_compensation = effective_compensation(employee, employee_work_date)
    current_rate = current_compensation["source"] if current_compensation and current_compensation["basis"] == EmployeeCompensationVersion.Basis.HOURLY else None
    current_daily_compensation = current_compensation["source"] if current_compensation and current_compensation["basis"] == EmployeeCompensationVersion.Basis.DAILY else None
    current_monthly_compensation = current_compensation["source"] if current_compensation and current_compensation["basis"] == EmployeeCompensationVersion.Basis.MONTHLY else None
    supported_compensation = bool(
        current_compensation
        and current_compensation["basis"] in {
            EmployeeCompensationVersion.Basis.HOURLY,
            EmployeeCompensationVersion.Basis.DAILY,
        }
    )
    compensations = employee.compensation_versions.order_by("-effective_from", "-pk")

    missing_setup = []
    if not profile.work_location.strip():
        missing_setup.append("Work location")
    if not profile.payroll_region.strip():
        missing_setup.append("Payroll region")
    if not profile.wage_order_reference.strip():
        missing_setup.append("Wage order reference")
    if not current_compensation:
        missing_setup.append("Hourly or daily compensation")
    elif not supported_compensation:
        missing_setup.append("Supported hourly or daily calculation method")

    if employee.status != Employee.Status.ACTIVE:
        profile_status, profile_status_label = "excluded", "Employee inactive"
        profile_status_detail = "Inactive employees are not included in payroll runs."
    elif not profile.active_for_payroll:
        profile_status, profile_status_label = "excluded", "Excluded from payroll"
        profile_status_detail = "Enable payroll participation to include this employee in eligible runs."
    elif missing_setup:
        profile_status, profile_status_label = "needs-setup", "Needs setup"
        profile_status_detail = "Missing: " + ", ".join(missing_setup) + "."
    elif not profile.minimum_wage_confirmed:
        profile_status, profile_status_label = "needs-review", "Needs review"
        profile_status_detail = "Confirm the compensation amount against the recorded wage order."
    else:
        profile_status, profile_status_label = "ready", "Payroll ready"
        profile_status_detail = "Required work and wage details are configured."

    current_rule_assignment = employee.payroll_rule_assignments.filter(
        effective_from__lte=employee_work_date,
    ).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gte=employee_work_date)
    ).select_related("rule_profile").first()
    default_rule_profile = PayrollRuleProfile.objects.filter(
        organization=organization, is_default=True, active=True,
    ).first()

    readiness_items = [
        {
            "label": "Compensation configured",
            "complete": supported_compensation,
            "detail": (
                "An effective hourly or daily amount is active."
                if supported_compensation else
                "The monthly amount is recorded, but monthly-to-payroll conversion is not supported yet. Add an hourly or daily version or exclude this employee from payroll."
                if current_monthly_compensation else
                "Add an effective hourly or daily amount."
            ),
        },
        {
            "label": "Work location set",
            "complete": bool(profile.work_location.strip() and profile.payroll_timezone.strip()),
            "detail": "Work location and timezone are configured." if profile.work_location.strip() and profile.payroll_timezone.strip() else "Set the employee's location and payroll timezone.",
        },
        {
            "label": "Wage-order reference on file",
            "complete": bool(profile.wage_order_reference.strip()),
            "detail": "Reference recorded for the employee's work location." if profile.wage_order_reference.strip() else "Record the applicable wage-order reference.",
        },
        {
            "label": "Rule profile resolved",
            "complete": bool(current_rule_assignment or default_rule_profile),
            "detail": "An employee override or organization default will be used." if (current_rule_assignment or default_rule_profile) else "Create an active organization default profile.",
        },
        {
            "label": "Pre-run eligibility review",
            "complete": bool(profile.minimum_wage_confirmed and profile.night_differential_eligible is not None),
            "detail": (
                "Wage-order, night-differential, and worker-classification checks are recorded. Statutory amounts are reviewed in the payroll run."
                if profile.minimum_wage_confirmed
                else "Complete the wage-order, night-differential, and worker-classification checks above. Statutory amounts are reviewed after a payroll draft is created."
            ),
        },
    ]
    incomplete_readiness_items = [item for item in readiness_items if not item["complete"]]
    if profile_status in {"needs-setup", "needs-review"}:
        profile_status_detail = (
            "Complete the requirements below before this employee is included in a final payroll run."
        )
    elif profile_status == "ready":
        profile_status_detail = "All payroll readiness checks are complete for this employee."

    action = request.POST.get("action", "profile") if request.method == "POST" else ""
    form = EmployeePayProfileForm(
        request.POST if request.method == "POST" and action != "assignment" else None,
        instance=profile,
    )
    assignment_form = PayrollRuleAssignmentForm(
        request.POST if request.method == "POST" and action == "assignment" else None,
        organization=organization,
        employee=employee,
        actor=request.user,
    )
    if request.method == "POST" and action == "assignment" and assignment_form.is_valid():
        try:
            with transaction.atomic():
                assignment = assignment_form.save(commit=False)
                prior = PayrollRuleAssignment.objects.select_for_update().filter(
                    employee=employee,
                    effective_from__lt=assignment.effective_from,
                    effective_until__isnull=True,
                ).order_by("-effective_from").first()
                if prior:
                    prior.effective_until = assignment.effective_from - timedelta(days=1)
                    prior.save(update_fields=["effective_until"])
                assignment.save()
            record_event(
                organization=organization,
                actor=request.user,
                action=AuditEvent.Action.PAYROLL_RULES_UPDATED,
                target_type="payroll_rule_assignment",
                target_id=assignment.pk,
                summary=f"Assigned {assignment.rule_profile.name} to {employee.employee_code}.",
                metadata={
                    "employee": employee.employee_code,
                    "profile": assignment.rule_profile.code,
                    "effective_from": assignment.effective_from.isoformat(),
                    "effective_until": assignment.effective_until.isoformat() if assignment.effective_until else None,
                },
            )
            messages.success(request, "Payroll rule profile assignment saved.")
            return redirect("payroll:employee_profile", pk=employee.pk)
        except ValidationError as error:
            _message_error(request, error, assignment_form)
    if request.method == "POST" and action != "assignment" and form.is_valid():
        try:
            form.save()
            record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_PROFILE_UPDATED, target_type="employee_pay_profile", target_id=profile.pk, summary=f"Updated payroll profile for {employee.employee_code}.", metadata={"region": profile.payroll_region, "timezone": profile.payroll_timezone, "minimum_wage_confirmed": profile.minimum_wage_confirmed})
            messages.success(request, "Employee payroll profile saved.")
            return redirect("payroll:employee_profile", pk=employee.pk)
        except ValidationError as error:
            _message_error(request, error, form)
    return render(request, "payroll/employee_profile.html", {
        "organization": organization,
        "employee": employee,
        "profile": profile,
        "form": form,
        "rates": employee.pay_rates.select_related("created_by"),
        "compensations": compensations,
        "current_rate": current_rate,
        "current_daily_compensation": current_daily_compensation,
        "current_monthly_compensation": current_monthly_compensation,
        "current_compensation": current_compensation,
        "current_hourly_amount": current_compensation["amount"] if current_compensation and current_compensation["basis"] == EmployeeCompensationVersion.Basis.HOURLY else None,
        "employee_work_date": employee_work_date,
        "work_timezone": work_timezone,
        "profile_status": profile_status,
        "profile_status_label": profile_status_label,
        "profile_status_detail": profile_status_detail,
        "profile_location_display": profile.work_location or "Not set",
        "rule_profiles": PayrollRuleProfile.objects.filter(organization=organization, active=True).order_by("-is_default", "name"),
        "default_rule_profile": default_rule_profile,
        "rule_assignments": employee.payroll_rule_assignments.select_related("rule_profile", "assigned_by"),
        "current_rule_assignment": current_rule_assignment,
        "assignment_form": assignment_form,
        "readiness_items": readiness_items,
        "incomplete_readiness_items": incomplete_readiness_items,
        "readiness_complete_count": sum(1 for item in readiness_items if item["complete"]),
        "profile_audit_events": AuditEvent.objects.filter(
            organization=organization,
            target_type__in={
                "employee_pay_profile", "employee_compensation_version", "employee_pay_rate",
                "employee_component_assignment", "payroll_rule_assignment", "payroll_period_input",
            },
            target_id__in={str(employee.pk), str(profile.pk)} if profile.pk else {str(employee.pk)},
        ).select_related("actor").order_by("-created_at", "-pk")[:12],
        "component_assignments": employee.payroll_component_assignments.select_related("component", "assigned_by"),
        "period_inputs": employee.payroll_period_inputs.order_by("-work_date", "-pk")[:20],
        "component_count": PayrollComponentDefinition.objects.filter(organization=organization, active=True).count(),
        "currency_symbol": "₱",
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
            _message_error(request, error, form)
    return render(request, "payroll/pay_rate_form.html", {"organization": organization, "employee": employee, "form": form})


@employer_required
@require_http_methods(["GET", "POST"])
def add_compensation(request, pk):
    organization = _organization(request)
    employee = get_object_or_404(Employee, pk=pk, organization=organization)
    form = EmployeeCompensationForm(
        request.POST or None,
        employee=employee,
        actor=request.user,
        organization=organization,
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                compensation = form.save(commit=False)
                if PayrollRun.objects.filter(
                    organization=organization,
                    status=PayrollRun.Status.FINALIZED,
                    statements__employee=employee,
                    period_end__gte=compensation.effective_from,
                ).exists():
                    raise ValidationError("This effective date could change a finalized payroll period. Create an adjustment run instead.")
                prior = EmployeeCompensationVersion.objects.select_for_update().filter(
                    employee=employee,
                    effective_from__lt=compensation.effective_from,
                    effective_until__isnull=True,
                ).order_by("-effective_from").first()
                if prior:
                    prior.effective_until = compensation.effective_from - timedelta(days=1)
                    prior.save(update_fields=["effective_until"])
                compensation.save()
            record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_RATE_ADDED, target_type="employee_compensation_version", target_id=compensation.pk, summary=f"Added a {compensation.get_basis_display().lower()} compensation version for {employee.employee_code}.", metadata={"basis": compensation.basis, "effective_from": compensation.effective_from.isoformat(), "amount": str(compensation.amount)})
            messages.success(request, "Compensation version added to the employee's pay history.")
            return redirect("payroll:employee_profile", pk=employee.pk)
        except ValidationError as error:
            _message_error(request, error, form)
    return render(request, "payroll/compensation_form.html", {"organization": organization, "employee": employee, "form": form})


@employer_required
@require_http_methods(["GET", "POST"])
def add_component_assignment(request, pk):
    organization = _organization(request)
    employee = get_object_or_404(Employee, pk=pk, organization=organization)
    form = EmployeeComponentAssignmentForm(
        request.POST or None,
        employee=employee,
        actor=request.user,
        organization=organization,
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                assignment = form.save(commit=False)
                if PayrollRun.objects.filter(
                    organization=organization,
                    status=PayrollRun.Status.FINALIZED,
                    statements__employee=employee,
                    period_end__gte=assignment.effective_from,
                ).exists():
                    raise ValidationError("This effective date could change a finalized payroll period. Create an adjustment run instead.")
                prior = EmployeeComponentAssignment.objects.select_for_update().filter(
                    employee=employee,
                    component=assignment.component,
                    effective_from__lt=assignment.effective_from,
                    effective_until__isnull=True,
                ).order_by("-effective_from").first()
                if prior:
                    prior.effective_until = assignment.effective_from - timedelta(days=1)
                    prior.save(update_fields=["effective_until"])
                assignment.save()
            record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_RULES_UPDATED, target_type="employee_component_assignment", target_id=assignment.pk, summary=f"Assigned {assignment.component.label} to {employee.employee_code}.", metadata={"component": assignment.component.code, "effective_from": assignment.effective_from.isoformat(), "amount": str(assignment.amount)})
            messages.success(request, "Pay component assignment saved.")
            return redirect("payroll:employee_profile", pk=employee.pk)
        except ValidationError as error:
            _message_error(request, error, form)
    return render(request, "payroll/component_assignment_form.html", {"organization": organization, "employee": employee, "form": form})


@employer_required
@require_http_methods(["GET", "POST"])
def add_period_input(request, pk):
    organization = _organization(request)
    employee = get_object_or_404(Employee, pk=pk, organization=organization)
    form = PayrollPeriodInputForm(
        request.POST or None,
        employee=employee,
        actor=request.user,
        organization=organization,
    )
    if request.method == "POST" and form.is_valid():
        try:
            period_input = form.save()
            record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_RULES_UPDATED, target_type="payroll_period_input", target_id=period_input.pk, summary=f"Added a reviewed payroll period input for {employee.employee_code}.", metadata={"work_date": period_input.work_date.isoformat(), "period_start": period_input.period_start.isoformat(), "period_end": period_input.period_end.isoformat()})
            messages.success(request, "Reviewed period input saved. It will be included in a matching daily payroll run.")
            return redirect("payroll:employee_profile", pk=employee.pk)
        except ValidationError as error:
            _message_error(request, error, form)
    return render(request, "payroll/period_input_form.html", {"organization": organization, "employee": employee, "form": form})


@employer_required
@require_http_methods(["GET", "POST"])
def component_definitions(request):
    organization = _organization(request)
    form = PayrollComponentDefinitionForm(request.POST or None, organization=organization, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            component = form.save()
            messages.success(request, f"{component.label} is available for employee assignments.")
            return redirect("payroll:component_definitions")
        except ValidationError as error:
            _message_error(request, error, form)
    all_components = PayrollComponentDefinition.objects.filter(organization=organization)
    query = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "")
    basis = request.GET.get("basis", "")
    status = request.GET.get("status", "")
    if query:
        all_components = all_components.filter(
            Q(code__icontains=query) | Q(label__icontains=query) | Q(description__icontains=query)
        )
    if kind in PayrollComponentDefinition.Kind.values:
        all_components = all_components.filter(kind=kind)
    else:
        kind = ""
    if basis in PayrollComponentDefinition.Basis.values:
        all_components = all_components.filter(basis=basis)
    else:
        basis = ""
    if status == "active":
        all_components = all_components.filter(active=True)
    elif status == "inactive":
        all_components = all_components.filter(active=False)
    else:
        status = ""
    page = Paginator(all_components.order_by("label", "pk"), 10).get_page(request.GET.get("page"))
    counts = PayrollComponentDefinition.objects.filter(organization=organization).aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(active=True)),
        earnings=Count("pk", filter=Q(kind=PayrollComponentDefinition.Kind.EARNING)),
        deductions=Count("pk", filter=Q(kind=PayrollComponentDefinition.Kind.DEDUCTION)),
        employer_contributions=Count("pk", filter=Q(kind=PayrollComponentDefinition.Kind.EMPLOYER_CONTRIBUTION)),
    )
    return render(request, "payroll/component_definitions.html", {
        "organization": organization,
        "form": form,
        "components": page.object_list,
        "page": page,
        "counts": counts,
        "query": query,
        "selected_kind": kind,
        "selected_basis": basis,
        "selected_status": status,
        "kind_choices": PayrollComponentDefinition.Kind.choices,
        "basis_choices": PayrollComponentDefinition.Basis.choices,
        "page_querystring": _page_querystring(request),
        "show_form": request.method == "POST" or request.GET.get("add") == "1",
    })


@employer_required
@require_http_methods(["GET", "POST"])
def component_edit(request, pk):
    organization = _organization(request)
    component = get_object_or_404(PayrollComponentDefinition, pk=pk, organization=organization)
    form = PayrollComponentDefinitionForm(
        request.POST or None,
        instance=component,
        organization=organization,
        actor=request.user,
    )
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
            record_event(
                organization=organization,
                actor=request.user,
                action=AuditEvent.Action.PAYROLL_RULES_UPDATED,
                target_type="payroll_component_definition",
                target_id=component.pk,
                summary=f"Updated payroll component {component.code}.",
                metadata={"code": component.code, "active": component.active},
            )
            messages.success(request, f"{component.label} updated.")
            return redirect("payroll:component_definitions")
        except ValidationError as error:
            _message_error(request, error, form)
    return render(request, "payroll/component_edit.html", {
        "organization": organization,
        "component": component,
        "form": form,
    })


@employer_required
@require_POST
def component_toggle(request, pk):
    organization = _organization(request)
    component = get_object_or_404(PayrollComponentDefinition, pk=pk, organization=organization)
    component.active = not component.active
    component.save(update_fields=["active"])
    record_event(
        organization=organization,
        actor=request.user,
        action=AuditEvent.Action.PAYROLL_RULES_UPDATED,
        target_type="payroll_component_definition",
        target_id=component.pk,
        summary=f"{'Activated' if component.active else 'Deactivated'} payroll component {component.code}.",
        metadata={"code": component.code, "active": component.active},
    )
    messages.success(request, f"{component.label} is now {'active' if component.active else 'inactive'}.")
    return redirect("payroll:component_definitions")


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
            return redirect(f"{reverse('payroll:holiday_calendar')}?year={holiday_date.year}")
        holiday = form.save()
        record_event(organization=organization, actor=request.user, action=AuditEvent.Action.PAYROLL_RULES_UPDATED, target_type="payroll_holiday", target_id=holiday.pk, summary=f"Added {holiday.name} to the payroll calendar.", metadata={"date": holiday.date.isoformat(), "kind": holiday.kind, "reviewed": holiday.reviewed})
        messages.success(request, "Holiday saved. Payroll blocks finalization if the holiday's source and review details are missing.")
        return redirect(f"{reverse('payroll:holiday_calendar')}?year={holiday.date.year}")

    try:
        organization_today = timezone.localdate(timezone=ZoneInfo(organization.timezone))
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        organization_today = timezone.localdate()
    all_holidays = PayrollHoliday.objects.filter(organization=organization)
    available_years = {date.year for date in all_holidays.dates("date", "year")}
    available_years.add(organization_today.year)
    raw_year = request.GET.get("year", str(organization_today.year))
    selected_year = int(raw_year) if raw_year.isdigit() and 1900 <= int(raw_year) <= 2200 else organization_today.year
    available_years.add(selected_year)
    year_holidays = all_holidays.filter(date__year=selected_year)
    holiday_count = year_holidays.count()
    reviewed_count = year_holidays.exclude(reviewed_by="").exclude(
        reviewed_at__isnull=True
    ).exclude(source_reference="").count()

    holidays = year_holidays
    review_status = request.GET.get("review", "")
    if review_status == "reviewed":
        holidays = holidays.exclude(reviewed_by="").exclude(reviewed_at__isnull=True).exclude(source_reference="")
    elif review_status == "needs_review":
        holidays = holidays.filter(
            Q(reviewed_by="") | Q(reviewed_at__isnull=True) | Q(source_reference="")
        )
    else:
        review_status = ""
    query = request.GET.get("q", "").strip()
    if query:
        holidays = holidays.filter(name__icontains=query)
    page = Paginator(holidays.order_by("date", "name"), 20).get_page(request.GET.get("page"))
    show_form = request.method == "POST" or request.GET.get("add") == "1"
    return render(request, "payroll/holiday_calendar.html", {
        "organization": organization,
        "form": form,
        "page": page,
        "holidays": page.object_list,
        "selected_year": selected_year,
        "default_year": organization_today.year,
        "year_choices": sorted(available_years, reverse=True),
        "review_status": review_status,
        "query": query,
        "page_querystring": _page_querystring(request),
        "show_form": show_form,
        "holiday_count": holiday_count,
        "reviewed_count": reviewed_count,
        "needs_review_count": holiday_count - reviewed_count,
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
    today = _organization_local_date(organization)
    settings_row = PayrollSettings.objects.filter(organization=organization).first()
    frequency = settings_row.frequency if settings_row else PayrollSettings.Frequency.SEMI_MONTHLY
    period_start, period_end = _period_bounds(today, frequency, "previous")
    form = PayrollRunForm(
        organization=organization,
        initial={
            "run_type": PayrollRun.RunType.REGULAR,
            "scope_mode": PayrollRun.ScopeMode.ALL_ACTIVE,
            "period_start": period_start,
            "period_end": period_end,
            "pay_date": period_end + timedelta(days=5),
            "request_key": uuid.uuid4(),
        },
    )
    readiness = _payroll_readiness(organization)
    context = {
        "organization": organization,
        "form": form,
    }
    context.update(_run_form_context(organization, form, readiness))
    return render(request, "payroll/run_form.html", context)


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
                employee_ids=(
                    [employee.pk for employee in form.cleaned_data["employees"]]
                    if form.cleaned_data["scope_mode"] == PayrollRun.ScopeMode.SELECTED else None
                ),
            )
            messages.success(request, "Payroll draft created. Review exceptions and add any itemized manual adjustments.")
            return redirect("payroll:run_detail", pk=run.pk)
        except ValidationError as error:
            _message_error(request, error, form)
    readiness = _payroll_readiness(organization)
    context = {
        "organization": organization,
        "form": form,
    }
    context.update(_run_form_context(organization, form, readiness))
    return render(request, "payroll/run_form.html", context)


@employer_required
@require_http_methods(["GET", "POST"])
def statutory_exception(request, pk, assessment_pk):
    organization = _organization(request)
    run = get_object_or_404(PayrollRun.objects.filter(organization=organization), pk=pk)
    assessment = get_object_or_404(
        PayrollStatutoryAssessment.objects.select_related("statement", "statement__employee", "statement__run"),
        pk=assessment_pk,
        statement__run=run,
    )
    statement = assessment.statement
    statement.statutory_rows = statutory_review_rows(statement)
    statement.statutory_reviewed_count = sum(1 for row in statement.statutory_rows if row["current"])
    statement.statutory_total_count = len(statement.statutory_rows)
    statement.statutory_complete = all(row["current"] for row in statement.statutory_rows)
    statement.statutory_form = StatutoryReviewForm(
        request.POST or None,
        statement=statement,
        prefix=f"statutory-{statement.pk}",
    )
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if request.method == "POST":
        if statement.statutory_form.is_valid():
            try:
                record_statutory_review(statement=statement, actor=request.user, **statement.statutory_form.cleaned_data)
            except ValidationError as error:
                statement.statutory_form.add_error(None, error)
            else:
                if not ajax:
                    messages.success(request, "Statutory review saved for this employee and payroll period.")
                    return redirect("payroll:statutory_exception", pk=run.pk, assessment_pk=assessment.pk)
        if ajax:
            statement.statutory_rows = statutory_review_rows(statement)
            statement.statutory_reviewed_count = sum(1 for row in statement.statutory_rows if row["current"])
            statement.statutory_total_count = len(statement.statutory_rows)
            statement.statutory_complete = all(row["current"] for row in statement.statutory_rows)
            html = render_to_string(
                "payroll/_statutory_review.html",
                {
                    "statement": statement,
                    "run": run,
                    "open_statutory_statement_id": statement.pk,
                    "dedicated_statutory_exception": True,
                },
                request=request,
            )
            message = "Statutory review saved for this employee and payroll period." if not statement.statutory_form.errors else "Check the statutory review fields and try again."
            return JsonResponse({
                "ok": not statement.statutory_form.errors,
                "html": html,
                "message": message,
                "reviewed_count": statement.statutory_reviewed_count,
                "total_count": statement.statutory_total_count,
                "complete": statement.statutory_complete,
            }, status=200 if not statement.statutory_form.errors else 422)
    return render(request, "payroll/statutory_exception.html", {
        "organization": organization,
        "run": run,
        "statement": statement,
        "assessment": assessment,
        "open_statutory_statement_id": statement.pk,
        "dedicated_statutory_exception": True,
    })


@employer_required
@require_GET
def statutory_workspace(request, pk):
    """Stable deep link for the run-level statutory workspace."""
    organization = _organization(request)
    run = get_object_or_404(PayrollRun.objects.filter(organization=organization), pk=pk)
    return redirect(f"{reverse('payroll:run_detail', kwargs={'pk': run.pk})}?stat_page=1#statutory-review")


@employer_required
@require_POST
def statutory_generate(request, pk):
    organization = _organization(request)
    run = get_object_or_404(PayrollRun.objects.filter(organization=organization), pk=pk)
    try:
        result = generate_statutory_assessments(run=run, actor=request.user)
    except ValidationError as error:
        message = "; ".join(error.messages) if getattr(error, "messages", None) else str(error)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "message": message}, status=422)
        messages.error(request, message)
    else:
        message = f"Generated {result['assessment_count']} statutory assessments. Ready rows can now be confirmed in bulk."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "message": message, "assessment_count": result["assessment_count"], "counts": result["counts"], "revision": result["run"].review_revision})
        messages.success(request, message)
    return redirect(f"{reverse('payroll:run_detail', kwargs={'pk': run.pk})}?stat_page=1#statutory-review")


@employer_required
@require_POST
def statutory_bulk_review(request, pk):
    organization = _organization(request)
    run = get_object_or_404(PayrollRun.objects.filter(organization=organization), pk=pk)
    form = PayrollStatutoryBulkReviewForm(request.POST)
    if not form.is_valid():
        message = next(iter(form.errors.values()))[0] if form.errors else "Check the bulk review fields."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "message": str(message), "errors": form.errors}, status=422)
        messages.error(request, str(message))
        return redirect(f"{reverse('payroll:run_detail', kwargs={'pk': run.pk})}?stat_page=1#statutory-review")
    assessment_ids = request.POST.getlist("assessment_ids")
    scope = request.POST.get("selection_scope", "visible")
    if scope == "all":
        filters = {
            "stat_q": request.POST.get("stat_q", "").strip(),
            "stat_agency": request.POST.get("stat_agency", "").strip(),
            "stat_status": request.POST.get("stat_status", "").strip(),
            "stat_source": request.POST.get("stat_source", "").strip(),
        }
        query = _statutory_assessment_queryset(run)
        if filters["stat_q"]:
            query = query.filter(
                Q(statement__employee__first_name__icontains=filters["stat_q"])
                | Q(statement__employee__last_name__icontains=filters["stat_q"])
                | Q(statement__employee__employee_code__icontains=filters["stat_q"])
            )
        if filters["stat_agency"]:
            query = query.filter(agency=filters["stat_agency"])
        if filters["stat_status"]:
            query = query.filter(status=filters["stat_status"])
        else:
            query = query.exclude(status__in=[PayrollStatutoryAssessment.Status.REVIEWED, PayrollStatutoryAssessment.Status.SUPERSEDED])
        if filters["stat_source"]:
            query = query.filter(source_type=filters["stat_source"])
        assessment_ids = list(query.values_list("pk", flat=True))
    try:
        result = bulk_review_statutory_assessments(
            run=run,
            actor=request.user,
            assessment_ids=assessment_ids,
            registration=form.cleaned_data["registration"],
            treatment=form.cleaned_data["treatment"],
            source_reference=form.cleaned_data["source_reference"],
            review_note=form.cleaned_data["review_note"],
            registration_follow_up=form.cleaned_data.get("registration_follow_up", ""),
            expected_revision=request.POST.get("expected_revision"),
        )
    except ValidationError as error:
        message = "; ".join(error.messages) if getattr(error, "messages", None) else str(error)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "message": message}, status=409)
        messages.error(request, message)
    else:
        message = f"Reviewed {result['reviewed_count']} statutory assessments."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            queue = _statutory_assessment_queryset(result["run"])
            counts = {
                "total": queue.count(),
                "ready": queue.filter(status=PayrollStatutoryAssessment.Status.READY).count(),
                "attention": queue.filter(status__in=[PayrollStatutoryAssessment.Status.NEEDS_REVIEW, PayrollStatutoryAssessment.Status.SUPERSEDED]).count(),
                "reviewed": queue.filter(status=PayrollStatutoryAssessment.Status.REVIEWED).count(),
            }
            pending_employee_count = queue.exclude(status=PayrollStatutoryAssessment.Status.REVIEWED).values("statement_id").distinct().count()
            return JsonResponse({"ok": True, "message": message, "reviewed_count": result["reviewed_count"], "revision": result["run"].review_revision, "assessment_ids": [int(value) for value in assessment_ids], "counts": counts, "pending_employee_count": pending_employee_count})
        messages.success(request, message)
    return redirect(f"{reverse('payroll:run_detail', kwargs={'pk': run.pk})}?stat_page=1#statutory-review")


@employer_required
@require_http_methods(["GET", "POST"])
def run_detail(request, pk):
    organization = _organization(request)
    run = get_object_or_404(PayrollRun.objects.filter(organization=organization), pk=pk)
    ajax_statutory_review = False
    ajax_statement_id = None
    invalid_statutory_form = None
    invalid_statement_id = None
    invalid_adjustment_form = None
    invalid_exception_form = None
    invalid_exception_id = None
    invalid_finalize_form = None
    invalid_void_form = None
    if request.method == "POST":
        action = request.POST.get("action")
        ajax_statutory_review = action == "statutory_review" and request.headers.get("X-Requested-With") == "XMLHttpRequest"
        action_form = None
        try:
            if action == "recalculate":
                calculate_payroll_run(run, actor=request.user)
                messages.success(request, "Payroll preview recalculated from the current approved timesheets and rules.")
            elif action == "statutory_review":
                statement = get_object_or_404(PayrollStatement, pk=request.POST.get('statement_id'), run=run)
                ajax_statement_id = statement.pk
                form = StatutoryReviewForm(request.POST, statement=statement, prefix=f'statutory-{statement.pk}')
                action_form = form
                if form.is_valid():
                    try:
                        record_statutory_review(statement=statement, actor=request.user, **form.cleaned_data)
                        if not ajax_statutory_review:
                            messages.success(request, 'Statutory review saved for this employee and payroll period.')
                    except ValidationError as error:
                        form.add_error(None, error)
                if form.errors:
                    invalid_statutory_form = form
                    invalid_statement_id = statement.pk
                    if not ajax_statutory_review:
                        messages.error(request, 'Check the statutory review fields and try again.')
            elif action == "adjustment":
                form = PayrollAdjustmentForm(request.POST, organization=organization)
                action_form = form
                if form.is_valid():
                    add_adjustment(run=run, actor=request.user, **form.cleaned_data)
                    messages.success(request, "Payroll line added to the draft.")
                else:
                    invalid_adjustment_form = form
                    for errors in form.errors.values():
                        for error in errors:
                            messages.error(request, error)
            elif action == "submit_review":
                submit_for_review(run=run, actor=request.user)
                messages.success(request, "Payroll run submitted for review.")
            elif action == 'return_to_draft':
                return_payroll_to_draft(run=run, actor=request.user)
                messages.success(request, 'Payroll returned to draft. Review any changed amounts before submitting again.')
            elif action == "finalize":
                form = FinalizePayrollForm(request.POST)
                action_form = form
                if form.is_valid():
                    finalize_payroll_run(run=run, actor=request.user, **form.cleaned_data)
                    messages.success(request, "Payroll run finalized. Employee payslips are now available.")
                else:
                    invalid_finalize_form = form
                    messages.error(request, "Add review evidence before finalizing this payroll run.")
            elif action == "void":
                form = VoidPayrollForm(request.POST)
                action_form = form
                if form.is_valid():
                    void_payroll_run(run=run, actor=request.user, **form.cleaned_data)
                    messages.success(request, "Payroll run voided and retained in history.")
                else:
                    invalid_void_form = form
                    messages.error(request, "Add a reason before voiding this payroll run.")
            elif action == "resolve_exception":
                exception = get_object_or_404(PayrollException, pk=request.POST.get("exception_id"), run=run)
                form = PayrollExceptionResolutionForm(
                    request.POST,
                    run=run,
                    exception=exception,
                    prefix=f"exception-{exception.pk}",
                )
                action_form = form
                if form.is_valid():
                    resolve_payroll_exception(
                        exception=exception,
                        actor=request.user,
                        note=form.cleaned_data["resolution_note"],
                        resolution_line=form.cleaned_data["resolution_line"],
                    )
                    messages.success(request, "Exception review recorded with its resolution evidence.")
                else:
                    invalid_exception_form = form
                    invalid_exception_id = exception.pk
                    for errors in form.errors.values():
                        for error in errors:
                            messages.error(request, error)
            elif action == "remove_line":
                remove_adjustment(run=run, line_id=request.POST.get("line_id"), actor=request.user)
                messages.success(request, "Manual payroll line removed.")
            else:
                messages.error(request, "Choose a valid payroll action.")
        except ValidationError as error:
            if action == "adjustment" and action_form is not None:
                invalid_adjustment_form = action_form
            elif action == "statutory_review" and action_form is not None:
                invalid_statutory_form = action_form
                invalid_statement_id = getattr(statement, "pk", None)
            elif action == "finalize" and action_form is not None:
                invalid_finalize_form = action_form
            elif action == "void" and action_form is not None:
                invalid_void_form = action_form
            elif action == "resolve_exception" and action_form is not None:
                invalid_exception_form = action_form
                invalid_exception_id = getattr(exception, "pk", None)
            if not ajax_statutory_review:
                _message_error(request, error, action_form)
        if all(form is None for form in (
            invalid_statutory_form,
            invalid_adjustment_form,
            invalid_exception_form,
            invalid_finalize_form,
            invalid_void_form,
        )):
            if not ajax_statutory_review:
                return redirect("payroll:run_detail", pk=run.pk)

    all_statement_query = run.statements.select_related("employee").prefetch_related(
        "lines", "time_entries", "statutory_assessments", "statutory_assessments__employee_line",
        "statutory_assessments__employer_line", "statutory_assessments__reviewed_by",
    )
    statement_query = all_statement_query
    statement_search = request.GET.get("q", "").strip()
    if statement_search:
        statement_query = statement_query.filter(
            Q(employee__first_name__icontains=statement_search)
            | Q(employee__last_name__icontains=statement_search)
            | Q(employee__employee_code__icontains=statement_search)
        )
    page_size = request.GET.get("page_size", "25")
    if page_size not in {"10", "25", "50"}:
        page_size = "25"
    open_statutory_statement_id = request.GET.get("review_statement", "")
    open_statutory_statement_id = int(open_statutory_statement_id) if open_statutory_statement_id.isdigit() else None
    paginator = Paginator(statement_query, int(page_size))
    page_number = request.GET.get('page')
    if invalid_statement_id or open_statutory_statement_id or (ajax_statutory_review and ajax_statement_id):
        ids = list(statement_query.values_list('pk', flat=True))
        target_statement_id = invalid_statement_id or open_statutory_statement_id or ajax_statement_id
        if target_statement_id in ids:
            page_number = ids.index(target_statement_id) // int(page_size) + 1
    statement_page = paginator.get_page(page_number)
    open_statutory_statement = None
    for statement in statement_page.object_list:
        statement.rule_profile_summary = _statement_rule_profile_summary(statement)
        statement.statutory_rows = statutory_review_rows(statement)
        statement.statutory_reviewed_count = sum(1 for row in statement.statutory_rows if row["current"])
        statement.statutory_total_count = len(statement.statutory_rows)
        statement.statutory_complete = all(row['current'] for row in statement.statutory_rows)
        statement.statutory_form = invalid_statutory_form if statement.pk == invalid_statement_id else StatutoryReviewForm(
            statement=statement, prefix=f'statutory-{statement.pk}')
        if statement.pk == (invalid_statement_id or open_statutory_statement_id):
            open_statutory_statement = statement
    statutory_pending_queue = []
    for index, statement in enumerate(all_statement_query):
        rows = statutory_review_rows(statement)
        reviewed_count = sum(1 for row in rows if row["current"])
        if reviewed_count != len(rows):
            statutory_pending_queue.append({
                "statement": statement,
                "reviewed_count": reviewed_count,
                "total_count": len(rows),
                "page_number": index // int(page_size) + 1,
            })
    statutory_pending = len(statutory_pending_queue)
    statutory_query = request.GET.get("stat_q", "").strip()
    if statutory_query:
        search_value = statutory_query.casefold()
        statutory_pending_queue = [
            item for item in statutory_pending_queue
            if search_value in item["statement"].employee.full_name.casefold()
            or search_value in item["statement"].employee.employee_code.casefold()
        ]
    statutory_page = Paginator(statutory_pending_queue, 10).get_page(request.GET.get("stat_page"))
    if ajax_statutory_review:
        ajax_statement = next((item for item in statement_page.object_list if item.pk == (invalid_statement_id or ajax_statement_id)), None)
        if ajax_statement is not None:
            statutory_html = render_to_string(
                "payroll/_statutory_review.html",
                {"statement": ajax_statement, "run": run},
                request=request,
            )
            statutory_error_message = ""
            if invalid_statutory_form is not None:
                for field_name, errors in invalid_statutory_form.errors.items():
                    if not errors:
                        continue
                    label = (
                        invalid_statutory_form.fields[field_name].label
                        if field_name in invalid_statutory_form.fields else
                        "Review"
                    )
                    statutory_error_message = f"{label}: {errors[0]}"
                    break
            return JsonResponse({
                "ok": invalid_statutory_form is None,
                "html": statutory_html,
                "message": "Statutory review saved for this employee and payroll period." if invalid_statutory_form is None else statutory_error_message or "Check the statutory review fields and try again.",
                "pending_count": statutory_pending,
                "reviewed_count": ajax_statement.statutory_reviewed_count,
                "total_count": ajax_statement.statutory_total_count,
                "complete": ajax_statement.statutory_complete,
            })
        return JsonResponse({
            "ok": False,
            "message": "The statutory review panel could not be refreshed. Refresh the page and try again.",
        }, status=409)
    exceptions = list(run.exceptions.select_related("employee", "timesheet", "resolution_line").order_by("superseded_at", "resolved_at", "employee__last_name", "pk"))
    exception_rows = [{
        "exception": item,
        "form": invalid_exception_form if item.pk == invalid_exception_id else PayrollExceptionResolutionForm(run=run, exception=item, prefix=f"exception-{item.pk}"),
    } for item in exceptions if not item.resolved_at and not item.superseded_at]
    active_exceptions = [item for item in exceptions if not item.resolved_at and not item.superseded_at]
    exception_counts = Counter(item.code for item in active_exceptions)
    exception_labels = {
        "MONTHLY_CALCULATION_NOT_CONFIGURED": ("Monthly calculation not configured", "Employees require a compensation or payroll-basis review."),
        "MONTHLY_INPUT_NOT_SUPPORTED": ("Monthly calculation not supported", "Change this employee to a supported hourly or daily compensation method, or exclude them from this run."),
        "NO_ATTENDANCE": ("Missing attendance", "No approved attendance or reviewed period input was found."),
        "NO_PAYROLL_TIME": ("Missing attendance", "No approved attendance or reviewed period input was found."),
        "TIMESHEET_REJECTED": ("Rejected timesheet", "Review the source timesheet and acknowledge the exclusion."),
        "NIGHT_PREMIUM_STACKING_REVIEW": ("Night premium review", "Record a reviewed earning line before finalization."),
    }
    for item in exceptions:
        item.display_label = exception_labels.get(
            item.code,
            (item.code.replace("_", " ").title(), "Review this payroll exception."),
        )[0]
    exception_summary = []
    for code, count in exception_counts.most_common():
        label, description = exception_labels.get(code, (code.replace("_", " ").title(), "Review this payroll exception."))
        exception_summary.append({"code": code, "label": label, "description": description, "count": count})
    active_exception_by_employee = Counter(item.employee_id for item in active_exceptions if item.employee_id)
    for statement in statement_page.object_list:
        statement.statement_exception_count = active_exception_by_employee.get(statement.employee_id, 0)
        statement.statement_status = "Blocked" if statement.statement_exception_count > 1 else ("Needs review" if statement.statement_exception_count else "Ready")
        snapshot = statement.snapshot or {}
        compensation_versions = snapshot.get("compensation_versions") or {}
        first_compensation = next(iter(compensation_versions.values()), {}) if isinstance(compensation_versions, dict) else {}
        basis = snapshot.get("pay_basis") or first_compensation.get("basis") or ""
        statement.pay_basis = {"HOURLY": "Hourly", "DAILY": "Daily", "MONTHLY": "Monthly"}.get(basis, basis.title() if basis else "—")
    adjustment_form = invalid_adjustment_form or PayrollAdjustmentForm(organization=organization, initial={"effective_date": run.period_start})
    manual_lines = PayrollLine.objects.filter(
        statement__run=run,
        source="MANUAL",
    ).select_related("statement__employee", "created_by").prefetch_related(
        "exception_resolutions",
    ).order_by("-effective_date", "-created_at")
    totals = run.statements.aggregate(
        gross=Sum("gross_amount"), deductions=Sum("deduction_amount"),
        contributions=Sum("employer_contribution_amount"), net=Sum("net_amount"),
    )
    context = {
        "organization": organization,
        "run": run,
        "statements": statement_page,
        "exceptions": exceptions,
        "exception_rows": exception_rows,
        "unresolved_exception_count": sum(1 for item in exceptions if not item.resolved_at and not item.superseded_at),
        "preview_history": run.calculation_previews.all()[:5],
        "adjustment_form": adjustment_form,
        "manual_lines": manual_lines,
        "manual_line_form_invalid": invalid_adjustment_form is not None,
        "exception_summary": exception_summary,
        "statement_search": statement_search,
        "statement_page_size": page_size,
        "page_querystring": _page_querystring(request),
        "statutory_pending_count": statutory_pending,
        "statutory_pending_queue": statutory_page,
        "statutory_query": statutory_query,
        "open_statutory_statement_id": open_statutory_statement_id,
        "open_statutory_statement": open_statutory_statement,
        "finalize_form": invalid_finalize_form or FinalizePayrollForm(),
        "void_form": invalid_void_form or VoidPayrollForm(),
        "finalize_form_invalid": invalid_finalize_form is not None,
        "void_form_invalid": invalid_void_form is not None,
        "totals": {key: value or Decimal("0.00") for key, value in totals.items()},
    }
    context.update(_statutory_workspace_context(run, request))
    context["statutory_bulk_form_invalid"] = False
    return render(request, "payroll/run_detail.html", context)


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
    writer.writerow(["Employee code", "Employee", "Rule profiles", "Period start", "Period end", "Pay date", "Pay frequency", "Currency", "Basic pay", "Overtime premium", "Night differential", "Holiday premium", "Allowances", "Other earnings", "Employee deductions", "Employer contributions", "Gross pay", "Net pay"])
    for statement in run.statements.select_related("employee").prefetch_related("lines"):
        grouped = {kind: Decimal("0.00") for kind in PayrollLine.Kind.values}
        for line in statement.lines.all():
            grouped[line.kind] += line.amount
        basic = sum((line.amount for line in statement.lines.all() if line.code == "REGULAR_PAY"), Decimal("0.00"))
        overtime = sum((line.amount for line in statement.lines.all() if line.code == "OVERTIME_PREMIUM"), Decimal("0.00"))
        night = sum((line.amount for line in statement.lines.all() if line.code == "NIGHT_DIFFERENTIAL"), Decimal("0.00"))
        holiday = sum((line.amount for line in statement.lines.all() if line.code == "DAY_PREMIUM"), Decimal("0.00"))
        allowances = sum((line.amount for line in statement.lines.all() if line.kind == PayrollLine.Kind.EARNING and line.source == "CALCULATED_COMPONENT"), Decimal("0.00"))
        writer.writerow([
            _csv_cell(statement.employee.employee_code), _csv_cell(statement.employee.full_name), _csv_cell(_statement_rule_profile_summary(statement)),
            run.period_start.isoformat(), run.period_end.isoformat(), run.pay_date.isoformat(), run.get_pay_frequency_display(), run.currency,
            f"{basic:.2f}", f"{overtime:.2f}", f"{night:.2f}", f"{holiday:.2f}", f"{allowances:.2f}",
            f"{grouped[PayrollLine.Kind.EARNING] - basic - overtime - night - holiday - allowances:.2f}",
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
    try:
        current_year = timezone.localdate(ZoneInfo(employee.organization.timezone)).year
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        current_year = timezone.localdate().year
    statements_this_year = statements.filter(run__pay_date__year=current_year).count()
    latest_statement = statements.first()
    page = Paginator(statements, 20).get_page(request.GET.get("page"))
    record_event(organization=employee.organization, actor=request.user, action=AuditEvent.Action.PAYROLL_STATEMENT_ACCESSED, target_type="payroll_history", target_id=employee.pk, summary="Viewed employee payroll history.", metadata={"page": page.number})
    return render(request, "payroll/my_statements.html", {
        "organization": employee.organization,
        "page": page,
        "statements_this_year": statements_this_year,
        "latest_statement": latest_statement,
    })


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
    statement.rule_profile_summary = _statement_rule_profile_summary(statement)
    record_event(organization=employee.organization, actor=request.user, action=AuditEvent.Action.PAYROLL_STATEMENT_ACCESSED, target_type="payroll_statement", target_id=statement.pk, summary=f"Viewed finalized payslip for {statement.run.reference}.")
    return render(request, "payroll/statement.html", {"organization": employee.organization, "statement": statement, "printable": True})
