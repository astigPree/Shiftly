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
        if self.owner_id and self.owner.role != self.owner.Role.EMPLOYER:
            raise ValidationError({"owner": "Organization owners must be employers."})

    def __str__(self):
        return self.name
