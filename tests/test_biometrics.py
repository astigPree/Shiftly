from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from attendance.services import clock_in
from biometrics.models import (
    AttendanceDevice,
    BiometricAttendanceProjection,
    BiometricPunch,
    DeviceIdentity,
    DeviceIdentityAssignment,
    DeviceSyncRun,
    OrganizationBiometricSettings,
)
from biometrics.services import BiometricDeviceError, assign_identity, reconcile_biometric_projection, sync_device_users
from schedules.models import Shift

from .factories import employee, workspace


class BiometricWorkflowTests(TestCase):
    def setUp(self):
        self.organization, self.owner = workspace("biometric")
        self.employee = employee(self.organization, "biometric-staff", account=True)
        self.device = AttendanceDevice.objects.create(
            organization=self.organization,
            name="Office F7",
            host="192.168.10.20",
            port=4370,
            timezone="Asia/Manila",
        )
        OrganizationBiometricSettings.objects.create(organization=self.organization, enabled=True)
        self.identity = DeviceIdentity.objects.create(device=self.device, terminal_user_id="17", display_name="Biometric staff")
        self.run = DeviceSyncRun.objects.create(device=self.device, kind=DeviceSyncRun.Kind.PUNCHES)

    def _utc(self, hour, minute=0):
        return datetime(2026, 9, 21, hour, minute, tzinfo=ZoneInfo("Asia/Manila")).astimezone(timezone.utc)

    def test_assignment_backfills_unmapped_punches_without_rewriting_evidence(self):
        punch = BiometricPunch.objects.create(
            device=self.device,
            device_identity=self.identity,
            sync_run=self.run,
            terminal_user_id="17",
            source_local_timestamp="2026-09-21 09:00:00",
            source_timezone="Asia/Manila",
            occurred_at=self._utc(9),
            canonical_key="first-record",
            payload_hash="a" * 64,
            raw_payload={"record_id": "first-record"},
        )
        assignment = assign_identity(
            identity=self.identity,
            employee=self.employee,
            effective_from=self._utc(0),
            actor=self.owner,
        )
        punch.refresh_from_db()
        self.assertEqual(punch.identity_assignment_id, assignment.pk)
        self.assertEqual(punch.canonical_key, "first-record")

    def test_projection_pairs_first_last_and_flexible_break_scans(self):
        shift = Shift.objects.create(
            organization=self.organization,
            employee=self.employee,
            work_date=datetime(2026, 9, 21, tzinfo=ZoneInfo("Asia/Manila")).date(),
            scheduled_start=self._utc(9),
            scheduled_end=self._utc(18),
            scheduled_break_minutes=60,
        )
        assignment = DeviceIdentityAssignment.objects.create(
            device_identity=self.identity,
            employee=self.employee,
            effective_from=self._utc(0),
            assigned_by=self.owner,
        )
        for index, (hour, minute) in enumerate(((9, 0), (12, 0), (13, 0), (18, 0))):
            BiometricPunch.objects.create(
                device=self.device,
                device_identity=self.identity,
                identity_assignment=assignment,
                sync_run=self.run,
                terminal_user_id="17",
                source_local_timestamp=f"2026-09-21 {hour:02d}:{minute:02d}:00",
                source_timezone="Asia/Manila",
                occurred_at=self._utc(hour, minute),
                canonical_key=f"record-{index}",
                payload_hash=str(index) * 64,
                raw_payload={"record_id": f"record-{index}"},
            )
        projection = reconcile_biometric_projection(shift, now=self._utc(23))
        self.assertEqual(projection.status, BiometricAttendanceProjection.Status.READY)
        self.assertEqual(projection.punch_count, 4)
        self.assertEqual(len(projection.candidate_breaks), 1)

    def test_mapped_employee_cannot_use_web_clock_in(self):
        shift = Shift.objects.create(
            organization=self.organization,
            employee=self.employee,
            work_date=datetime(2026, 9, 21, tzinfo=ZoneInfo("Asia/Manila")).date(),
            scheduled_start=self._utc(9),
            scheduled_end=self._utc(18),
            scheduled_break_minutes=0,
        )
        DeviceIdentityAssignment.objects.create(
            device_identity=self.identity,
            employee=self.employee,
            effective_from=self._utc(0),
            assigned_by=self.owner,
        )
        with self.assertRaises(PermissionDenied):
            clock_in(shift=shift, employee=self.employee, actor=self.employee.user, at=self._utc(9))

    def test_employer_device_and_identity_pages_render(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("biometrics:devices"))
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("biometrics:identities", args=[self.device.pk]))
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("biometrics:punches", args=[self.device.pk]))
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("biometrics:issues"))
        self.assertEqual(response.status_code, 200)

    def test_failed_sync_keeps_operational_failure_record(self):
        class FailingAdapter:
            def list_users(self):
                raise BiometricDeviceError("test terminal unavailable")

        with self.assertRaises(BiometricDeviceError):
            sync_device_users(self.device, adapter=FailingAdapter())
        self.assertEqual(DeviceSyncRun.objects.latest("id").status, DeviceSyncRun.Status.FAILED)
        self.device.refresh_from_db()
        self.assertEqual(self.device.health, AttendanceDevice.Health.OFFLINE)
