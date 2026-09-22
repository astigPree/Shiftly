from decimal import Decimal
from datetime import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class PayrollSettings(models.Model):
    class Frequency(models.TextChoices):
        WEEKLY = "WEEKLY", "Weekly"
        SEMI_MONTHLY = "SEMI_MONTHLY", "Semi-monthly"
        MONTHLY = "MONTHLY", "Monthly"

    organization = models.OneToOneField(
        "organizations.Organization", on_delete=models.PROTECT, related_name="payroll_settings"
    )
    country_code = models.CharField(max_length=2, default="PH", choices=[("PH", "Philippines")])
    currency = models.CharField(max_length=3, default="PHP", choices=[("PHP", "Philippine peso (PHP)")])
    frequency = models.CharField(max_length=16, choices=Frequency.choices, default=Frequency.SEMI_MONTHLY)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        self.country_code = self.country_code.strip().upper()
        self.currency = self.currency.strip().upper()
        if len(self.country_code) != 2:
            raise ValidationError({"country_code": "Enter a two-letter country code."})
        if len(self.currency) != 3:
            raise ValidationError({"currency": "Enter a three-letter currency code."})
        if self.country_code != "PH" or self.currency != "PHP":
            raise ValidationError("The first payroll release supports Philippine payroll in PHP only.")

    def __str__(self):
        return f"{self.organization.name} payroll settings"


class PayrollRuleProfile(models.Model):
    """Reusable named payroll policy used by one or more employees."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="payroll_rule_profiles"
    )
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_rule_profiles_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="payroll_rule_profile_org_code_unique"),
            models.UniqueConstraint(
                fields=["organization"], condition=Q(is_default=True),
                name="payroll_rule_profile_one_default",
            ),
        ]

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip().lower()
        self.name = (self.name or "").strip()
        if not self.code:
            raise ValidationError({"code": "Enter a profile code."})
        if not self.name:
            raise ValidationError({"name": "Enter a profile name."})
        if self.is_default and not self.active:
            raise ValidationError({"active": "The organization default profile must remain active."})
        if self.organization_id and self.is_default:
            conflict = type(self).objects.filter(
                organization_id=self.organization_id, is_default=True,
            ).exclude(pk=self.pk)
            if conflict.exists():
                raise ValidationError({"is_default": "This organization already has a default payroll rule profile."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


class PayrollRuleSet(models.Model):
    """Effective-dated rules supplied and reviewed by the employer's payroll adviser."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="payroll_rule_sets"
    )
    rule_profile = models.ForeignKey(
        PayrollRuleProfile, on_delete=models.PROTECT, null=True, blank=True,
        related_name="rule_versions",
        help_text="Reusable payroll rule profile. Legacy rows are migrated to the organization default profile.",
    )
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    regular_day_minutes = models.PositiveSmallIntegerField(default=480)
    overtime_multiplier = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal("1.250"))
    rest_day_multiplier = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal("1.300"))
    rest_day_overtime_multiplier = models.DecimalField(max_digits=5, decimal_places=3, default=Decimal("1.690"))
    night_start = models.TimeField(default=time(22, 0))
    night_end = models.TimeField(default=time(6, 0))
    night_differential_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.1000"))
    source_references = models.TextField(
        blank=True,
        help_text="Official source links and the review evidence for this version of the rules.",
    )
    reviewed_by = models.CharField(max_length=160, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_rule_sets_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["rule_profile", "effective_from"], name="payroll_rule_profile_effective_unique"),
            models.CheckConstraint(check=Q(regular_day_minutes__gt=0), name="payroll_rule_day_minutes_positive"),
            models.CheckConstraint(check=Q(overtime_multiplier__gte=1), name="payroll_rule_ot_multiplier_valid"),
            models.CheckConstraint(check=Q(rest_day_multiplier__gte=1), name="payroll_rule_rest_multiplier_valid"),
            models.CheckConstraint(check=Q(rest_day_overtime_multiplier__gte=1), name="payroll_rule_rest_ot_valid"),
            models.CheckConstraint(check=Q(night_differential_rate__gte=0), name="payroll_rule_night_rate_nonneg"),
            models.CheckConstraint(
                check=Q(effective_until__isnull=True) | Q(effective_until__gte=models.F("effective_from")),
                name="payroll_rule_dates_valid",
            ),
        ]
        indexes = [models.Index(fields=["organization", "effective_from"], name="payroll_rule_org_from_idx")]

    def clean(self):
        super().clean()
        if self.rule_profile_id and self.organization_id and self.rule_profile.organization_id != self.organization_id:
            raise ValidationError({"rule_profile": "The rule profile must belong to the same organization."})
        if self.night_start and self.night_end and self.night_start == self.night_end:
            raise ValidationError({"night_end": "Night differential start and end times must be different."})
        if self.effective_from and self.effective_until and self.effective_until < self.effective_from:
            raise ValidationError({"effective_until": "End date must be on or after the effective date."})
        if self.effective_from and (self.rule_profile_id or self.organization_id):
            scope = {"rule_profile_id": self.rule_profile_id} if self.rule_profile_id else {"organization_id": self.organization_id, "rule_profile__isnull": True}
            overlaps = type(self).objects.filter(**scope).exclude(pk=self.pk).filter(
                Q(effective_until__isnull=True) | Q(effective_until__gte=self.effective_from)
            )
            if self.effective_until:
                overlaps = overlaps.filter(effective_from__lte=self.effective_until)
            if overlaps.exists():
                raise ValidationError({"effective_from": "Rule dates cannot overlap another rule version."})

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            changed_fields = [
                field for field in (
                    "effective_from", "effective_until", "regular_day_minutes", "overtime_multiplier",
                    "rest_day_multiplier", "rest_day_overtime_multiplier", "night_start", "night_end",
                    "night_differential_rate", "source_references", "reviewed_by", "reviewed_at", "rule_profile_id",
                ) if getattr(previous, field) != getattr(self, field)
            ]
            may_close = (
                previous.reviewed
                and changed_fields == ["effective_until"]
                and previous.effective_until is None
                and self.effective_until is not None
                and self.effective_until >= previous.effective_from
            )
            if previous.reviewed and changed_fields and not may_close:
                raise ValidationError("Reviewed payroll rules are immutable. Add a new effective-dated version.")
        return super().save(*args, **kwargs)

    @property
    def reviewed(self):
        return bool(self.reviewed_by.strip() and self.reviewed_at and self.source_references.strip())

    @property
    def regular_day_hours(self):
        return Decimal(self.regular_day_minutes) / Decimal("60")

    @property
    def night_differential_percent(self):
        return self.night_differential_rate * Decimal("100")

    def __str__(self):
        profile = f" for {self.rule_profile.name}" if self.rule_profile_id else ""
        return f"Payroll rules from {self.effective_from}{profile}"


