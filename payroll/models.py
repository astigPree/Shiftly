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


class StatutoryRuleVersion(models.Model):
    """Reviewer-gated version of one Philippine statutory/tax rule table."""

    class Agency(models.TextChoices):
        SSS = "SSS", "SSS"
        PHILHEALTH = "PHILHEALTH", "PhilHealth"
        PAGIBIG = "PAGIBIG", "Pag-IBIG"
        BIR = "BIR", "BIR withholding"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="statutory_rule_versions",
    )
    agency = models.CharField(max_length=12, choices=Agency.choices)
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    basis = models.CharField(max_length=120, blank=True)
    employee_rate = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    employer_rate = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    minimum_base = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    maximum_base = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    bracket_table = models.JSONField(default=dict, blank=True)
    rounding_method = models.CharField(max_length=80, blank=True)
    source_reference = models.TextField(blank=True)
    reviewed_by = models.CharField(max_length=160, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="statutory_rule_versions_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="statutory_rule_versions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["agency", "-effective_from", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "agency", "effective_from"],
                name="payroll_stat_rule_org_agency_from_unique",
            ),
            models.CheckConstraint(
                check=Q(effective_until__isnull=True) | Q(effective_until__gte=models.F("effective_from")),
                name="payroll_stat_rule_dates_valid",
            ),
            models.CheckConstraint(
                check=Q(minimum_base__isnull=True) | Q(minimum_base__gte=0),
                name="payroll_stat_rule_min_base_nonneg",
            ),
            models.CheckConstraint(
                check=Q(maximum_base__isnull=True) | Q(maximum_base__gte=0),
                name="payroll_stat_rule_max_base_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "agency", "effective_from"], name="payroll_stat_rule_lookup_idx"),
        ]

    def clean(self):
        super().clean()
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValidationError({"effective_until": "End date must be on or after the effective date."})
        if self.minimum_base is not None and self.maximum_base is not None and self.maximum_base < self.minimum_base:
            raise ValidationError({"maximum_base": "Maximum base must be on or above the minimum base."})
        overlaps = type(self).objects.filter(
            organization_id=self.organization_id, agency=self.agency,
        ).exclude(pk=self.pk).filter(
            Q(effective_until__isnull=True) | Q(effective_until__gte=self.effective_from)
        )
        if self.effective_until:
            overlaps = overlaps.filter(effective_from__lte=self.effective_until)
        if overlaps.exists():
            raise ValidationError({"effective_from": "Statutory rule dates cannot overlap another version for this agency."})

    def save(self, *args, **kwargs):
        if self.pk:
            prior = type(self).objects.get(pk=self.pk)
            if prior.approved_at and any(
                getattr(prior, field) != getattr(self, field)
                for field in (
                    "agency", "effective_from", "effective_until", "basis", "employee_rate",
                    "employer_rate", "minimum_base", "maximum_base", "bracket_table",
                    "rounding_method", "source_reference", "reviewed_by", "reviewed_at",
                    "approved_by_id", "approved_at",
                )
            ):
                raise ValidationError("Approved statutory rules are immutable. Add a new effective-dated version.")
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def reviewed(self):
        return bool(self.reviewed_by.strip() and self.reviewed_at and self.source_reference.strip())

    @property
    def approved(self):
        return bool(self.reviewed and self.approved_by_id and self.approved_at)

    def __str__(self):
        return f"{self.get_agency_display()} rules from {self.effective_from}"


