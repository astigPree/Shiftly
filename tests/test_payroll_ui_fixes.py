from datetime import date

from django.test import TestCase
from django.urls import reverse

from payroll.presentation import snapshot_pay_basis

from .factories import completed, employee, payroll_setup, workspace


class PayrollUiFixRegressionTests(TestCase):
    def test_snapshot_basis_supports_legacy_hourly_rate_versions_and_mixed_values(self):
        self.assertEqual(
            snapshot_pay_basis({"rate_versions": {"old": {"basis": "HOURLY"}}}),
            "Hourly",
        )
        self.assertEqual(
            snapshot_pay_basis({
                "rate_versions": {"hourly": {"basis": "HOURLY"}},
                "compensation_versions": {"daily": {"basis": "DAILY"}},
            }),
            "Mixed",
        )
        self.assertEqual(snapshot_pay_basis({}), "Pay basis not recorded")

    def test_run_preview_uses_requested_period_and_is_read_only(self):
        organization, owner = workspace("preview")
        staff = employee(organization, "preview-staff")
        payroll_setup(organization, staff, rate="120.0000")
        completed(organization, staff, day=date(2026, 9, 21), approve=True)
        self.client.force_login(owner)

        before = {
            "runs": organization.payroll_runs.count(),
            "events": organization.audit_events.count(),
        }
        response = self.client.post(reverse("payroll:run_preview"), {
            "request_key": "f2f76bd8-2f8d-4fd4-a7d6-7f3adcb85d1e",
            "run_type": "REGULAR",
            "scope_mode": "ALL_ACTIVE",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "pay_date": "2026-10-05",
            "parent_run": "",
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["approved_timesheets"], 1)
        self.assertEqual(payload["employee_count"], 1)
        self.assertEqual(payload["source_mode"], "attendance")
        self.assertEqual(before, {
            "runs": organization.payroll_runs.count(),
            "events": organization.audit_events.count(),
        })

    def test_run_preview_rejects_foreign_selected_employee(self):
        organization, owner = workspace("preview-tenant")
        other_organization, _ = workspace("preview-other")
        foreign = employee(other_organization, "foreign")
        self.client.force_login(owner)

        response = self.client.post(reverse("payroll:run_preview"), {
            "request_key": "8f317bf2-4b07-4fb6-8c75-4e907cedbc1a",
            "run_type": "REGULAR",
            "scope_mode": "SELECTED",
            "employees": [str(foreign.pk)],
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "pay_date": "2026-10-05",
            "parent_run": "",
        })

        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.json()["ok"])
