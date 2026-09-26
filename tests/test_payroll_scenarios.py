"""Philippine payroll simulations; figures are synthetic, not statutory rates."""
from datetime import date
from decimal import Decimal
from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from audit.models import AuditEvent
from payroll.models import (PayrollLine, PayrollRun, PayrollSettings, EmployeePayProfile,
    EmployeePayRate, PayrollRuleProfile, PayrollRuleSet, PayrollRuleAssignment)
from payroll.services import (create_payroll_run, submit_for_review, resolve_payroll_exception,
    add_adjustment, remove_adjustment, calculate_payroll_run, finalize_payroll_run, return_payroll_to_draft)
from payroll.statutory import AGENCIES, record_statutory_review, statutory_review_rows
from .factories import workspace, employee, payroll_setup, completed, review_statutory, instant, DAY


class PhilippinePayrollScenarios(TestCase):
    def setUp(self):
        self.org, self.owner = workspace()
        self.emp = employee(self.org)
        payroll_setup(self.org, self.emp)

    def make_run(self):
        return create_payroll_run(organization=self.org, actor=self.owner,
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))

    def test_missing_statutory_review_cannot_silently_mean_zero(self):
        completed(self.org, self.emp)
        run = self.make_run()
        with self.assertRaisesMessage(ValidationError, 'statutory'):
            submit_for_review(run=run, actor=self.owner)

    def test_empty_regular_run_cannot_be_submitted(self):
        run = self.make_run()
        for issue in run.exceptions.all():
            resolve_payroll_exception(exception=issue, actor=self.owner, note='No work in this test period.')
        with self.assertRaisesMessage(ValidationError, 'at least one employee'):
            submit_for_review(run=run, actor=self.owner)

    def prepare(self):
        completed(self.org, self.emp)
        return self.make_run()

    def line(self, run, kind, amount, label='Synthetic item', emp=None):
        statement = add_adjustment(run=run, actor=self.owner, employee=emp or self.emp,
            kind=kind, label=label, amount=amount, effective_date=DAY,
            note='Synthetic reviewed calculation; not a statutory contribution schedule.')
        return statement.lines.filter(source='MANUAL').latest('pk')

    def review(self, statement, agency='SSS', **overrides):
        values = dict(statement=statement, actor=self.owner, agency=agency, registration='REGISTERED',
            employee_treatment='ZERO', employer_treatment='NOT_APPLICABLE' if agency == 'WITHHOLDING' else 'ZERO',
            source_reference='TEST-ONLY calculation for September 2026',
            review_note='Explicit synthetic zero amount for this cutoff, independently reviewed.')
        values.update(overrides)
        return record_statutory_review(**values)

    def finalize(self, run):
        run = submit_for_review(run=run, actor=self.owner)
        return finalize_payroll_run(run=run, actor=self.owner, review_note='Synthetic payroll reconciled.')

    def test_each_missing_registration_needs_review_without_erasing_pay(self):
        run = self.prepare()
        shares = {}
        for agency, _ in AGENCIES:
            shares[agency] = (self.line(run, 'DEDUCTION', '10', agency),
                None if agency == 'WITHHOLDING' else self.line(run, 'EMPLOYER_CONTRIBUTION', '20', agency))
        statement = run.statements.get()
        for agency, _ in AGENCIES:
            ee, er = shares[agency]
            self.review(statement, agency=agency, registration='PENDING',
                employee_treatment='LINE', employee_line=ee,
                employer_treatment='LINE' if er else 'NOT_APPLICABLE', employer_line=er,
                registration_follow_up='HR is obtaining the missing number; follow-up case TEST-01.',
                review_note='Reviewed amount still included while registration is pending.')
        run = self.finalize(run)
        statement.refresh_from_db()
        self.assertEqual(statement.gross_amount, Decimal('800.00'))
        self.assertEqual(statement.deduction_amount, Decimal('40.00'))
        self.assertEqual(statement.employer_contribution_amount, Decimal('60.00'))
        self.assertEqual(statement.net_amount, Decimal('760.00'))
        self.assertTrue(all(row['current'] for row in statutory_review_rows(statement)))
        self.assertEqual(AuditEvent.objects.filter(action='PAYROLL_STATUTORY_REVIEWED').count(), 4)
        self.client.force_login(self.emp.user)
        payslip = self.client.get(f'/payroll/my/{statement.pk}/')
        self.assertContains(payslip, '760.00')
        self.assertContains(payslip, '60.00')
        self.client.force_login(self.owner)
        exported = self.client.get(f'/payroll/runs/{run.pk}/export.csv')
        self.assertEqual(exported.status_code, 200)
        self.assertIn(b'760.00', exported.content)

    def test_pending_registration_requires_follow_up(self):
        statement = self.prepare().statements.get()
        for agency, _ in AGENCIES:
            with self.subTest(agency=agency), self.assertRaisesMessage(ValidationError, 'follow-up'):
                self.review(statement, agency=agency, registration='PENDING')

    def test_mixed_employees_missing_sss_or_philhealth_and_different_rules(self):
        other = employee(self.org, suffix='no-philhealth')
        EmployeePayProfile.objects.create(employee=other, work_location='Manila', payroll_region='NCR',
            payroll_timezone='Asia/Manila', minimum_wage_confirmed=True,
            wage_order_reference='TEST-ONLY', night_differential_eligible=True)
        EmployeePayRate.objects.create(employee=other, hourly_rate=200, effective_from=DAY, created_by=self.owner)
        special = PayrollRuleProfile.objects.create(organization=self.org, code='reviewed-night',
            name='Reviewed night policy', created_by=self.owner)
        PayrollRuleSet.objects.create(organization=self.org, rule_profile=special, effective_from=DAY,
            night_differential_rate=Decimal('0.20'), source_references='Synthetic policy',
            reviewed_by='Test reviewer', reviewed_at=instant(), created_by=self.owner)
        PayrollRuleAssignment.objects.create(organization=self.org, employee=other, rule_profile=special,
            effective_from=DAY, assigned_by=self.owner)
        for emp in (self.emp, other):
            completed(self.org, emp, start=22, end=3, break_minutes=0)
        run = self.make_run()
        self.assertEqual(run.statements.get(employee=self.emp).gross_amount, Decimal('550'))
        self.assertEqual(run.statements.get(employee=other).gross_amount, Decimal('1200'))
        for emp in (self.emp, other):
            self.line(run, 'DEDUCTION', '10', 'SSS', emp=emp)
            self.line(run, 'DEDUCTION', '20', 'PhilHealth', emp=emp)
            self.line(run, 'EMPLOYER_CONTRIBUTION', '30', 'SSS employer', emp=emp)
            self.line(run, 'EMPLOYER_CONTRIBUTION', '20', 'PhilHealth employer', emp=emp)
        for statement in run.statements.all():
            for agency, label in AGENCIES:
                pending = (statement.employee_id == self.emp.pk and agency == 'SSS') or (
                    statement.employee_id == other.pk and agency == 'PHILHEALTH')
                values = {}
                if agency in ('SSS', 'PHILHEALTH'):
                    values = dict(employee_treatment='LINE', employee_line=statement.lines.get(label=label),
                        employer_treatment='LINE', employer_line=statement.lines.get(label=label + ' employer'))
                self.review(statement, agency, registration='PENDING' if pending else 'REGISTERED',
                    registration_follow_up='HR follow-up TEST-MIXED' if pending else '', **values)
        self.finalize(run)
        self.assertEqual(run.statements.get(employee=self.emp).net_amount, Decimal('520'))
        self.assertEqual(run.statements.get(employee=other).net_amount, Decimal('1170'))

    def test_repeated_review_does_not_duplicate_deductions(self):
        run = self.prepare()
        line = self.line(run, 'DEDUCTION', '10')
        statement = run.statements.get()
        for _ in range(2):
            self.review(statement, employee_treatment='LINE', employee_line=line)
        self.assertEqual(statement.lines.filter(kind='DEDUCTION').count(), 1)
        statement.refresh_from_db()
        self.assertEqual(statement.net_amount, Decimal('790'))

    def test_missing_number_is_not_an_exemption(self):
        statement = self.prepare().statements.get()
        for agency, _ in AGENCIES:
            with self.subTest(agency=agency), self.assertRaisesMessage(ValidationError, 'not an exemption'):
                self.review(statement, agency=agency, registration='PENDING', employee_treatment='NOT_APPLICABLE',
                    registration_follow_up='HR follow-up TEST-02')

    def test_unreviewed_zero_does_not_pass_but_explicit_zero_does(self):
        run = self.prepare()
        statement = run.statements.get()
        for agency, _ in AGENCIES[:-1]:
            self.review(statement, agency)
        with self.assertRaisesMessage(ValidationError, 'Withholding tax'):
            submit_for_review(run=run, actor=self.owner)
        self.review(statement, 'WITHHOLDING')
        self.assertEqual(self.finalize(run).status, 'FINALIZED')

    def test_first_cutoff_can_reference_second_cutoff_without_duplicate_deduction(self):
        PayrollSettings.objects.filter(organization=self.org).update(frequency='SEMI_MONTHLY')
        completed(self.org, self.emp, day=date(2026, 9, 10))
        run = create_payroll_run(organization=self.org, actor=self.owner,
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 15), pay_date=date(2026, 9, 15))
        statement = run.statements.get()
        for agency, _ in AGENCIES:
            self.review(statement, agency, employee_treatment='OTHER_PERIOD',
                employer_treatment='NOT_APPLICABLE' if agency == 'WITHHOLDING' else 'OTHER_PERIOD',
                source_reference='Synthetic monthly reconciliation / Sep 16–30 cutoff',
                review_note='Reviewed allocation to second cutoff; no amount in this first cutoff.')
        self.finalize(run)
        self.assertEqual(run.statements.get().net_amount, Decimal('800'))
        completed(self.org, self.emp)
        second = create_payroll_run(organization=self.org, actor=self.owner,
            period_start=date(2026, 9, 16), period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))
        with self.assertRaisesMessage(ValidationError, 'statutory'):
            submit_for_review(run=second, actor=self.owner)
        self.assertEqual(second.statements.get().deduction_amount, 0)

    def test_reviewed_not_applicable_needs_evidence(self):
        statement = self.prepare().statements.get()
        with self.assertRaises(ValidationError):
            self.review(statement, registration='NOT_APPLICABLE')
        self.review(statement, registration='NOT_APPLICABLE', employee_treatment='NOT_APPLICABLE',
            employer_treatment='NOT_APPLICABLE', review_note='Synthetic exemption case with external reviewer evidence.')
        statement.refresh_from_db()
        self.assertTrue(statutory_review_rows(statement)[0]['current'])

    def test_source_and_reason_are_required_for_zero_and_exemption(self):
        statement = self.prepare().statements.get()
        for field in ('source_reference', 'review_note'):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.review(statement, **{field: '  '})

    def test_both_shares_need_explicit_decisions(self):
        statement = self.prepare().statements.get()
        for field in ('employee_treatment', 'employer_treatment'):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.review(statement, **{field: ''})

    def test_missing_amount_line_cannot_pass_as_entered(self):
        statement = self.prepare().statements.get()
        with self.assertRaisesMessage(ValidationError, 'positive manual line'):
            self.review(statement, employee_treatment='LINE')

    def test_wrong_employee_or_share_line_is_rejected(self):
        run = self.prepare()
        other = employee(self.org, suffix='other')
        other_line = self.line(run, 'DEDUCTION', '10', emp=other)
        employer_line = self.line(run, 'EMPLOYER_CONTRIBUTION', '20')
        statement = run.statements.get(employee=self.emp)
        for line in (other_line, employer_line):
            with self.subTest(line=line.pk), self.assertRaises(ValidationError):
                self.review(statement, employee_treatment='LINE', employee_line=line)

    def test_same_line_cannot_cover_two_agencies(self):
        run = self.prepare()
        line = self.line(run, 'DEDUCTION', '10')
        statement = run.statements.get()
        self.review(statement, 'SSS', employee_treatment='LINE', employee_line=line)
        with self.assertRaisesMessage(ValidationError, 'another statutory item'):
            self.review(statement, 'PHILHEALTH', employee_treatment='LINE', employee_line=line)

    def test_zero_treatment_cannot_hide_selected_deduction(self):
        run = self.prepare()
        line = self.line(run, 'DEDUCTION', '10')
        with self.assertRaises(ValidationError):
            self.review(run.statements.get(), employee_line=line)

    def test_tax_cannot_be_recorded_as_employer_contribution(self):
        run = self.prepare()
        line = self.line(run, 'EMPLOYER_CONTRIBUTION', '10')
        with self.assertRaises(ValidationError):
            self.review(run.statements.get(), 'WITHHOLDING', employer_treatment='LINE', employer_line=line)

    def test_bonus_or_deduction_change_requires_new_review(self):
        run = self.prepare()
        review_statutory(run)
        self.line(run, 'EARNING', '100', 'Reviewed bonus')
        with self.assertRaisesMessage(ValidationError, 'statutory'):
            submit_for_review(run=run, actor=self.owner)
        review_statutory(run)
        self.finalize(run)
        self.assertEqual(run.statements.get().net_amount, Decimal('900'))

    def test_deleting_deduction_invalidates_review(self):
        run = self.prepare()
        line = self.line(run, 'DEDUCTION', '10')
        review_statutory(run)
        self.review(run.statements.get(), employee_treatment='LINE', employee_line=line)
        remove_adjustment(run=run, actor=self.owner, line_id=line.pk)
        with self.assertRaisesMessage(ValidationError, 'statutory'):
            submit_for_review(run=run, actor=self.owner)

    def test_recalculate_requires_new_review_and_retains_audit(self):
        run = self.prepare()
        review_statutory(run)
        calculate_payroll_run(run, actor=self.owner)
        with self.assertRaisesMessage(ValidationError, 'statutory'):
            submit_for_review(run=run, actor=self.owner)
        self.assertEqual(AuditEvent.objects.filter(action='PAYROLL_STATUTORY_REVIEWED').count(), 4)
        self.assertTrue(any(p.data['statements'][0]['calculation_inputs'].get('statutory_reviews')
                            for p in run.calculation_previews.all()))

    def test_finalization_rechecks_even_a_legacy_review_run(self):
        run = self.prepare()
        PayrollRun.objects.filter(pk=run.pk).update(status='REVIEW')
        with self.assertRaisesMessage(ValidationError, 'statutory'):
            finalize_payroll_run(run=run, actor=self.owner, review_note='Legacy run recheck')
        return_payroll_to_draft(run=run, actor=self.owner)
        review_statutory(run)
        self.assertEqual(self.finalize(run).status, 'FINALIZED')
        with self.assertRaises(ValidationError):
            return_payroll_to_draft(run=run, actor=self.owner)

    def test_unconfirmed_classification_is_not_silently_paid_with_default_premiums(self):
        profile = self.emp.payroll_profile
        profile.rank_and_file = False
        profile.save()
        run = self.prepare()
        self.assertTrue(run.exceptions.filter(code='PAY_CLASSIFICATION_UNCONFIRMED').exists())
        with self.assertRaises(ValidationError):
            submit_for_review(run=run, actor=self.owner)

    def test_finalized_review_is_locked(self):
        run = self.prepare()
        review_statutory(run)
        self.finalize(run)
        statement = run.statements.get()
        before = deepcopy(statement.snapshot)
        with self.assertRaises(ValidationError):
            self.review(statement)
        statement.refresh_from_db()
        self.assertEqual(statement.snapshot, before)

    def test_other_owner_and_employee_cannot_review(self):
        statement = self.prepare().statements.get()
        _, other_owner = workspace('other')
        for actor in (other_owner, self.emp.user):
            with self.subTest(actor=actor.pk), self.assertRaises(PermissionDenied):
                self.review(statement, actor=actor)

    def test_invalid_adjustment_amounts_raise_validation_not_server_errors(self):
        run = self.prepare()
        for amount in ('NaN', 'Infinity', '-Infinity', 'invalid', '0', '-1', '0.001', '1000000000000', None):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.line(run, 'DEDUCTION', amount)
        self.assertFalse(run.statements.get().lines.filter(source='MANUAL').exists())

    def test_negative_net_and_employer_share_are_distinct(self):
        run = self.prepare()
        self.line(run, 'EMPLOYER_CONTRIBUTION', '900')
        self.assertEqual(run.statements.get().net_amount, Decimal('800'))
        self.line(run, 'DEDUCTION', '900')
        review_statutory(run)
        with self.assertRaisesMessage(ValidationError, 'exceed gross'):
            submit_for_review(run=run, actor=self.owner)

    def test_night_work_requires_confirmed_eligibility(self):
        profile = self.emp.payroll_profile
        profile.night_differential_eligible = False
        profile.save()
        completed(self.org, self.emp, start=22, end=3, break_minutes=30)
        run = self.make_run()
        self.assertTrue(run.exceptions.filter(code='NIGHT_ELIGIBILITY_UNCONFIRMED').exists())
        review_statutory(run)
        with self.assertRaisesMessage(ValidationError, 'exceptions'):
            submit_for_review(run=run, actor=self.owner)
        profile.night_differential_eligible = True
        profile.save()
        calculate_payroll_run(run, actor=self.owner)
        self.assertEqual(run.statements.get().gross_amount, Decimal('495'))
        review_statutory(run)
        self.finalize(run)

    def test_missing_work_setup_blocks_payroll(self):
        profile = self.emp.payroll_profile
        profile.work_location = ''
        profile.save()
        run = self.prepare()
        self.assertTrue(run.exceptions.filter(code='WORK_LOCATION_MISSING').exists())
        with self.assertRaises(ValidationError):
            submit_for_review(run=run, actor=self.owner)

    def test_statutory_form_preserves_invalid_input_and_scopes_statement(self):
        run = self.prepare()
        statement = run.statements.get()
        self.client.force_login(self.owner)
        response = self.client.post(f'/payroll/runs/{run.pk}/', {
            'action': 'statutory_review', 'statement_id': statement.pk,
            f'statutory-{statement.pk}-agency': 'SSS',
            f'statutory-{statement.pk}-registration': 'PENDING',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'payroll-statutory-review" open')
        self.assertContains(response, 'This field is required')
        self.client.force_login(self.emp.user)
        self.assertEqual(self.client.post(f'/payroll/runs/{run.pk}/', {'action': 'statutory_review',
            'statement_id': statement.pk}).status_code, 403)
