"""Real browser checks; opt in with RUN_BROWSER_TESTS=1. Uses a test database."""
import os
import json
import re
import unittest
from pathlib import Path
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import RequestFactory
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone

from payroll.services import create_payroll_run, submit_for_review, finalize_payroll_run, add_adjustment
from payroll.models import PayrollHoliday
from employees.services import issue_employee_invitation
from schedules.services import create_shift
from .factories import workspace, employee, completed, payroll_setup, shift, PASSWORD, DAY
from .factories import review_statutory


@unittest.skipUnless(os.environ.get("RUN_BROWSER_TESTS") == "1", "Set RUN_BROWSER_TESTS=1 for browser scenarios")
class BrowserTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.artifacts = Path(".artifacts/ui")
        cls.artifacts.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.org, self.owner = workspace()
        self.emp = employee(self.org)
        self.context = None
        self.errors = []

    def tearDown(self):
        if self.context:
            self.context.close()
            self.browser.close()
            self.runtime.stop()

    def open_browser(self):
        if self.context is None:
            from playwright.sync_api import sync_playwright
            self.runtime = sync_playwright().start()
            self.browser = self.runtime.chromium.launch()
            self.context = self.browser.new_context(viewport={"width": 1440, "height": 900})
            self.page = self.context.new_page()
            self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def login(self, user):
        self.open_browser()
        self.page.goto(self.live_server_url + "/login/")
        self.page.locator('[name="username"]').fill(user.email)
        self.page.locator('[name="password"]').fill(PASSWORD)
        self.page.locator('button[type="submit"]').click()
        self.page.wait_for_url("**/home/" if user.role == "EMPLOYER" else "**/attendance/my/")

    def inspect(self, path, name, *, navigate=True, status=200):
        self.errors.clear()
        if navigate:
            response = self.page.goto(self.live_server_url + path)
            self.assertEqual(response.status, status, path)
        self.page.screenshot(path=str(self.artifacts / f"{name}.png"), full_page=True)
        dimensions = self.page.evaluate("""() => ({width: innerWidth, content: document.documentElement.scrollWidth,
          overflowing: Array.from(document.querySelectorAll('main *')).filter(el => {
            const r = el.getBoundingClientRect();
            return r.width && (r.right > innerWidth + 1 || r.left < -1);
          }).slice(0, 15).map(el => ({tag: el.tagName, classes: el.className, text: el.textContent.trim().slice(0, 90)}))})""")
        (self.artifacts / f"{name}.json").write_text(json.dumps({"path": path, **dimensions}, indent=2), encoding="utf-8")
        self.assertLessEqual(dimensions["content"], dimensions["width"] + 1, f"Page overflow: {path}: {dimensions}")
        self.assertFalse(self.errors, f"JavaScript errors on {path}: {self.errors}")
        self.assertEqual(self.page.locator("h1").count(), 1, f"One page heading required: {path}")
        # Browser table layout must align headers with the corresponding cells.
        misaligned = self.page.evaluate("""() => Array.from(document.querySelectorAll('table')).flatMap(table => {
          const head = Array.from(table.querySelectorAll('thead tr:last-child th'));
          const body = table.querySelector('tbody tr');
          if (!body || body.children.length !== head.length || Array.from(body.children).some(c => c.colSpan > 1)) return [];
          return head.flatMap((th, i) => {
            const td = body.children[i];
            if (!th.getClientRects().length || !td.getClientRects().length) return [];
            return Math.abs(th.getBoundingClientRect().x - td.getBoundingClientRect().x) > 2 ? [th.textContent.trim()] : [];
          });
        })""")
        self.assertFalse(misaligned, f"Misaligned columns on {path}: {misaligned}")
        # A flex basis used as a mobile height must not stretch ordinary inputs.
        tall_inputs = self.page.locator('main input:not([type="hidden"]), main select').evaluate_all(
            "nodes => nodes.filter(el => el.getBoundingClientRect().height > 60).map(el => el.name)"
        )
        self.assertFalse(tall_inputs, f"Oversized form controls on {path}: {tall_inputs}")
        for heading in self.page.locator('.payroll-empty-state > h3').all():
            self.assertGreater(heading.bounding_box()['width'], 180, "Empty message needs a full text column")

    def test_empty_employer_and_employee_pages_at_three_widths(self):
        self.login(self.owner)
        for width in (1440, 1024, 390):
            self.page.set_viewport_size({"width": width, "height": 900})
            for path, name in (("/home/", "dashboard"), ("/employees/", "employees"), ("/schedules/", "schedules"),
                               ("/attendance/", "attendance"), ("/timesheets/", "timesheets"), ("/reports/", "reports"),
                               ("/payroll/", "payroll"), ("/payroll/setup/", "payroll-settings"), ("/payroll/employees/", "pay-profiles"),
                               ("/payroll/holidays/", "holidays"), ("/settings/", "settings"), ("/schedules/new/", "shift-form"),
                               ("/employees/new/", "employee-form"), ("/payroll/runs/new/", "payroll-form"),
                               ("/reports/?report=hours", "report-hours"), ("/reports/?report=timesheets", "report-timesheets"),
                               ("/reports/?report=activity", "report-activity"),
                               (f"/payroll/employees/{self.emp.pk}/rates/new/", "rate-form"),
                               (f"/payroll/employees/{self.emp.pk}/", "pay-profile")):
                with self.subTest(path=path, width=width):
                    self.inspect(path, f"empty-{name}-{width}")
        self.context.clear_cookies()
        self.login(self.emp.user)
        for width in (1440, 1024, 390):
            self.page.set_viewport_size({"width": width, "height": 900})
            for path, name in (("/attendance/my/", "home"), ("/schedules/my/", "schedule"),
                               ("/timesheets/my/", "timesheets"), ("/payroll/my/", "pay"), ("/profile/", "profile")):
                with self.subTest(path=path, width=width):
                    self.inspect(path, f"employee-empty-{name}-{width}")

    def test_populated_pages(self):
        work, _, sheet = completed(self.org, self.emp)
        payroll_setup(self.org, self.emp)
        run = create_payroll_run(organization=self.org, actor=self.owner, period_start=date(2026, 9, 1),
                                period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))
        review_statutory(run)
        run = submit_for_review(run=run, actor=self.owner)
        run = finalize_payroll_run(run=run, actor=self.owner, review_note="Synthetic UI data")
        statement = run.statements.get()
        editable = shift(self.org, self.emp, day=DAY + timedelta(days=5))
        _, _, pending_sheet = completed(self.org, self.emp, day=date(2026, 10, 1), approve=False)
        draft = create_payroll_run(organization=self.org, actor=self.owner, period_start=date(2026, 10, 1),
                                  period_end=date(2026, 10, 31), pay_date=date(2026, 10, 31))
        holiday = PayrollHoliday.objects.create(organization=self.org, date=date(2026, 1, 1), name="Test holiday",
            kind="REGULAR", worked_multiplier="2", overtime_multiplier="2.6", created_by=self.owner)
        self.login(self.owner)
        for width in (1440, 1024, 390):
            self.page.set_viewport_size({"width": width, "height": 900})
            for path, name in ((f"/employees/{self.emp.pk}/", "employee-detail"), (f"/schedules/{work.pk}/", "shift-detail"),
                               (f"/timesheets/{sheet.pk}/", "timesheet-detail"), (f"/payroll/runs/{run.pk}/", "run-detail"),
                               (f"/schedules/{editable.pk}/edit/", "shift-edit"),
                               (f"/employees/{self.emp.pk}/edit/", "employee-edit"),
                               (f"/employees/{self.emp.pk}/schedules/", "employee-schedules"),
                               (f"/employees/{self.emp.pk}/attendance/", "employee-attendance"),
                               (f"/employees/{self.emp.pk}/timesheets/", "employee-timesheets"),
                               (f"/timesheets/{pending_sheet.pk}/", "timesheet-review"),
                               (f"/payroll/runs/{draft.pk}/", "draft-run"),
                               (f"/payroll/holidays/{holiday.pk}/edit/", "holiday-edit"),
                               (f"/payroll/employees/{self.emp.pk}/", "pay-profile"),
                               ("/payroll/", "payroll-runs"), ("/payroll/holidays/", "holidays"),
                               ("/payroll/setup/", "rules"), ("/payroll/employees/", "pay-profiles"),
                               ("/reports/?report=hours&week_of=2026-09-21", "hours"),
                               ("/reports/?report=attendance&daily_date=2026-09-21", "attendance-report"),
                               ("/reports/?report=timesheets&start_date=2026-09-01&end_date=2026-09-30", "timesheet-report"),
                               ("/reports/?report=activity", "activity-report")):
                with self.subTest(path=path, width=width):
                    self.inspect(path, f"populated-{name}-{width}")
        self.context.clear_cookies()
        self.login(self.emp.user)
        for width in (1440, 1024, 390):
            self.page.set_viewport_size({"width": width, "height": 900})
            for path, name in ((f"/timesheets/my/{sheet.pk}/", "sheet"), ("/payroll/my/", "statements"),
                               (f"/payroll/my/{statement.pk}/", "payslip")):
                with self.subTest(path=path, width=width):
                    self.inspect(path, f"employee-populated-{name}-{width}")

    def test_public_pages(self):
        invitee = employee(self.org, suffix="invite", account=False)
        issue_employee_invitation(invitee, self.owner, RequestFactory().get("/"))
        token = re.search(r"/invitations/([^/]+)/", mail.outbox[-1].body).group(1)
        reset = f"/reset/{urlsafe_base64_encode(force_bytes(self.owner.pk))}/{default_token_generator.make_token(self.owner)}/"
        self.open_browser()
        for width in (1440, 390):
            self.page.set_viewport_size({"width": width, "height": 900})
            for path, name, status in (("/login/", "login", 200), ("/signup/", "signup", 200),
                    ("/password-reset/", "password-reset", 200), ("/password-reset/done/", "reset-sent", 200),
                    ("/reset/done/", "reset-complete", 200), (reset, "reset-password", 200),
                    (f"/invitations/{token}/", "invitation", 200), ("/invitations/invalid/", "invalid-invitation", 404)):
                with self.subTest(path=path, width=width):
                    self.inspect(path, f"public-{name}-{width}", status=status)

    def test_clock_confirmation_cycle(self):
        now = timezone.now()
        zone = ZoneInfo(self.org.timezone)
        create_shift(organization=self.org, employee=self.emp, actor=self.owner,
            work_date=timezone.localdate(now, zone), scheduled_start=now, scheduled_end=now + timedelta(hours=8),
            scheduled_break_minutes=30)
        self.login(self.emp.user)
        self.page.set_viewport_size({"width": 390, "height": 844})
        for action in ('Clock in', 'Start break', 'End break', 'Clock out'):
            self.page.get_by_role('button', name=action, exact=True).click()
            dialog = self.page.locator('[data-attendance-confirm-dialog]')
            self.assertTrue(dialog.is_visible())
            self.assertTrue(self.page.locator('[data-attendance-confirm-cancel]').evaluate('(e)=>e===document.activeElement'))
            self.inspect('/attendance/my/', f'employee-confirm-{action.replace(" ", "-").lower()}', navigate=False)
            self.page.locator('[data-attendance-confirm-cancel]').click()
            self.assertFalse(dialog.is_visible())
            self.page.get_by_role('button', name=action, exact=True).click()
            with self.page.expect_navigation():
                self.page.locator('[data-attendance-confirm-submit]').click()
        self.inspect('/attendance/my/', 'employee-shift-completed')

    def test_expanded_forms_and_dialogs(self):
        completed(self.org, self.emp)
        payroll_setup(self.org, self.emp)
        run = create_payroll_run(organization=self.org, actor=self.owner, period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))
        review_statutory(run)
        run = submit_for_review(run=run, actor=self.owner)
        self.login(self.owner)
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.page.goto(self.live_server_url + '/payroll/setup/')
            self.page.locator('.payroll-rule-profile-create > summary').click()
            self.inspect('/payroll/setup/', f'expanded-rule-profile-{width}', navigate=False)
            self.page.get_by_role('button', name='Create profile', exact=True).click()
            self.page.locator('.field-error').first.wait_for()
            self.assertTrue(self.page.locator('.payroll-rule-profile-create').evaluate('(e)=>e.open'))
            self.inspect('/payroll/setup/', f'invalid-rule-profile-{width}', navigate=False)
            self.page.goto(self.live_server_url + f'/payroll/runs/{run.pk}/')
            for name, selector in (('Finalize payroll', '#finalize-run-dialog'), ('Void run', '#void-run-dialog')):
                self.page.get_by_role('button', name=name, exact=True).click()
                self.assertTrue(self.page.locator(selector).is_visible())
                self.inspect(f'/payroll/runs/{run.pk}/', f'{name.replace(" ", "-")}-{width}', navigate=False)
                self.page.locator(selector + ' [data-payroll-dialog-close]').click()
            self.page.goto(self.live_server_url + f'/employees/{self.emp.pk}/')
            self.page.locator('[data-open-deactivation-dialog]').click()
            self.inspect(f'/employees/{self.emp.pk}/', f'deactivation-dialog-{width}', navigate=False)
            self.page.locator('[data-close-deactivation-dialog]').click()

    def test_schedule_row_menu_remains_clickable_outside_table(self):
        for offset in range(3):
            shift(self.org, self.emp, day=DAY + timedelta(days=offset))
        self.login(self.owner)
        for width in (1440, 390, 320):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.page.goto(self.live_server_url + '/schedules/')
            menu = self.page.locator('.schedule-row-menu').last
            trigger = menu.locator('summary')
            panel = menu.locator('.schedule-row-menu-popover')
            trigger.click()
            panel.wait_for(state='visible')
            self.assertEqual(panel.locator('a, button').count(), 3)
            for action in panel.locator('a, button').all():
                self.assertTrue(action.evaluate('''el => {
                    const r = el.getBoundingClientRect();
                    return el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
                }'''), f'Menu action clipped at {width}px: {action.inner_text()}')
            self.inspect('/schedules/', f'schedule-row-menu-{width}', navigate=False)
            self.page.keyboard.press('Escape')
            panel.wait_for(state='hidden')
            self.assertTrue(trigger.evaluate('el => el === document.activeElement'))
            trigger.click()
            panel.wait_for(state='visible')
            self.page.locator('h1').click()
            panel.wait_for(state='hidden')
            trigger.click()
            panel.wait_for(state='visible')
            panel.get_by_role('button', name='Cancel shift', exact=True).click()
            dialog = self.page.locator('dialog[open]')
            dialog.wait_for(state='visible')
            self.inspect('/schedules/', f'schedule-cancel-dialog-{width}', navigate=False)
            self.page.keyboard.press('Escape')
            dialog.wait_for(state='hidden')

    def test_statutory_review_missing_number_and_return_to_draft(self):
        completed(self.org, self.emp)
        payroll_setup(self.org, self.emp)
        run = create_payroll_run(organization=self.org, actor=self.owner, period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))
        for kind, amount in (('DEDUCTION', '30'), ('EMPLOYER_CONTRIBUTION', '60')):
            add_adjustment(run=run, actor=self.owner, employee=self.emp, kind=kind,
                label='Synthetic SSS ' + kind, amount=amount, effective_date=DAY, note='Test-only reviewed amount')
        statement = run.statements.get()
        employee_line = statement.lines.get(kind='DEDUCTION').pk
        employer_line = statement.lines.get(kind='EMPLOYER_CONTRIBUTION').pk
        path = f'/payroll/runs/{run.pk}/'
        self.login(self.owner)
        for width in (1440, 390, 320):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.page.goto(self.live_server_url + path)
            self.page.locator('.payroll-statutory-review > summary').click()
            self.inspect(path, f'statutory-review-{width}', navigate=False)
            bounds = self.page.locator('.payroll-statutory-form').bounding_box()
            self.assertLessEqual(bounds['x'] + bounds['width'], width)
        self.page.set_viewport_size({'width': 390, 'height': 900})
        for agency in ('SSS', 'PHILHEALTH', 'PAGIBIG', 'WITHHOLDING'):
            self.page.goto(self.live_server_url + path)
            self.page.locator('.payroll-statutory-review > summary').click()
            def field(name):
                return self.page.locator(f'[name="statutory-{statement.pk}-{name}"]')
            field('agency').select_option(agency)
            field('registration').select_option('PENDING' if agency == 'SSS' else 'REGISTERED')
            field('employee_treatment').select_option('LINE' if agency == 'SSS' else 'ZERO')
            field('employer_treatment').select_option('LINE' if agency == 'SSS' else ('NOT_APPLICABLE' if agency == 'WITHHOLDING' else 'ZERO'))
            if agency == 'SSS':
                field('employee_line').select_option(str(employee_line))
                field('employer_line').select_option(str(employer_line))
            field('source_reference').fill('Synthetic cutoff calculation TEST-01')
            field('review_note').fill('Test-only manual amount / reviewed zero for this period.')
            if agency == 'SSS':
                with self.page.expect_navigation():
                    self.page.get_by_role('button', name='Save statutory review').click()
                self.assertTrue(self.page.locator('.payroll-statutory-review').evaluate('e => e.open'))
                self.assertIn('follow-up', self.page.locator('.payroll-statutory-form .field-error').inner_text())
                field('registration_follow_up').fill('HR is processing the registration under case TEST-01.')
            with self.page.expect_navigation():
                self.page.get_by_role('button', name='Save statutory review').click()
        self.assertIn('Statutory items · Reviewed', self.page.locator('.payroll-statutory-review > summary').inner_text())
        with self.page.expect_navigation():
            self.page.get_by_role('button', name='Submit for review', exact=True).click()
        self.page.get_by_role('button', name='Return to draft', exact=True).click()
        self.page.locator('#payroll-confirm-dialog').wait_for(state='visible')
        self.page.locator('#payroll-confirm-dialog [data-payroll-confirm-cancel]').click()
        self.assertTrue(self.page.get_by_role('button', name='Return to draft', exact=True).is_enabled())
        self.page.get_by_role('button', name='Return to draft', exact=True).click()
        with self.page.expect_navigation():
            self.page.locator('#payroll-confirm-dialog [data-payroll-confirm-submit]').click()
        self.assertTrue(self.page.get_by_role('button', name='Submit for review', exact=True).is_visible())
        self.page.locator('.payroll-lines-row details > summary').click()
        self.page.get_by_role('button', name='Remove', exact=True).first.click()
        with self.page.expect_navigation():
            self.page.locator('#payroll-confirm-dialog [data-payroll-confirm-submit]').click()
        self.assertIn('Needs review', self.page.locator('.payroll-statutory-review > summary').inner_text())

    def test_calendar_selection_and_review(self):
        employee(self.org, suffix='second')
        self.login(self.owner)
        for width in (1440, 390, 320):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.page.goto(self.live_server_url + '/schedules/new/')
            for checkbox in self.page.locator('[data-employee-checkbox]').all():
                checkbox.check()
            dates = self.page.locator('[data-calendar-grid] [data-date]')
            dates.nth(15).click()
            dates.nth(16).click()
            self.page.locator('[name="start_time"]').fill('22:00')
            self.page.locator('[name="end_time"]').fill('03:00')
            self.page.locator('[name="scheduled_break_minutes"]').fill('30')
            self.inspect('/schedules/new/', f'calendar-selected-{width}', navigate=False)
            with self.page.expect_navigation():
                self.page.locator('[data-batch-main-submit]').click()
            self.page.locator('[data-batch-review-dialog]').wait_for(state='visible')
            self.assertIn('Create 4 shifts?', self.page.locator('#batch-review-title').inner_text())
            self.inspect('/schedules/new/', f'calendar-review-{width}', navigate=False)
            self.page.locator('[data-batch-review-back]').click()
            self.assertEqual(self.page.locator('[data-employee-checkbox]:checked').count(), 2)
