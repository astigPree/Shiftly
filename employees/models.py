from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


employee_code_validator = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$",
    message="Use 1–32 letters, numbers, periods, underscores, or hyphens.",
)


class Employee(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="employees",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="employee_profile",
        null=True,
        blank=True,
    )
    employee_code = models.CharField(
        max_length=32,
        validators=[employee_code_validator],
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField()
    job_title = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "employee_code"],
                name="employees_org_code_unique",
            ),
            models.UniqueConstraint(
                Lower("email"), name="employees_email_ci_unique"
            ),
            models.CheckConstraint(
                check=Q(status__in=["ACTIVE", "INACTIVE"]),
                name="employees_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="employees_org_status_idx"),
            models.Index(fields=["organization", "last_name", "first_name"], name="employees_org_name_idx"),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().casefold()
        self.employee_code = self.employee_code.strip().upper()
        return super().save(*args, **kwargs)

    @property
    def full_name(self):
        return " ".join(part for part in (self.first_name, self.last_name) if part)

    def __str__(self):
        return f"{self.full_name} ({self.employee_code})"


class EmployeeInvitation(models.Model):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField()
    token_digest = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="employee_invitations_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee"],
                condition=Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="employees_one_open_invitation",
            ),
            models.CheckConstraint(
                check=Q(expires_at__gt=models.F("created_at")),
                name="employees_invitation_expiry_after_creation",
            ),
        ]
        indexes = [models.Index(fields=["expires_at"], name="employees_invite_expiry_idx")]

    def __str__(self):
        return f"Invitation for {self.email}"
