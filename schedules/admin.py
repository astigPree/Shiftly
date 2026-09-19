from django.contrib import admin

from .models import Shift


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("work_date", "employee", "scheduled_start", "scheduled_end", "status", "organization")
    list_filter = ("status", "organization", "work_date")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_code")
    readonly_fields = ("created_at", "updated_at")
