from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .validators import validate_iana_timezone


class Organization(models.Model):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organization",
    )
    name = models.CharField(max_length=120)
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        validators=[validate_iana_timezone],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def clean(self):
        super().clean()
        validate_iana_timezone(self.timezone)
        if self.pk and Organization.objects.filter(pk=self.pk).exists():
            prior = Organization.objects.get(pk=self.pk)
            if prior.timezone != self.timezone and self.shifts.exists():
                raise ValidationError({"timezone": "The organization time zone is locked after its first shift."})
        if self.owner_id and self.owner.role != self.owner.Role.EMPLOYER:
            raise ValidationError({"owner": "Organization owners must be employers."})

    def save(self, *args, **kwargs):
        if self.pk:
            prior_timezone = Organization.objects.filter(pk=self.pk).values_list("timezone", flat=True).first()
            if prior_timezone and prior_timezone != self.timezone and self.shifts.exists():
                raise ValidationError({"timezone": "The organization time zone is locked after its first shift."})
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name
