from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from attendance.models import AttendanceSession
from attendance.services import clock_in
from biometrics.forms import DeviceIdentityAssignmentForm
from biometrics.models import (
    AttendanceDevice,
    BiometricAttendanceProjection,
    BiometricPunch,
    DeviceIdentity,
    DeviceIdentityAssignment,
    DeviceSyncRun,
    OrganizationBiometricSettings,
)
from biometrics.services import (
    BiometricConfigurationError,
    BiometricDeviceError,
    BiometricErrorCode,
    assign_identity,
    reconcile_biometric_projection,
    refresh_due_biometric_projections,
    materialize_biometric_projection,
    sync_device_users,
    test_device_connection,
)
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

    def test_first_scan_is_visible_as_provisional_without_attendance_side_effects(self):
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
        BiometricPunch.objects.create(
            device=self.device,
            device_identity=self.identity,
            identity_assignment=assignment,
            sync_run=self.run,
            terminal_user_id="17",
            source_local_timestamp="2026-09-21 09:03:00",
            source_timezone="Asia/Manila",
            occurred_at=self._utc(9, 3),
            canonical_key="provisional-first",
            payload_hash="b" * 64,
            raw_payload={"record_id": "provisional-first"},
        )

        projection = reconcile_biometric_projection(shift, now=self._utc(9, 5))

        self.assertEqual(projection.status, BiometricAttendanceProjection.Status.COLLECTING)
        self.assertEqual(projection.live_state, BiometricAttendanceProjection.LiveState.WORKING)
        self.assertEqual(projection.punch_count, 1)
        self.assertIsNone(projection.materialized_session_id)
        self.assertEqual(AttendanceSession.objects.count(), 0)

        self.client.force_login(self.owner)
        review_response = self.client.get(reverse("biometrics:projection_detail", args=[projection.pk]))
        self.assertEqual(review_response.status_code, 200)
        employer_response = self.client.get(reverse("attendance:list"), {"date": "2026-09-21"})
        self.assertEqual(employer_response.status_code, 200)
        self.assertContains(employer_response, "Working · provisional")
        self.client.force_login(self.employee.user)
        with patch("attendance.views.timezone.now", return_value=self._utc(9, 5)):
            employee_response = self.client.get(reverse("attendance:my_attendance"))
        self.assertEqual(employee_response.status_code, 200)
        self.assertContains(employee_response, "Working · biometric provisional")

    def test_projection_waits_for_candidate_close_then_becomes_ready(self):
        shift = Shift.objects.create(
            organization=self.organization,
            employee=self.employee,
            work_date=datetime(2026, 9, 21, tzinfo=ZoneInfo("Asia/Manila")).date(),
            scheduled_start=self._utc(9),
            scheduled_end=self._utc(18),
            scheduled_break_minutes=0,
        )
        assignment = DeviceIdentityAssignment.objects.create(
            device_identity=self.identity,
            employee=self.employee,
            effective_from=self._utc(0),
            assigned_by=self.owner,
        )
        for index, (hour, minute) in enumerate(((9, 0), (18, 0))):
            BiometricPunch.objects.create(
                device=self.device,
                device_identity=self.identity,
                identity_assignment=assignment,
                sync_run=self.run,
                terminal_user_id="17",
                source_local_timestamp=f"2026-09-21 {hour:02d}:{minute:02d}:00",
                source_timezone="Asia/Manila",
                occurred_at=self._utc(hour, minute),
                canonical_key=f"close-{index}",
                payload_hash=str(index + 2) * 64,
                raw_payload={"record_id": f"close-{index}"},
            )

        collecting = reconcile_biometric_projection(shift, now=self._utc(18, 1))
        self.assertEqual(collecting.live_state, BiometricAttendanceProjection.LiveState.AWAITING_NEXT_SCAN)
        self.assertEqual(collecting.status, BiometricAttendanceProjection.Status.COLLECTING)

        refreshed = refresh_due_biometric_projections(now=self._utc(23))
        self.assertEqual(len(refreshed), 1)
        collecting.refresh_from_db()
        self.assertEqual(collecting.status, BiometricAttendanceProjection.Status.READY)
        self.assertEqual(collecting.live_state, BiometricAttendanceProjection.LiveState.READY_FOR_REVIEW)
        self.assertEqual(AttendanceSession.objects.count(), 0)

    def test_late_scan_after_application_is_retained_as_issue(self):
        shift = Shift.objects.create(
            organization=self.organization,
            employee=self.employee,
            work_date=datetime(2026, 9, 21, tzinfo=ZoneInfo("Asia/Manila")).date(),
            scheduled_start=self._utc(9),
            scheduled_end=self._utc(18),
            scheduled_break_minutes=0,
        )
        assignment = DeviceIdentityAssignment.objects.create(
            device_identity=self.identity,
            employee=self.employee,
            effective_from=self._utc(0),
            assigned_by=self.owner,
        )
        for index, hour in enumerate((9, 18)):
            BiometricPunch.objects.create(
                device=self.device,
                device_identity=self.identity,
                identity_assignment=assignment,
                sync_run=self.run,
                terminal_user_id="17",
                source_local_timestamp=f"2026-09-21 {hour:02d}:00:00",
                source_timezone="Asia/Manila",
                occurred_at=self._utc(hour),
                canonical_key=f"applied-{index}",
                payload_hash=str(index + 5) * 64,
                raw_payload={"record_id": f"applied-{index}"},
            )
        projection = reconcile_biometric_projection(shift, now=self._utc(23))
        session = materialize_biometric_projection(projection, actor=self.owner)
        late_punch = BiometricPunch.objects.create(
            device=self.device,
            device_identity=self.identity,
            identity_assignment=assignment,
            sync_run=self.run,
            terminal_user_id="17",
            source_local_timestamp="2026-09-21 19:00:00",
            source_timezone="Asia/Manila",
            occurred_at=self._utc(19),
            canonical_key="applied-late",
            payload_hash="z" * 64,
            raw_payload={"record_id": "applied-late"},
        )

        reconcile_biometric_projection(shift, now=self._utc(23, 5))

        late_punch.refresh_from_db()
        projection.refresh_from_db()
        self.assertEqual(projection.status, BiometricAttendanceProjection.Status.MATERIALIZED)
        self.assertEqual(late_punch.projection_id, projection.pk)
        self.assertTrue(projection.issues.filter(code="LATE_EVIDENCE", status="OPEN").exists())
        self.assertEqual(session.clock_out_at, self._utc(18))

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

    def test_identity_form_binds_identity_before_model_validation(self):
        form = DeviceIdentityAssignmentForm(
            data={
                "employee": self.employee.pk,
                "effective_from": "2026-09-21T00:00",
                "effective_until": "",
            },
            organization=self.organization,
            identity=self.identity,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.instance.device_identity_id, self.identity.pk)

    def test_identity_form_reports_overlap_without_relation_exception(self):
        DeviceIdentityAssignment.objects.create(
            device_identity=self.identity,
            employee=self.employee,
            effective_from=self._utc(0),
            assigned_by=self.owner,
        )
        form = DeviceIdentityAssignmentForm(
            data={
                "employee": self.employee.pk,
                "effective_from": "2026-09-21T09:00",
                "effective_until": "",
            },
            organization=self.organization,
            identity=self.identity,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("overlapping assignment", str(form.errors).lower())

    def test_identity_mapping_post_saves_without_server_error(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("biometrics:identities", args=[self.device.pk]),
            {
                "identity": self.identity.pk,
                "employee": self.employee.pk,
                "effective_from": "2026-09-21T00:00",
                "effective_until": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DeviceIdentityAssignment.objects.filter(
            device_identity=self.identity,
            employee=self.employee,
        ).exists())

    def test_identity_mapping_missing_context_returns_form_error(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("biometrics:identities", args=[self.device.pk]),
            {
                "identity": "999999",
                "employee": self.employee.pk,
                "effective_from": "2026-09-21T00:00",
                "effective_until": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no longer available")

    def test_failed_connection_test_is_recorded_and_releases_lock(self):
        class FailingAdapter:
            def test_connection(self):
                raise BiometricDeviceError("terminal unavailable")

        with self.assertRaises(BiometricDeviceError) as context:
            test_device_connection(self.device, actor=self.owner, adapter=FailingAdapter())
        self.assertEqual(context.exception.code, BiometricErrorCode.NETWORK_UNREACHABLE)
        run = DeviceSyncRun.objects.latest("id")
        self.assertEqual(run.kind, DeviceSyncRun.Kind.CONNECTION)
        self.assertEqual(run.status, DeviceSyncRun.Status.FAILED)
        self.assertEqual(run.error_code, BiometricErrorCode.NETWORK_UNREACHABLE)
        self.device.refresh_from_db()
        self.assertEqual(self.device.sync_lock_until, None)
        self.assertEqual(self.device.health, AttendanceDevice.Health.OFFLINE)

    def test_locked_sync_creates_skipped_run(self):
        self.device.sync_lock_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.device.save(update_fields=["sync_lock_until"])
        result = sync_device_users(self.device, actor=self.owner)
        self.assertEqual(result["status"], DeviceSyncRun.Status.SKIPPED)
        self.assertEqual(result["error_code"], BiometricErrorCode.SYNC_LOCKED)
        self.assertEqual(result["run"].error_code, BiometricErrorCode.SYNC_LOCKED)

    def test_unsupported_device_fails_safely_and_releases_lock(self):
        self.device.model = "Unsupported Terminal"
        self.device.save(update_fields=["model"])
        with self.assertRaises(BiometricConfigurationError) as context:
            test_device_connection(self.device, actor=self.owner)
        self.assertEqual(context.exception.code, BiometricErrorCode.UNSUPPORTED_DEVICE)
        run = DeviceSyncRun.objects.latest("id")
        self.assertEqual(run.error_code, BiometricErrorCode.UNSUPPORTED_DEVICE)
        self.device.refresh_from_db()
        self.assertIsNone(self.device.sync_lock_until)