class EmployeePayProfile(models.Model):
    """Work-location and review controls shared by hourly and daily payroll."""

    class EmploymentStatus(models.TextChoices):
        REGULAR = "REGULAR", "Regular"
        PROBATION = "PROBATION", "Probation"
        PART_TIME = "PART_TIME", "Part-time"
        OTHER = "OTHER", "Other"

    class PayBasis(models.TextChoices):
        HOURLY = "HOURLY", "Hourly"
        DAILY = "DAILY", "Daily"
        MONTHLY = "MONTHLY", "Monthly"
        MIXED = "MIXED", "Mixed"

    employee = models.OneToOneField(
        "employees.Employee", on_delete=models.PROTECT, related_name="payroll_profile"
    )
    employment_status = models.CharField(
        max_length=16, choices=EmploymentStatus.choices, default=EmploymentStatus.REGULAR
    )
    pay_basis = models.CharField(
        max_length=8, choices=PayBasis.choices, default=PayBasis.HOURLY,
        help_text="The employee's primary payroll basis. Mixed pay uses dated compensation and components.",
    )
    minimum_daily_rate = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True,
        help_text="Reviewer-entered statutory/minimum daily base for the applicable wage region.",
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
        if self.minimum_daily_rate is not None and self.minimum_daily_rate < 0:
            raise ValidationError({"minimum_daily_rate": "Minimum daily rate cannot be negative."})
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


