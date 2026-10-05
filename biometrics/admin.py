from django.contrib import admin

from .models import (
    AttendanceDevice,
    BiometricAttendanceProjection,
    BiometricPunch,
    BiometricPunchIssue,
    DeviceIdentity,
    DeviceIdentityAssignment,
    DeviceSyncRun,
    OrganizationBiometricSettings,
)


@admin.register(OrganizationBiometricSettings)
class OrganizationBiometricSettingsAdmin(admin.ModelAdmin):
    list_display = ("organization", "enabled", "default_sync_interval_seconds", "updated_at")


@admin.register(AttendanceDevice)
class AttendanceDeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "model", "host", "port", "status", "health", "last_successful_sync_at")
    list_filter = ("status", "health", "model")
    search_fields = ("name", "host", "serial_number")


@admin.register(DeviceIdentity)
class DeviceIdentityAdmin(admin.ModelAdmin):
    list_display = ("device", "terminal_user_id", "display_name", "last_seen_at")
    search_fields = ("terminal_user_id", "display_name")


@admin.register(DeviceIdentityAssignment)
class DeviceIdentityAssignmentAdmin(admin.ModelAdmin):
    list_display = ("device_identity", "employee", "effective_from", "effective_until")
    list_filter = ("device_identity__device",)


@admin.register(DeviceSyncRun)
class DeviceSyncRunAdmin(admin.ModelAdmin):
    list_display = ("device", "kind", "status", "started_at", "finished_at", "punches_created", "punches_duplicate")
    list_filter = ("kind", "status")
    readonly_fields = ("error_message", "diagnostics")


@admin.register(BiometricPunch)
class BiometricPunchAdmin(admin.ModelAdmin):
    list_display = ("device", "terminal_user_id", "occurred_at", "device_record_id", "identity_assignment")
    list_filter = ("device", "source_timezone")
    search_fields = ("terminal_user_id", "device_record_id", "canonical_key")
    readonly_fields = ("raw_payload", "payload_hash", "canonical_key")


@admin.register(BiometricAttendanceProjection)
class BiometricAttendanceProjectionAdmin(admin.ModelAdmin):
    list_display = ("shift", "employee", "status", "punch_count", "updated_at")
    list_filter = ("status",)


@admin.register(BiometricPunchIssue)
class BiometricPunchIssueAdmin(admin.ModelAdmin):
    list_display = ("organization", "code", "status", "summary", "created_at", "resolved_at")
    list_filter = ("code", "status")
    search_fields = ("summary", "employee__employee_code", "device__name")
