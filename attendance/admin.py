from django.contrib import admin

from .models import AttendanceSession, BreakSession


class BreakSessionInline(admin.TabularInline):
    model = BreakSession
    extra = 0
    can_delete = False
    readonly_fields = ("started_at", "ended_at", "created_at")


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ("employee", "shift", "clock_in_at", "clock_out_at", "status", "organization")
    list_filter = ("status", "organization")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_code")
    readonly_fields = ("organization", "employee", "shift", "clock_in_at", "clock_out_at", "status", "created_at", "updated_at")
    inlines = (BreakSessionInline,)


@admin.register(BreakSession)
class BreakSessionAdmin(admin.ModelAdmin):
    list_display = ("attendance_session", "started_at", "ended_at")
    readonly_fields = ("attendance_session", "started_at", "ended_at", "created_at")