class EmployeeStatutoryCoverage(models.Model):
    """Effective-dated employee coverage and registration evidence.

    Coverage is deliberately separate from employment status.  A Regular or
    Probation label never silently creates an exemption or a contribution
    registration.
    """

    class Agency(models.TextChoices):
        SSS = "SSS", "SSS"
        PHILHEALTH = "PHILHEALTH", "PhilHealth"
        PAGIBIG = "PAGIBIG", "Pag-IBIG"
        BIR = "BIR", "BIR withholding"

    class Status(models.TextChoices):
        REVIEW = "REVIEW", "Needs review"
        COVERED = "COVERED", "Covered"
        EXEMPT = "EXEMPT", "Exempt"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="employee_statutory_coverages",
    )
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="statutory_coverages",
    )
    agency = models.CharField(max_length=12, choices=Agency.choices)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.REVIEW)
    identifier = models.CharField(
        max_length=64, blank=True,
        help_text="Sensitive government identifier. Restrict access at the view and audit layers.",
    )
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    exemption_reason = models.CharField(max_length=255, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    reviewed_by = models.CharField(max_length=160, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="employee_statutory_coverages_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["agency", "-effective_from", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "agency", "effective_from"],
                name="payroll_stat_coverage_emp_agency_from_unique",
            ),
            models.CheckConstraint(
                check=Q(effective_until__isnull=True) | Q(effective_until__gte=models.F("effective_from")),
                name="payroll_stat_coverage_dates_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "employee", "agency", "effective_from"], name="payroll_stat_cov_lookup_idx"),
        ]

    def clean(self):
        super().clean()
        if self.employee_id and self.organization_id and self.employee.organization_id != self.organization_id:
            raise ValidationError({"employee": "The employee must belong to the same organization."})
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValidationError({"effective_until": "End date must be on or after the effective date."})
        if self.status == self.Status.EXEMPT:
            if not self.exemption_reason.strip():
                raise ValidationError({"exemption_reason": "Record the approved exemption reason."})
            if not self.source_reference.strip():
                raise ValidationError({"source_reference": "Record the source for the exemption."})
        overlaps = type(self).objects.filter(
            employee_id=self.employee_id, agency=self.agency,
        ).exclude(pk=self.pk).filter(
            Q(effective_until__isnull=True) | Q(effective_until__gte=self.effective_from)
        )
        if self.effective_until:
            overlaps = overlaps.filter(effective_from__lte=self.effective_until)
        if overlaps.exists():
            raise ValidationError({"effective_from": "Coverage dates cannot overlap another version for this agency."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def reviewed(self):
        return bool(self.reviewed_by.strip() and self.reviewed_at and self.source_reference.strip())

    def __str__(self):
        return f"{self.employee.full_name}: {self.get_agency_display()} ({self.get_status_display()})"


class EmployeePaymentMethod(models.Model):
    """Effective-dated payment preference without storing bank credentials."""

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer / payroll account"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="employee_payment_methods",
    )
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="payment_methods",
    )
    method = models.CharField(max_length=16, choices=Method.choices)
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    account_reference = models.CharField(
        max_length=255, blank=True,
        help_text="Optional payroll-owner reference; do not store raw bank credentials here.",
    )
    source_reference = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="employee_payment_methods_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "effective_from"],
                name="payroll_payment_method_emp_from_unique",
            ),
            models.CheckConstraint(
                check=Q(effective_until__isnull=True) | Q(effective_until__gte=models.F("effective_from")),
                name="payroll_payment_method_dates_valid",
            ),
        ]

    def clean(self):
        super().clean()
        if self.employee_id and self.organization_id and self.employee.organization_id != self.organization_id:
            raise ValidationError({"employee": "The employee must belong to the same organization."})
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValidationError({"effective_until": "End date must be on or after the effective date."})
        overlaps = type(self).objects.filter(employee_id=self.employee_id).exclude(pk=self.pk).filter(
            Q(effective_until__isnull=True) | Q(effective_until__gte=self.effective_from)
        )
        if self.effective_until:
            overlaps = overlaps.filter(effective_from__lte=self.effective_until)
        if overlaps.exists():
            raise ValidationError({"effective_from": "Payment method dates cannot overlap another version."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class EmployeeObligation(models.Model):
    """An approved employee obligation whose balance changes only through a ledger."""

    class Kind(models.TextChoices):
        CASH_ADVANCE = "CASH_ADVANCE", "Cash advance"
        SSS_LOAN = "SSS_LOAN", "SSS loan"
        PAGIBIG_LOAN = "PAGIBIG_LOAN", "Pag-IBIG loan"
        COMPANY_LOAN = "COMPANY_LOAN", "Company loan"
        EMPLOYEE_CHARGE = "EMPLOYEE_CHARGE", "Employee charge"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        SETTLED = "SETTLED", "Settled"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="employee_obligations",
    )
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="payroll_obligations",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    reference = models.CharField(max_length=80)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2)
    as_of_date = models.DateField()
    installment_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    priority = models.PositiveIntegerField(default=100)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    source_reference = models.CharField(max_length=255)
    reviewed_by = models.CharField(max_length=160)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="employee_obligations_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["priority", "employee_id", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"], name="payroll_obligation_org_reference_unique"
            ),
            models.CheckConstraint(check=Q(opening_balance__gte=0), name="payroll_obligation_opening_nonneg"),
            models.CheckConstraint(
                check=Q(installment_amount__isnull=True) | Q(installment_amount__gt=0),
                name="payroll_obligation_installment_positive",
            ),
        ]

    def clean(self):
        super().clean()
        if self.employee_id and self.organization_id and self.employee.organization_id != self.organization_id:
            raise ValidationError({"employee": "The employee must belong to the same organization."})
        if self.installment_amount is not None and self.installment_amount <= 0:
            raise ValidationError({"installment_amount": "Installment amount must be positive."})
        if not self.source_reference.strip():
            raise ValidationError({"source_reference": "Record the approved obligation source."})
        if not self.reviewed_by.strip():
            raise ValidationError({"reviewed_by": "Record who reviewed the obligation."})

    def save(self, *args, **kwargs):
        if self.pk:
            prior = type(self).objects.get(pk=self.pk)
            if any(
                getattr(prior, field) != getattr(self, field)
                for field in (
                    "organization_id", "employee_id", "kind", "reference", "opening_balance",
                    "as_of_date", "installment_amount", "starts_on", "priority", "source_reference",
                    "reviewed_by", "reviewed_at", "created_by_id",
                )
            ):
                raise ValidationError("Obligation terms are append-only. Use a ledger correction transaction.")
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def ledger_balance(self):
        posted = self.transactions.filter(status=EmployeeObligationTransaction.Status.POSTED).aggregate(
            total=models.Sum("amount")
        )["total"] or Decimal("0")
        return max(Decimal("0.00"), self.opening_balance - posted)

    def __str__(self):
        return f"{self.employee.full_name}: {self.reference}"


