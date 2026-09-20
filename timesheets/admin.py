from django.contrib import admin

from .models import Timesheet, TimesheetApproval


class TimesheetApprovalInline(admin.TabularInline):
    model = TimesheetApproval
    extra = 0
    can_delete = False
    readonly_fields = ("reviewer", "action", "comment", "reviewed_at")


@admin.register(Timesheet)
class TimesheetAdmin(admin.ModelAdmin):
    list_display = ("shift", "employee", "status", "worked_minutes", "created_at", "updated_at")
    list_filter = ("status", "organization")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_code")
    readonly_fields = (
        "organization", "employee", "shift", "attendance_session", "scheduled_minutes",
        "break_minutes", "worked_minutes", "payable_minutes", "late_minutes", "undertime_minutes",
        "status", "review_reason", "created_at", "updated_at",
    )
    inlines = (TimesheetApprovalInline,)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TimesheetApproval)
class TimesheetApprovalAdmin(admin.ModelAdmin):
    list_display = ("timesheet", "reviewer", "action", "reviewed_at")
    list_filter = ("action",)
    readonly_fields = ("timesheet", "reviewer", "action", "comment", "reviewed_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
