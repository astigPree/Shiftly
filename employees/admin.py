from django.contrib import admin

from .models import Employee, EmployeeInvitation


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_code", "full_name", "email", "organization", "status")
    list_filter = ("status", "organization")
    search_fields = ("employee_code", "first_name", "last_name", "email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmployeeInvitation)
class EmployeeInvitationAdmin(admin.ModelAdmin):
    list_display = ("employee", "email", "created_by", "created_at", "expires_at", "accepted_at", "revoked_at")
    list_filter = ("accepted_at", "revoked_at")
    search_fields = ("email", "employee__employee_code")
    readonly_fields = ("employee", "email", "token_digest", "created_by", "created_at", "expires_at", "accepted_at", "revoked_at")