class EmployeeObligationTransaction(models.Model):
    """Append-only obligation ledger. Positive amounts reduce the balance."""

    class Kind(models.TextChoices):
        SCHEDULED_INSTALLMENT = "SCHEDULED_INSTALLMENT", "Scheduled installment"
        SKIPPED = "SKIPPED", "Skipped installment"
        EXTERNAL_REPAYMENT = "EXTERNAL_REPAYMENT", "External repayment"
        CORRECTION = "CORRECTION", "Correction"
        REVERSAL = "REVERSAL", "Reversal"
        FINAL_SETTLEMENT = "FINAL_SETTLEMENT", "Final settlement"

    class Status(models.TextChoices):
        PROPOSED = "PROPOSED", "Proposed"
        POSTED = "POSTED", "Posted"
        VOID = "VOID", "Voided"

    obligation = models.ForeignKey(
        EmployeeObligation, on_delete=models.PROTECT, related_name="transactions"
    )
    payroll_run = models.ForeignKey(
        "PayrollRun", on_delete=models.PROTECT, null=True, blank=True,
        related_name="obligation_transactions",
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Positive repayment reduces balance; a signed correction can restore it.",
    )
    transaction_date = models.DateField()
    reason = models.CharField(max_length=255)
    source_reference = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PROPOSED)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="employee_obligation_transactions_created",
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["transaction_date", "pk"]
        constraints = [
            models.CheckConstraint(
                check=Q(amount__gte=0) | Q(kind__in=["CORRECTION", "REVERSAL"]),
                name="payroll_obligation_tx_amount_signed_only_correction",
            ),
        ]

    def clean(self):
        super().clean()
        if self.payroll_run_id and self.obligation_id and self.payroll_run.organization_id != self.obligation.organization_id:
            raise ValidationError({"payroll_run": "The payroll run must belong to the obligation's organization."})
        if self.status == self.Status.POSTED and not self.posted_at:
            raise ValidationError({"posted_at": "Posted transactions require a posted timestamp."})
        if self.kind == self.Kind.SKIPPED and self.amount != 0:
            raise ValidationError({"amount": "A skipped installment must have a zero ledger amount."})

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Obligation transactions are append-only. Add a reversal or correction.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Obligation transactions are append-only. Add a reversal or correction.")


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
            ).exclude(pk=self.pk).filter(
                Q(effective_until__isnull=True) | Q(effective_until__gte=self.effective_from)
            )
            if self.effective_until:
                overlaps = overlaps.filter(effective_from__lte=self.effective_until)
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


