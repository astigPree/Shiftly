from datetime import date
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from audit.models import AuditEvent
from payroll.models import PayrollLine, PayrollRun, PayrollStatement
from payroll.payslips import build_finalized_payslip_data, build_payslip_pdf

from .factories import employee, workspace


class PayslipPdfTests(TestCase):
    def setUp(self):
        self.organization, self.owner = workspace()
        self.employee = employee(self.organization, suffix="payslip")
        self.other_organization, self.other_owner = workspace("other")
        self.other_employee = employee(self.other_organization, suffix="other")
        self._reference = 0

    def finalized_statement(self, *, employee_record=None, classification="REGULAR", basis="HOURLY",
                            include_daily_inputs=False, long_name=False, item_count=0):
        self._reference += 1
        employee_record = employee_record or self.employee
        run = PayrollRun.objects.create(
            organization=employee_record.organization,
            reference=f"PAYSLIP-{self._reference:03d}",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            pay_date=date(2026, 10, 5),
            pay_frequency="MONTHLY",
            currency="PHP",
            prepared_by=employee_record.organization.owner,
        )
        display_name = (
            "A very long synthetic employee name that confirms the professional payslip wraps "
            "personal information without clipping any content"
            if long_name else employee_record.full_name
        )
        snapshot = {
            "employee": {
                "code": employee_record.employee_code,
                "name": display_name,
                "employment_status": classification,
                "employment_status_label": {
                    "REGULAR": "Regular",
                    "PROBATION": "Probation",
                    "PART_TIME": "Part-time",
                    "OTHER": "Other",
                }[classification],
            },
            "compensation_versions": {
                "synthetic": {"basis": basis, "amount": "100.0000" if basis == "HOURLY" else "800.0000"},
            },
        }
        if include_daily_inputs:
            snapshot["period_inputs"] = [{
                "absence_units": "0.50", "undertime_minutes": 45,
            }]
        statement = PayrollStatement.objects.create(
            run=run,
            employee=employee_record,
            gross_amount=Decimal("950.00"),
            deduction_amount=Decimal("150.00"),
            employer_contribution_amount=Decimal("75.00"),
            net_amount=Decimal("800.00"),
            snapshot=snapshot,
        )
        line_values = [
            ("EARNING", "REGULAR_PAY", "Basic pay", "800.00", "CALCULATED"),
            ("EARNING", "COMPONENT_COLA", "Cost of living allowance", "100.00", "CALCULATED_COMPONENT"),
            ("EARNING", "MANUAL_BONUS", "Attendance bonus", "50.00", "MANUAL"),
            ("DEDUCTION", "MANUAL_SSS", "SSS employee", "50.00", "MANUAL"),
            ("DEDUCTION", "MANUAL_TAX", "BIR withholding tax", "50.00", "MANUAL"),
            ("DEDUCTION", "COMPONENT_ADVANCE", "Advance repayment", "50.00", "CALCULATED_COMPONENT"),
            ("EMPLOYER_CONTRIBUTION", "MANUAL_SSS_EMPLOYER", "SSS employer", "75.00", "MANUAL"),
        ]
        for index in range(item_count):
            line_values[2:2] = [("EARNING", f"MANUAL_{index}", f"Approved earning item {index + 1}", "0.00", "MANUAL")]
        for kind, code, label, amount, source in line_values:
            PayrollLine.objects.create(
                statement=statement,
                kind=kind,
                code=code,
                label=label,
                amount=Decimal(amount),
                source=source,
                created_by=employee_record.organization.owner,
            )
        PayrollRun.objects.filter(pk=run.pk).update(status=PayrollRun.Status.FINALIZED)
        return PayrollStatement.objects.select_related("run", "run__organization", "employee").prefetch_related("lines").get(pk=statement.pk)

    def test_builder_preserves_finalized_totals_and_itemizes_supported_categories(self):
        statement = self.finalized_statement()

        data = build_finalized_payslip_data(statement)

        self.assertEqual(data["gross"], Decimal("950.00"))
        self.assertEqual(data["deductions"], Decimal("150.00"))
        self.assertEqual(data["net"], Decimal("800.00"))
        self.assertEqual(data["allowance_total"], Decimal("100.00"))
        self.assertEqual(
            [row["label"] for row in data["deduction_rows"]],
            ["SSS", "BIR withholding tax", "Cash advance"],
        )
        self.assertEqual(data["employer_contributions"], Decimal("75.00"))

    def test_builder_supports_every_finalized_classification(self):
        expected = {
            "REGULAR": "Regular",
            "PROBATION": "Probation",
            "PART_TIME": "Part-time",
            "OTHER": "Other",
        }
        for status, label in expected.items():
            with self.subTest(status=status):
                statement = self.finalized_statement(classification=status)
                self.assertEqual(build_finalized_payslip_data(statement)["employee"]["classification"], label)

    def test_daily_snapshot_marks_absence_and_undertime_without_second_deduction(self):
        statement = self.finalized_statement(basis="DAILY", include_daily_inputs=True)

        data = build_finalized_payslip_data(statement)

        self.assertIn("already reflected", data["work_adjustment_note"])
        self.assertEqual(data["gross"] - data["deductions"], data["net"])
        self.assertEqual(data["employee"]["pay_basis"], "Daily")

    def test_pdf_has_selectable_text_and_handles_long_names_and_many_lines(self):
        statement = self.finalized_statement(long_name=True, item_count=24)

        document = build_payslip_pdf(build_finalized_payslip_data(statement))
        reader = PdfReader(BytesIO(document))
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertTrue(document.startswith(b"%PDF-"))
        self.assertGreaterEqual(len(reader.pages), 1)
        self.assertIn("PAYSLIP", extracted)
        self.assertIn("NET PAY", extracted)
        self.assertIn("Approved earning item 24", extracted)

    def test_employee_can_download_only_their_own_finalized_payslip(self):
        statement = self.finalized_statement()
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("payroll:my_statement_payslip_pdf", args=[statement.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("Shiftly_Payslip_PAYSLIP_2026-09.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-"))
        event = AuditEvent.objects.get(action=AuditEvent.Action.PAYROLL_EXPORT_ACCESSED)
        self.assertEqual(event.metadata["format"], "pdf")
        self.assertEqual(event.metadata["access_scope"], "employee")

    def test_finalized_payslip_download_controls_render_for_employer_and_employee(self):
        statement = self.finalized_statement()
        employer_url = reverse("payroll:run_statement_payslip_pdf", args=[statement.run_id, statement.pk])
        employee_url = reverse("payroll:my_statement_payslip_pdf", args=[statement.pk])

        self.client.force_login(self.owner)
        employer_page = self.client.get(reverse("payroll:run_detail", args=[statement.run_id]))
        self.assertEqual(employer_page.status_code, 200)
        self.assertContains(employer_page, employer_url)

        self.client.force_login(self.employee.user)
        history_page = self.client.get(reverse("payroll:my_statements"))
        detail_page = self.client.get(reverse("payroll:my_statement_detail", args=[statement.pk]))
        self.assertEqual(history_page.status_code, 200)
        self.assertEqual(detail_page.status_code, 200)
        self.assertContains(history_page, employee_url)
        self.assertContains(detail_page, "Download payslip (PDF)")

    def test_employee_cannot_download_another_employee_or_draft_payslip(self):
        other_statement = self.finalized_statement(employee_record=self.other_employee)
        draft_statement = self.finalized_statement()
        PayrollRun.objects.filter(pk=draft_statement.run_id).update(status=PayrollRun.Status.DRAFT)
        self.client.force_login(self.employee.user)

        other_response = self.client.get(reverse("payroll:my_statement_payslip_pdf", args=[other_statement.pk]))
        draft_response = self.client.get(reverse("payroll:my_statement_payslip_pdf", args=[draft_statement.pk]))

        self.assertEqual(other_response.status_code, 404)
        self.assertEqual(draft_response.status_code, 404)

    def test_employer_download_is_organization_scoped_and_finalized_only(self):
        statement = self.finalized_statement()
        self.client.force_login(self.owner)

        response = self.client.get(reverse("payroll:run_statement_payslip_pdf", args=[statement.run_id, statement.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))

        self.client.force_login(self.other_owner)
        forbidden = self.client.get(reverse("payroll:run_statement_payslip_pdf", args=[statement.run_id, statement.pk]))
        self.assertEqual(forbidden.status_code, 404)

        PayrollRun.objects.filter(pk=statement.run_id).update(status=PayrollRun.Status.DRAFT)
        self.client.force_login(self.owner)
        unavailable = self.client.get(reverse("payroll:run_statement_payslip_pdf", args=[statement.run_id, statement.pk]))
        self.assertEqual(unavailable.status_code, 409)
        self.assertContains(unavailable, "available only after payroll is finalized", status_code=409)