class EmployeePayProfile(models.Model):
    """The first implementation supports hourly-paid employees in the Philippines."""

    employee = models.OneToOneField(
        "employees.Employee", on_delete=models.PROTECT, related_name="payroll_profile"
    )
    work_location = models.CharField(max_length=180, blank=True)
    payroll_region = models.CharField(max_length=80, blank=True)
    payroll_timezone = models.CharField(max_length=64, blank=True, help_text="IANA timezone for the employee's actual work location, such as Asia/Manila. Blank uses the organization timezone.")
    wage_order_reference = models.CharField(max_length=255, blank=True)
    minimum_wage_confirmed = models.BooleanField(default=False)
    night_differential_eligible = models.BooleanField(default=False)
    rest_day = models.PositiveSmallIntegerField(null=True, blank=True, choices=[
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
        (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ])
    rank_and_file = models.BooleanField(default=True)
    active_for_payroll = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["active_for_payroll", "employee"], name="payroll_profile_active_idx")]

    def clean(self):
        super().clean()
        self.payroll_timezone = (self.payroll_timezone or "").strip()
        if self.payroll_timezone:
            try:
                ZoneInfo(self.payroll_timezone)
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                raise ValidationError({"payroll_timezone": "Enter a valid IANA timezone, such as Asia/Manila."})

    def save(self, *args, **kwargs):
        if self.pk:
            prior = type(self).objects.get(pk=self.pk)
            if prior.payroll_timezone != self.payroll_timezone and PayrollStatement.objects.filter(
                employee_id=self.employee_id,
                run__status=PayrollRun.Status.FINALIZED,
            ).exists():
                raise ValidationError("An employee's payroll timezone cannot be changed after a finalized statement. Effective-dated work-location timezone history is not yet supported.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Payroll profile for {self.employee.full_name}"


class PayrollRuleAssignment(models.Model):
    """An employee-specific, effective-dated override of the organization default profile."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="payroll_rule_assignments"
    )
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT, related_name="payroll_rule_assignments"
    )
    rule_profile = models.ForeignKey(
        PayrollRuleProfile, on_delete=models.PROTECT, related_name="employee_assignments"
    )
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_rule_assignments_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "effective_from"], name="payroll_rule_assignment_emp_from_unique"),
            models.CheckConstraint(
                check=Q(effective_until__isnull=True) | Q(effective_until__gte=models.F("effective_from")),
                name="payroll_rule_assignment_dates_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "employee", "effective_from"], name="payrule_assign_emp_idx"),
            models.Index(fields=["rule_profile", "effective_from"], name="payrule_assign_profile_idx"),
        ]

    def clean(self):
        super().clean()
        if self.effective_from and self.effective_until and self.effective_until < self.effective_from:
            raise ValidationError({"effective_until": "End date must be on or after the effective date."})
        if self.employee_id and self.organization_id and self.employee.organization_id != self.organization_id:
            raise ValidationError({"employee": "The employee must belong to the same organization."})
        if self.rule_profile_id and self.organization_id and self.rule_profile.organization_id != self.organization_id:
            raise ValidationError({"rule_profile": "The rule profile must belong to the same organization."})
        if self.employee_id and self.effective_from:
            overlaps = type(self).objects.filter(
                employee_id=self.employee_id,
                effective_from__lte=(self.effective_until or self.effective_from),
            ).exclude(pk=self.pk).filter(
                Q(effective_until__isnull=True) | Q(effective_until__gte=self.effective_from)
            )
            if overlaps.exists():
                raise ValidationError({"effective_from": "Assignment dates cannot overlap another assignment for this employee."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.full_name}: {self.rule_profile.name} from {self.effective_from}"


class EmployeePayRate(models.Model):
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT, related_name="pay_rates"
    )
    hourly_rate = models.DecimalField(max_digits=12, decimal_places=4)
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    change_reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="employee_pay_rates_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-pk"]
        constraints = [
            models.CheckConstraint(check=Q(hourly_rate__gt=0), name="payroll_rate_positive"),
            models.UniqueConstraint(fields=["employee", "effective_from"], name="payroll_rate_emp_effective_unique"),
            models.CheckConstraint(
                check=Q(effective_until__isnull=True) | Q(effective_until__gte=models.F("effective_from")),
                name="payroll_rate_dates_valid",
            ),
        ]
        indexes = [models.Index(fields=["employee", "effective_from"], name="payroll_rate_emp_from_idx")]

    def clean(self):
        super().clean()
        if self.effective_from and self.effective_until and self.effective_until < self.effective_from:
            raise ValidationError({"effective_until": "End date must be on or after the effective date."})
        if self.employee_id and self.effective_from:
            overlaps = type(self).objects.filter(employee_id=self.employee_id).exclude(pk=self.pk).filter(
                Q(effective_until__isnull=True) | Q(effective_until__gte=self.effective_from)
            )
            if self.effective_until:
                overlaps = overlaps.filter(effective_from__lte=self.effective_until)
            if overlaps.exists():
                raise ValidationError({"effective_from": "Rate dates cannot overlap another rate version."})

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            may_close = (
                previous.effective_until is None
                and self.effective_until is not None
                and self.effective_until >= previous.effective_from
                and all(
                    getattr(previous, field) == getattr(self, field)
                    for field in ("employee_id", "hourly_rate", "effective_from", "change_reason", "created_by_id")
                )
            )
            if not may_close:
                raise ValidationError("Pay-rate history is append-only. A current rate may only be closed when a new rate starts.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Pay-rate history is append-only.")

    def __str__(self):
        return f"{self.employee.full_name}: {self.hourly_rate} from {self.effective_from}"


class PayrollHoliday(models.Model):
    class Kind(models.TextChoices):
        REGULAR = "REGULAR", "Regular holiday"
        SPECIAL = "SPECIAL", "Special non-working day"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="payroll_holidays"
    )
    date = models.DateField()
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    worked_multiplier = models.DecimalField(max_digits=5, decimal_places=3)
    overtime_multiplier = models.DecimalField(max_digits=5, decimal_places=3)
    source_reference = models.CharField(max_length=255, blank=True)
    reviewed_by = models.CharField(max_length=160, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_holidays_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "date"], name="payroll_holiday_org_date_unique"),
            models.CheckConstraint(check=Q(worked_multiplier__gte=1), name="payroll_holiday_multiplier_valid"),
            models.CheckConstraint(check=Q(overtime_multiplier__gte=1), name="payroll_holiday_ot_valid"),
        ]

    @property
    def reviewed(self):
        return bool(self.reviewed_by.strip() and self.reviewed_at and self.source_reference.strip())

    def __str__(self):
        return f"{self.name} · {self.date}"


class PayrollRun(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        REVIEW = "REVIEW", "In review"
        FINALIZED = "FINALIZED", "Finalized"
        VOID = "VOID", "Voided"

    class RunType(models.TextChoices):
        REGULAR = "REGULAR", "Regular"
        OFF_CYCLE = "OFF_CYCLE", "Off-cycle"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="payroll_runs"
    )
    reference = models.CharField(max_length=40)
    idempotency_key = models.UUIDField(default=uuid.uuid4, editable=False)
    run_type = models.CharField(max_length=12, choices=RunType.choices, default=RunType.REGULAR)
    parent_run = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="adjustment_runs")
    period_start = models.DateField()
    period_end = models.DateField()
    pay_date = models.DateField()
    pay_frequency = models.CharField(
        max_length=16,
        choices=PayrollSettings.Frequency.choices,
        default=PayrollSettings.Frequency.SEMI_MONTHLY,
    )
    currency = models.CharField(max_length=3, default="PHP")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_runs_prepared")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="payroll_runs_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="payroll_runs_finalized")
    finalized_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "reference"], name="payroll_run_org_reference_unique"),
            models.UniqueConstraint(fields=["organization", "idempotency_key"], name="payroll_run_org_idempotency_unique"),
            models.CheckConstraint(check=Q(period_end__gte=models.F("period_start")), name="payroll_run_period_valid"),
            models.CheckConstraint(check=Q(status__in=["DRAFT", "REVIEW", "FINALIZED", "VOID"]), name="payroll_run_status_valid"),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "period_start"], name="payroll_run_org_status_idx"),
            models.Index(fields=["organization", "period_start", "period_end"], name="payroll_run_org_period_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            prior = type(self).objects.get(pk=self.pk)
            if prior.status in (self.Status.FINALIZED, self.Status.VOID):
                raise ValidationError("Finalized and void payroll runs are immutable.")
            immutable = ("organization_id", "reference", "idempotency_key", "run_type", "parent_run_id", "period_start", "period_end", "pay_date", "pay_frequency", "currency", "prepared_by_id")
            if any(getattr(prior, name) != getattr(self, name) for name in immutable):
                raise ValidationError("Payroll run identity and period cannot be changed.")
            allowed = {
                self.Status.DRAFT: {self.Status.DRAFT, self.Status.REVIEW, self.Status.VOID},
                self.Status.REVIEW: {self.Status.REVIEW, self.Status.DRAFT, self.Status.FINALIZED, self.Status.VOID},
            }
            if self.status not in allowed.get(prior.status, {prior.status}):
                raise ValidationError("This payroll run transition is not allowed.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError("Only draft payroll runs can be deleted.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} · {self.period_start}–{self.period_end}"


class PayrollStatement(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="statements")
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="payroll_statements")
    gross_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    deduction_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    employer_contribution_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__last_name", "employee__first_name", "pk"]
        constraints = [models.UniqueConstraint(fields=["run", "employee"], name="payroll_statement_run_employee_unique")]
        indexes = [models.Index(fields=["employee", "run"], name="payroll_statement_emp_run_idx")]

    def clean(self):
        super().clean()
        if self.run_id and self.employee_id and self.run.organization_id != self.employee.organization_id:
            raise ValidationError({"employee": "The employee must belong to the payroll run's organization."})

    def save(self, *args, **kwargs):
        if self.run_id and self.run.status != PayrollRun.Status.DRAFT:
            raise ValidationError("Statements can only change while the payroll run is a draft.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.run.status != PayrollRun.Status.DRAFT:
            raise ValidationError("Only statements in a draft run can be removed.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.full_name} · {self.run.reference}"


class PayrollLine(models.Model):
    class Kind(models.TextChoices):
        EARNING = "EARNING", "Earning"
        DEDUCTION = "DEDUCTION", "Deduction"
        EMPLOYER_CONTRIBUTION = "EMPLOYER_CONTRIBUTION", "Employer contribution"

    statement = models.ForeignKey(PayrollStatement, on_delete=models.PROTECT, related_name="lines")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    code = models.CharField(max_length=32)
    label = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    effective_date = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=24, default="CALCULATED")
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_lines_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "code", "pk"]
        constraints = [models.CheckConstraint(check=Q(amount__gte=0), name="payroll_line_amount_nonneg")]

    def save(self, *args, **kwargs):
        if self.statement_id and self.statement.run.status != PayrollRun.Status.DRAFT:
            raise ValidationError("Payroll lines can only change while the run is a draft.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.statement.run.status != PayrollRun.Status.DRAFT:
            raise ValidationError("Payroll lines can only be removed while the run is a draft.")
        return super().delete(*args, **kwargs)


class PayrollTimeEntry(models.Model):
    statement = models.ForeignKey(PayrollStatement, on_delete=models.PROTECT, related_name="time_entries")
    timesheet = models.ForeignKey("timesheets.Timesheet", on_delete=models.PROTECT, related_name="payroll_entries")
    work_date = models.DateField()
    payable_minutes = models.PositiveIntegerField()
    night_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    rate_snapshot = models.DecimalField(max_digits=12, decimal_places=4)
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["statement", "timesheet"], name="payroll_time_statement_timesheet_unique")]

    def clean(self):
        super().clean()
        if self.statement_id and self.timesheet_id:
            if self.statement.run.organization_id != self.timesheet.organization_id:
                raise ValidationError("Timesheet and payroll statement must belong to the same organization.")
            if self.statement.employee_id != self.timesheet.employee_id:
                raise ValidationError("Timesheet and payroll statement must belong to the same employee.")

    def save(self, *args, **kwargs):
        if self.statement_id and self.statement.run.status != PayrollRun.Status.DRAFT:
            raise ValidationError("Payroll time entries can only change while the run is a draft.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.statement.run.status != PayrollRun.Status.DRAFT:
            raise ValidationError("Payroll time entries can only be removed while the run is a draft.")
        return super().delete(*args, **kwargs)


class PayrollException(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="exceptions")
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, null=True, blank=True, related_name="payroll_exceptions")
    timesheet = models.ForeignKey("timesheets.Timesheet", on_delete=models.PROTECT, null=True, blank=True, related_name="payroll_exceptions")
    code = models.CharField(max_length=40)
    description = models.CharField(max_length=255)
    work_date = models.DateField(null=True, blank=True)
    resolution_line = models.ForeignKey("payroll.PayrollLine", on_delete=models.PROTECT, null=True, blank=True, related_name="exception_resolutions")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="payroll_exceptions_resolved")
    resolution_note = models.CharField(max_length=500, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["resolved_at", "employee__last_name", "pk"]

    @property
    def is_resolved(self):
        return self.resolved_at is not None

    @property
    def needs_manual_pay_line(self):
        return self.code in {"NIGHT_PREMIUM_STACKING_REVIEW", "HOLIDAY_REST_DAY_STACKING", "HOLIDAY_NOT_REVIEWED"}

    def save(self, *args, **kwargs):
        if self.run_id and self.run.status != PayrollRun.Status.DRAFT:
            raise ValidationError("Payroll exceptions can only change while the run is a draft.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.run.status != PayrollRun.Status.DRAFT:
            raise ValidationError("Payroll exceptions can only be removed while the run is a draft.")
        return super().delete(*args, **kwargs)


class PayrollCalculationSnapshot(models.Model):
    """Append-only audit snapshot of each draft calculation preview."""

    run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="calculation_previews")
    sequence = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_previews_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sequence"]
        constraints = [models.UniqueConstraint(fields=["run", "sequence"], name="payroll_preview_run_sequence_unique")]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Payroll calculation snapshots are append-only.")
        if self.run_id and self.run.status != PayrollRun.Status.DRAFT:
            raise ValidationError("A calculation preview can only be recorded on a draft run.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Payroll calculation snapshots are append-only.")