class EmployeeCompensationVersion(models.Model):
    """Effective-dated compensation that can be hourly or daily.

    Legacy :class:`EmployeePayRate` rows remain valid.  The payroll resolver
    prefers the newest compensation version when one exists and otherwise
    falls back to the legacy hourly rate, so existing payroll history is not
    rewritten by introducing daily-paid employees.
    """

    class Basis(models.TextChoices):
        HOURLY = "HOURLY", "Hourly"
        DAILY = "DAILY", "Daily"
        MONTHLY = "MONTHLY", "Monthly"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="employee_compensation_versions"
    )
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT, related_name="compensation_versions"
    )
    basis = models.CharField(max_length=8, choices=Basis.choices, default=Basis.HOURLY)
    amount = models.DecimalField(max_digits=12, decimal_places=4)
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    regular_day_minutes = models.PositiveSmallIntegerField(default=480)
    currency = models.CharField(max_length=3, default="PHP")
    source_reference = models.CharField(max_length=255, blank=True)
    reviewed_by = models.CharField(max_length=160, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="employee_compensation_versions_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "effective_from"], name="payroll_compensation_emp_from_unique"),
            models.CheckConstraint(check=Q(amount__gt=0), name="payroll_compensation_amount_positive"),
            models.CheckConstraint(check=Q(regular_day_minutes__gt=0), name="payroll_compensation_day_minutes_positive"),
            models.CheckConstraint(
                check=Q(effective_until__isnull=True) | Q(effective_until__gte=models.F("effective_from")),
                name="payroll_compensation_dates_valid",
            ),
        ]
        indexes = [models.Index(fields=["employee", "effective_from"], name="payroll_comp_emp_from_idx")]

    def clean(self):
        super().clean()
        if self.employee_id and self.organization_id and self.employee.organization_id != self.organization_id:
            raise ValidationError({"employee": "The employee must belong to the same organization."})
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValidationError({"effective_until": "End date must be on or after the effective date."})
        if self.currency != "PHP":
            raise ValidationError({"currency": "The first payroll release supports PHP only."})
        if self.basis in {self.Basis.DAILY, self.Basis.MONTHLY} and (not self.source_reference.strip() or not self.reviewed_by.strip()):
            raise ValidationError({"source_reference": "Daily and monthly compensation require a reviewed source reference and reviewer."})
        overlaps = type(self).objects.filter(employee_id=self.employee_id).exclude(pk=self.pk).filter(
            Q(effective_until__isnull=True) | Q(effective_until__gte=self.effective_from)
        )
        if self.effective_until:
            overlaps = overlaps.filter(effective_from__lte=self.effective_until)
        if overlaps.exists():
            raise ValidationError({"effective_from": "Compensation dates cannot overlap another compensation version."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def reviewed(self):
        return bool(self.reviewed_by.strip() and self.reviewed_at and self.source_reference.strip())

    def __str__(self):
        return f"{self.employee.full_name}: {self.amount} ({self.get_basis_display()}) from {self.effective_from}"


class PayrollComponentDefinition(models.Model):
    """Organization-scoped, stable definition for recurring pay components."""

    class Kind(models.TextChoices):
        EARNING = "EARNING", "Earning"
        DEDUCTION = "DEDUCTION", "Deduction"
        EMPLOYER_CONTRIBUTION = "EMPLOYER_CONTRIBUTION", "Employer contribution"

    class Basis(models.TextChoices):
        PER_PERIOD = "PER_PERIOD", "Per payroll period"
        PER_WORKED_DAY = "PER_WORKED_DAY", "Per worked day"
        PER_PAYABLE_HOUR = "PER_PAYABLE_HOUR", "Per payable hour"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="payroll_component_definitions"
    )
    code = models.SlugField(max_length=40)
    label = models.CharField(max_length=120)
    kind = models.CharField(max_length=24, choices=Kind.choices, default=Kind.EARNING)
    basis = models.CharField(max_length=20, choices=Basis.choices, default=Basis.PER_PERIOD)
    deduct_undertime = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    description = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_component_definitions_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label", "pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="payroll_component_org_code_unique")]

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip().lower()
        self.label = (self.label or "").strip()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.label} ({self.code})"


