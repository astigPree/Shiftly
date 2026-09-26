import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from payroll.models import (PayrollRun, PayrollLine, PayrollRuleProfile, PayrollRuleAssignment,
    PayrollRuleSet, EmployeePayRate, PayrollHoliday, PayrollSettings)
from payroll.services import (create_payroll_run, calculate_payroll_run, add_adjustment,
    remove_adjustment, submit_for_review, finalize_payroll_run, void_payroll_run,
    resolve_payroll_exception, resolve_effective_rule, effective_pay_rate)
from .factories import workspace, employee, completed, payroll_setup, instant, DAY


class PayrollTests(TestCase):
    def setUp(self):
        self.org, self.owner = workspace()
        self.emp = employee(self.org)
        self.profile, self.rule = payroll_setup(self.org, self.emp)

    def run_payroll(self, **overrides):
        values = dict(organization=self.org, actor=self.owner, period_start=date(2026, 9, 1),
                      period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))
        values.update(overrides)
        return create_payroll_run(**values)

    def exception_codes(self, run):
        return set(run.exceptions.filter(superseded_at__isnull=True, resolved_at__isnull=True).values_list("code", flat=True))

    def finalize(self, run):
        run = submit_for_review(run=run, actor=self.owner)
        return finalize_payroll_run(run=run, actor=self.owner, review_note="Synthetic reference checked")

    def test_basic_pay_net_is_persisted_and_reconciles(self):
        completed(self.org, self.emp)
        run = self.run_payroll()
        statement = run.statements.get()
        self.assertEqual(statement.gross_amount, Decimal("800.00"))
        self.assertEqual(statement.net_amount, Decimal("800.00"))
        self.assertFalse(self.exception_codes(run))
        self.assertEqual(self.finalize(run).status, "FINALIZED")

    def test_ordinary_overtime(self):
        completed(self.org, self.emp, end=19, break_minutes=0)
        statement = self.run_payroll().statements.get()
        self.assertEqual(statement.gross_amount, Decimal("1050.00"))
        self.assertEqual(statement.time_entries.get().overtime_minutes, 120)

    def test_overnight_night_differential_excludes_break(self):
        completed(self.org, self.emp, start=22, end=3, break_minutes=30)
        statement = self.run_payroll().statements.get()
        self.assertEqual(statement.gross_amount, Decimal("495.00"))
        entry = statement.time_entries.get()
        self.assertEqual((entry.payable_minutes, entry.night_minutes), (270, 270))
        self.assertEqual(entry.snapshot["included_work_dates"], ["2026-09-21", "2026-09-22"])

    def test_midnight_assignment_and_rate_changes(self):
        special = PayrollRuleProfile.objects.create(organization=self.org, code="night", name="Night team", created_by=self.owner)
        PayrollRuleSet.objects.create(organization=self.org, rule_profile=special, effective_from=DAY,
            night_differential_rate=Decimal("0.20"), source_references="Test", reviewed_by="Tester",
            reviewed_at=instant(), created_by=self.owner)
        PayrollRuleAssignment.objects.create(organization=self.org, employee=self.emp, rule_profile=special,
            effective_from=DAY + timedelta(days=1), assigned_by=self.owner)
        old_rate = self.emp.pay_rates.get()
        old_rate.effective_until = DAY
        old_rate.save()
        EmployeePayRate.objects.create(employee=self.emp, hourly_rate=Decimal("200"),
            effective_from=DAY + timedelta(days=1), change_reason="New rate", created_by=self.owner)
        completed(self.org, self.emp, start=22, end=3, break_minutes=0)
        statement = self.run_payroll().statements.get()
        # 2 hours * 100 * 1.10 + 3 hours * 200 * 1.20
        self.assertEqual(statement.gross_amount, Decimal("940.00"))
        self.assertEqual(len(statement.snapshot["rule_versions"]), 2)
        self.assertEqual(len(statement.snapshot["rate_versions"]), 2)

    def test_period_cutoff_includes_only_local_work_dates(self):
        completed(self.org, self.emp, day=date(2026, 8, 31), start=22, end=3, break_minutes=0)
        statement = self.run_payroll().statements.get()
        self.assertEqual(statement.gross_amount, Decimal("330.00"))
        self.assertEqual(statement.time_entries.get().payable_minutes, 180)

    def test_rest_day_and_reviewed_holiday_premiums(self):
        pay_profile = self.emp.payroll_profile
        pay_profile.rest_day = DAY.weekday()
        pay_profile.save()
        completed(self.org, self.emp)
        statement = self.run_payroll().statements.get()
        self.assertEqual(statement.gross_amount, Decimal("1040.00"))

    def test_reviewed_holiday_pay(self):
        PayrollHoliday.objects.create(organization=self.org, date=DAY, name="Test holiday", kind="REGULAR",
            worked_multiplier=Decimal("2"), overtime_multiplier=Decimal("2.6"), source_reference="Test",
            reviewed_by="Tester", reviewed_at=instant(), created_by=self.owner)
        completed(self.org, self.emp)
        self.assertEqual(self.run_payroll().statements.get().gross_amount, Decimal("1600.00"))

    def test_unreviewed_holiday_requires_manual_line(self):
        PayrollHoliday.objects.create(organization=self.org, date=DAY, name="Test holiday", kind="REGULAR",
            worked_multiplier=Decimal("2"), overtime_multiplier=Decimal("2.6"), created_by=self.owner)
        completed(self.org, self.emp)
        run = self.run_payroll()
        issue = run.exceptions.get(code="HOLIDAY_NOT_REVIEWED")
        with self.assertRaises(ValidationError):
            resolve_payroll_exception(exception=issue, actor=self.owner, note="Confirmed")
        statement = add_adjustment(run=run, actor=self.owner, employee=self.emp, kind="EARNING", label="Holiday premium",
            amount="800", effective_date=DAY, note="Reviewed test premium")
        line = statement.lines.get(source="MANUAL")
        resolve_payroll_exception(exception=issue, actor=self.owner, note="Reviewed", resolution_line=line)
        with self.assertRaises(ValidationError):
            remove_adjustment(run=run, actor=self.owner, line_id=line.pk)

    def test_missing_rate_blocks_review_and_recalculation_clears_exception(self):
        self.emp.pay_rates.all().delete()
        completed(self.org, self.emp)
        run = self.run_payroll()
        self.assertIn("PAY_RATE_MISSING", self.exception_codes(run))
        with self.assertRaises(ValidationError):
            submit_for_review(run=run, actor=self.owner)
        EmployeePayRate.objects.create(employee=self.emp, hourly_rate=100, effective_from=DAY, created_by=self.owner)
        calculate_payroll_run(run=run, actor=self.owner)
        self.assertFalse(self.exception_codes(run))
        self.assertEqual(run.calculation_previews.count(), 2)

    def test_pending_timesheets_not_paid(self):
        completed(self.org, self.emp, approve=False)
        run = self.run_payroll()
        self.assertEqual(run.statements.count(), 0)
        self.assertTrue(self.exception_codes(run))

    def test_unreviewed_rule_cannot_be_bypassed(self):
        PayrollRuleSet.objects.filter(pk=self.rule.pk).update(reviewed_at=None)
        completed(self.org, self.emp)
        run = self.run_payroll()
        self.assertEqual(run.statements.count(), 0)
        with self.assertRaises(ValidationError):
            submit_for_review(run=run, actor=self.owner)

    def test_adjustments_deductions_contributions_and_removal(self):
        completed(self.org, self.emp)
        run = self.run_payroll()
        for kind, value in (("EARNING", "100"), ("DEDUCTION", "50"), ("EMPLOYER_CONTRIBUTION", "25")):
            add_adjustment(run=run, actor=self.owner, employee=self.emp, kind=kind, label="Test line",
                           amount=value, effective_date=DAY, note="Test reason")
        statement = run.statements.get()
        self.assertEqual((statement.gross_amount, statement.net_amount, statement.employer_contribution_amount),
                         (Decimal("900"), Decimal("850"), Decimal("25")))
        line = statement.lines.get(source="MANUAL", kind="EARNING")
        remove_adjustment(run=run, line_id=line.pk, actor=self.owner)
        statement.refresh_from_db()
        self.assertEqual(statement.net_amount, Decimal("750"))

    def test_negative_net_blocks_review(self):
        completed(self.org, self.emp)
        run = self.run_payroll()
        add_adjustment(run=run, actor=self.owner, employee=self.emp, kind="DEDUCTION", label="Too much",
                       amount="900", effective_date=DAY, note="Invalid total test")
        with self.assertRaises(ValidationError):
            submit_for_review(run=run, actor=self.owner)

    def test_duplicate_run_token_and_overlapping_periods(self):
        token = uuid.uuid4()
        run = self.run_payroll(idempotency_key=token)
        self.assertEqual(self.run_payroll(idempotency_key=token).pk, run.pk)
        with self.assertRaises(ValidationError):
            self.run_payroll()
        with self.assertRaises(ValidationError):
            self.run_payroll(idempotency_key=token, pay_date=date(2026, 10, 1))

    def test_void_reason_and_replacement_reference(self):
        run = self.run_payroll()
        with self.assertRaises(ValidationError):
            void_payroll_run(run=run, actor=self.owner, reason="")
        void_payroll_run(run=run, actor=self.owner, reason="Replace draft")
        replacement = self.run_payroll()
        self.assertNotEqual(replacement.reference, run.reference)

    def test_foreign_owner_cannot_manage_run(self):
        _, other = workspace("b")
        with self.assertRaises(PermissionDenied):
            self.run_payroll(actor=other)

    def test_assignment_resolution_bounds_and_conflicts(self):
        team = PayrollRuleProfile.objects.create(organization=self.org, code="team", name="Team", created_by=self.owner)
        assignment = PayrollRuleAssignment.objects.create(organization=self.org, employee=self.emp, rule_profile=team,
            effective_from=DAY, effective_until=DAY, assigned_by=self.owner)
        self.assertEqual(resolve_effective_rule(self.org, DAY - timedelta(days=1), self.emp)[1], self.profile)
        self.assertEqual(resolve_effective_rule(self.org, DAY, self.emp)[2], assignment)
        self.assertEqual(resolve_effective_rule(self.org, DAY + timedelta(days=1), self.emp)[1], self.profile)
        with self.assertRaises(ValidationError):
            PayrollRuleAssignment.objects.create(organization=self.org, employee=self.emp, rule_profile=team,
                effective_from=DAY - timedelta(days=1), assigned_by=self.owner)

    def test_finalized_run_is_immutable_and_off_cycle_keeps_original(self):
        completed(self.org, self.emp)
        run = self.finalize(self.run_payroll())
        original = run.statements.get()
        with self.assertRaises(ValidationError):
            calculate_payroll_run(run=run, actor=self.owner)
        with self.assertRaises(ValidationError):
            void_payroll_run(run=run, actor=self.owner, reason="Cannot void")
        with self.assertRaises(ValidationError):
            original.save()
        correction = self.run_payroll(run_type="OFF_CYCLE", parent_run=run)
        statement = add_adjustment(run=correction, actor=self.owner, employee=self.emp, kind="EARNING",
            label="Correction", amount="50", effective_date=DAY, note="Test correction")
        self.finalize(correction)
        original.refresh_from_db()
        self.assertEqual(original.net_amount, Decimal("800.00"))
        statement.refresh_from_db()
        self.assertEqual(statement.net_amount, Decimal("50.00"))
