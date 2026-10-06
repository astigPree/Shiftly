from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from biometrics.models import AttendanceDevice, DeviceSyncRun, OrganizationBiometricSettings
from biometrics.services import BiometricOperationError, sync_device_punches, sync_device_users


class Command(BaseCommand):
    help = "Synchronize active biometric terminals that are due for a user and punch sync."

    def add_arguments(self, parser):
        parser.add_argument("--device", type=int, help="Only synchronize this device id.")
        parser.add_argument("--users-only", action="store_true")
        parser.add_argument("--punches-only", action="store_true")
        parser.add_argument("--force", action="store_true", help="Ignore the configured due time.")

    def handle(self, *args, **options):
        query = AttendanceDevice.objects.filter(status=AttendanceDevice.Status.ACTIVE).select_related("organization")
        if options.get("device"):
            query = query.filter(pk=options["device"])
        now = timezone.now()
        totals = {"devices": 0, "users": 0, "punches": 0, "errors": 0, "partial": 0, "skipped": 0}
        for device in query:
            try:
                biometric_settings = device.organization.biometric_settings
            except OrganizationBiometricSettings.DoesNotExist:
                biometric_settings = None
            if biometric_settings is None or not biometric_settings.enabled:
                totals["skipped"] += 1
                self.stdout.write(f"{device.name}: skipped (biometric attendance is disabled)")
                continue
            due_at = device.last_successful_sync_at
            if not options.get("force") and due_at and due_at + timedelta(seconds=device.effective_sync_interval_seconds) > now:
                totals["skipped"] += 1
                continue
            totals["devices"] += 1
            try:
                statuses = []
                if not options.get("punches_only"):
                    result = sync_device_users(device)
                    totals["users"] += result.get("users_seen", 0)
                    statuses.append(result.get("status"))
                    if result.get("status") == DeviceSyncRun.Status.SKIPPED:
                        totals["skipped"] += 1
                    elif result.get("status") == DeviceSyncRun.Status.PARTIAL:
                        totals["partial"] += 1
                if not options.get("users_only"):
                    result = sync_device_punches(device)
                    totals["punches"] += result.get("punches_created", 0)
                    statuses.append(result.get("status"))
                    if result.get("status") == DeviceSyncRun.Status.SKIPPED:
                        totals["skipped"] += 1
                    elif result.get("status") == DeviceSyncRun.Status.PARTIAL:
                        totals["partial"] += 1
                if DeviceSyncRun.Status.SKIPPED in statuses:
                    self.stdout.write(self.style.WARNING(f"{device.name}: sync already running"))
                elif DeviceSyncRun.Status.PARTIAL in statuses:
                    self.stdout.write(self.style.WARNING(f"{device.name}: synchronized with review items"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"{device.name}: synchronized"))
            except BiometricOperationError as error:
                totals["errors"] += 1
                retry = " retryable" if error.retryable else ""
                self.stderr.write(self.style.ERROR(f"{device.name}: {error.code}{retry} - {error.operator_message}"))
            except Exception:
                totals["errors"] += 1
                self.stderr.write(self.style.ERROR(f"{device.name}: biometric operation failed; review the sync history"))
        self.stdout.write(
            f"Devices: {totals['devices']} · users: {totals['users']} · punches: {totals['punches']} · partial: {totals['partial']} · skipped: {totals['skipped']} · errors: {totals['errors']}"
        )
