from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from biometrics.models import AttendanceDevice
from biometrics.services import sync_device_punches, sync_device_users


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
        totals = {"devices": 0, "users": 0, "punches": 0, "errors": 0, "skipped": 0}
        for device in query:
            due_at = device.last_successful_sync_at
            if not options.get("force") and due_at and due_at + timedelta(seconds=device.effective_sync_interval_seconds) > now:
                totals["skipped"] += 1
                continue
            totals["devices"] += 1
            try:
                if not options.get("punches_only"):
                    result = sync_device_users(device)
                    totals["users"] += result.get("users_seen", 0)
                if not options.get("users_only"):
                    result = sync_device_punches(device)
                    totals["punches"] += result.get("punches_created", 0)
                self.stdout.write(self.style.SUCCESS(f"{device.name}: synchronized"))
            except Exception as error:
                totals["errors"] += 1
                self.stderr.write(self.style.ERROR(f"{device.name}: {error}"))
        self.stdout.write(
            f"Devices: {totals['devices']} · users: {totals['users']} · punches: {totals['punches']} · skipped: {totals['skipped']} · errors: {totals['errors']}"
        )
