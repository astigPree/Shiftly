from django.contrib import admin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "timezone", "created_at")
    search_fields = ("name", "owner__email")
    readonly_fields = ("created_at", "updated_at")