class EmployeeComponentAssignment(models.Model):
    """Effective-dated amount for one employee and shared component definition."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="employee_component_assignments"
    )
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT, related_name="payroll_component_assignments"
    )
    component = models.ForeignKey(
        PayrollComponentDefinition, on_delete=models.PROTECT, related_name="employee_assignments"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=4)
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    basis = models.CharField(max_length=20, choices=PayrollComponentDefinition.Basis.choices, blank=True)
    deduct_undertime = models.BooleanField(null=True, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_component_assignments_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "component__label", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "component", "effective_from"], name="payroll_component_emp_from_unique"),
            models.CheckConstraint(check=Q(amount__gt=0), name="payroll_component_amount_positive"),
            models.CheckConstraint(
                check=Q(effective_until__isnull=True) | Q(effective_until__gte=models.F("effective_from")),
                name="payroll_component_dates_valid",
            ),
        ]
        indexes = [models.Index(fields=["employee", "effective_from"], name="payroll_comp_assign_emp_idx")]

    def clean(self):
        super().clean()
        if self.employee_id and self.organization_id and self.employee.organization_id != self.organization_id:
            raise ValidationError({"employee": "The employee must belong to the same organization."})
        if self.component_id and self.organization_id and self.component.organization_id != self.organization_id:
            raise ValidationError({"component": "The component must belong to the same organization."})
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValidationError({"effective_until": "End date must be on or after the effective date."})
        if self.basis and self.basis not in PayrollComponentDefinition.Basis.values:
            raise ValidationError({"basis": "Choose a valid component basis."})
        overlaps = type(self).objects.filter(employee_id=self.employee_id, component_id=self.component_id).exclude(pk=self.pk).filter(
            Q(effective_until__isnull=True) | Q(effective_until__gte=self.effective_from)
        )
        if self.effective_until:
            overlaps = overlaps.filter(effective_from__lte=self.effective_until)
        if overlaps.exists():
            raise ValidationError({"effective_from": "Component dates cannot overlap another assignment for this employee."})

    def save(self, *args, **kwargs):
        if not self.basis and self.component_id:
            self.basis = self.component.basis
        if self.deduct_undertime is None and self.component_id:
            self.deduct_undertime = self.component.deduct_undertime
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.full_name}: {self.component.label} from {self.effective_from}"


class PayrollPeriodInput(models.Model):
    """Reviewed date-level quantities for daily pay or imported registers."""

    class Mode(models.TextChoices):
        DAILY_REGISTER = "DAILY_REGISTER", "Daily register"
        ADJUSTMENT = "ADJUSTMENT", "Reviewed adjustment"
        PAID_ABSENCE = "PAID_ABSENCE", "Paid absence"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="payroll_period_inputs"
    )
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT, related_name="payroll_period_inputs"
    )
    period_start = models.DateField()
    period_end = models.DateField()
    work_date = models.DateField()
    worked_day_units = models.DecimalField(max_digits=7, decimal_places=3, default=Decimal("0"))
    planned_day_units = models.DecimalField(max_digits=7, decimal_places=3, default=Decimal("1"))
    undertime_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    night_minutes = models.PositiveIntegerField(default=0)
    holiday_units = models.DecimalField(max_digits=7, decimal_places=3, default=Decimal("0"))
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.DAILY_REGISTER)
    source_reference = models.CharField(max_length=255)
    reviewed_by = models.CharField(max_length=160)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_period_inputs_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["work_date", "employee_id", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "period_start", "period_end", "work_date"], name="payroll_input_emp_period_date_unique"),
            models.CheckConstraint(check=Q(period_end__gte=models.F("period_start")), name="payroll_input_period_valid"),
            models.CheckConstraint(check=Q(work_date__gte=models.F("period_start"), work_date__lte=models.F("period_end")), name="payroll_input_date_in_period"),
            models.CheckConstraint(check=Q(worked_day_units__gte=0) & Q(planned_day_units__gte=0) & Q(holiday_units__gte=0), name="payroll_input_units_nonneg"),
        ]
        indexes = [models.Index(fields=["organization", "period_start", "period_end"], name="payroll_input_org_period_idx")]

    def clean(self):
        super().clean()
        if self.employee_id and self.organization_id and self.employee.organization_id != self.organization_id:
            raise ValidationError({"employee": "The employee must belong to the same organization."})
        if self.period_end < self.period_start:
            raise ValidationError({"period_end": "Period end must be on or after period start."})
        if not (self.period_start <= self.work_date <= self.period_end):
            raise ValidationError({"work_date": "The work date must be inside the input period."})
        if not self.source_reference.strip():
            raise ValidationError({"source_reference": "Add the register or approved source reference."})
        if not self.reviewed_by.strip():
            raise ValidationError({"reviewed_by": "Record who reviewed these quantities."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def reviewed(self):
        return bool(self.reviewed_at and self.reviewed_by.strip() and self.source_reference.strip())

    def __str__(self):
        return f"{self.employee.full_name}: {self.work_date} period input"


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

    class ScopeMode(models.TextChoices):
        ALL_ACTIVE = "ALL_ACTIVE", "All active payroll employees"
        SELECTED = "SELECTED", "Selected employees"

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
    scope_mode = models.CharField(
        max_length=12, choices=ScopeMode.choices, default=ScopeMode.ALL_ACTIVE,
        help_text="Payroll periods and employee scope belong to this run, not to the organization globally.",
    )
    employees = models.ManyToManyField(
        "employees.Employee", through="PayrollRunEmployee", related_name="payroll_runs",
        blank=True,
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payroll_runs_prepared")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="payroll_runs_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="payroll_runs_finalized")
    finalized_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)
    review_note = models.TextField(blank=True)
    review_revision = models.PositiveIntegerField(
        default=0,
        help_text="Changes to draft calculation inputs increment this revision for stale review protection.",
    )
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
            immutable = ("organization_id", "reference", "idempotency_key", "run_type", "parent_run_id", "period_start", "period_end", "pay_date", "pay_frequency", "currency", "scope_mode", "prepared_by_id")
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


class PayrollRunEmployee(models.Model):
    """Explicit employee membership for a selected payroll run."""

    run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="employee_memberships")
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="payroll_run_employee_memberships",
    )
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="payroll_run_memberships",
    )
    included_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="payroll_run_employee_memberships_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["employee__last_name", "employee__first_name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["run", "employee"], name="payroll_run_employee_unique"),
        ]
        indexes = [
            models.Index(fields=["organization", "employee"], name="payroll_run_emp_org_idx"),
        ]

    def clean(self):
        super().clean()
        if self.run_id and self.organization_id and self.run.organization_id != self.organization_id:
            raise ValidationError({"organization": "The membership organization must match the payroll run."})
        if self.employee_id and self.organization_id and self.employee.organization_id != self.organization_id:
            raise ValidationError({"employee": "The employee must belong to the membership organization."})

    def save(self, *args, **kwargs):
        run_status = (
            PayrollRun.objects.only("status").get(pk=self.run_id).status
            if self.run_id
            else PayrollRun.Status.DRAFT
        )
        if run_status != PayrollRun.Status.DRAFT:
            raise ValidationError("Employee scope can only change while the payroll run is a draft.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        run_status = PayrollRun.objects.only("status").get(pk=self.run_id).status
        if run_status != PayrollRun.Status.DRAFT:
            raise ValidationError("Employee scope can only change while the payroll run is a draft.")
        return super().delete(*args, **kwargs)


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


class PayrollStatutoryAssessment(models.Model):
    """One reviewable agency assessment for one employee statement.

    This is the durable run-level record used by the bulk statutory workspace. The
    legacy snapshot review remains populated for compatibility with finalized and
    historical payroll records.
    """

    class Agency(models.TextChoices):
        SSS = "SSS", "SSS"
        PHILHEALTH = "PHILHEALTH", "PhilHealth"
        PAGIBIG = "PAGIBIG", "Pag-IBIG"
        WITHHOLDING = "WITHHOLDING", "Withholding tax"

    class Status(models.TextChoices):
        PROPOSED = "PROPOSED", "Proposed"
        READY = "READY", "Ready"
        NEEDS_REVIEW = "NEEDS_REVIEW", "Needs attention"
        REVIEWED = "REVIEWED", "Reviewed"
        SUPERSEDED = "SUPERSEDED", "Review again"

    class SourceType(models.TextChoices):
        MANUAL = "MANUAL", "Existing manual line"
        ZERO = "ZERO", "Reviewed zero"
        EXEMPT = "EXEMPT", "Reviewed not applicable"
        OTHER_PERIOD = "OTHER_PERIOD", "Handled in another cutoff"
        IMPORTED = "IMPORTED", "Imported reviewed amount"
        CALCULATED = "CALCULATED", "Calculated amount"

    statement = models.ForeignKey(
        PayrollStatement, on_delete=models.PROTECT, related_name="statutory_assessments"
    )
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="payroll_statutory_assessments",
    )
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="payroll_statutory_assessments",
    )
    agency = models.CharField(max_length=12, choices=Agency.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED, db_index=True)
    source_type = models.CharField(max_length=16, choices=SourceType.choices, default=SourceType.MANUAL)
    coverage = models.ForeignKey(
        EmployeeStatutoryCoverage, on_delete=models.PROTECT, null=True, blank=True,
        related_name="payroll_assessments",
    )
    rule_version = models.ForeignKey(
        StatutoryRuleVersion, on_delete=models.PROTECT, null=True, blank=True,
        related_name="payroll_assessments",
    )
    employee_line = models.ForeignKey(
        PayrollLine, on_delete=models.PROTECT, null=True, blank=True,
        related_name="employee_statutory_assessments",
    )
    employer_line = models.ForeignKey(
        PayrollLine, on_delete=models.PROTECT, null=True, blank=True,
        related_name="employer_statutory_assessments",
    )
    employee_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    employer_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    calculation_basis = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    calculation_snapshot = models.JSONField(default=dict, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    review_note = models.CharField(max_length=500, blank=True)
    registration_follow_up = models.CharField(max_length=500, blank=True)
    input_fingerprint = models.CharField(max_length=64, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="payroll_statutory_assessments_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__last_name", "employee__first_name", "agency", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["statement", "agency"], name="payroll_stat_assessment_statement_agency_unique"),
            models.CheckConstraint(check=Q(employee_amount__gte=0), name="payroll_stat_assessment_employee_nonneg"),
            models.CheckConstraint(check=Q(employer_amount__gte=0), name="payroll_stat_assessment_employer_nonneg"),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "agency"], name="payroll_stat_assess_q_idx"),
            models.Index(fields=["statement", "status"], name="payroll_stat_assess_stmt_idx"),
        ]

    def clean(self):
        super().clean()
        if self.statement_id:
            if self.statement.run.organization_id != self.organization_id:
                raise ValidationError({"organization": "The assessment organization must match the statement run."})
            if self.statement.employee_id != self.employee_id:
                raise ValidationError({"employee": "The assessment employee must match the statement."})
        if self.employee_id and self.organization_id and self.employee.organization_id != self.organization_id:
            raise ValidationError({"employee": "The employee must belong to the assessment organization."})
        if self.employee_line_id and (
            self.employee_line.statement_id != self.statement_id
            or self.employee_line.kind != PayrollLine.Kind.DEDUCTION
            or self.employee_line.source != "MANUAL"
        ):
            raise ValidationError({"employee_line": "Select a manual deduction line from this statement."})
        if self.employer_line_id and (
            self.employer_line.statement_id != self.statement_id
            or self.employer_line.kind != PayrollLine.Kind.EMPLOYER_CONTRIBUTION
            or self.employer_line.source != "MANUAL"
        ):
            raise ValidationError({"employer_line": "Select a manual employer contribution line from this statement."})
        if self.agency == self.Agency.WITHHOLDING and self.employer_line_id:
            raise ValidationError({"employer_line": "Withholding tax cannot have an employer contribution line."})
        if self.status == self.Status.REVIEWED and not (self.reviewed_by_id and self.reviewed_at and self.input_fingerprint):
            raise ValidationError("A reviewed assessment requires reviewer evidence and a current input fingerprint.")

    @property
    def run_id(self):
        return self.statement.run_id if self.statement_id else None

    @property
    def is_current(self):
        return self.status == self.Status.REVIEWED and bool(self.input_fingerprint)

    def save(self, *args, **kwargs):
        if self.statement_id and self.statement.run.status != PayrollRun.Status.DRAFT and not self._state.adding:
            raise ValidationError("Statutory assessments can only change while the payroll run is a draft.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.statement.run.status != PayrollRun.Status.DRAFT:
            raise ValidationError("Statutory assessments can only be removed while the payroll run is a draft.")
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
