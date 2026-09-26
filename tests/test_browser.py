"""Real browser checks; opt in with RUN_BROWSER_TESTS=1. Uses a test database."""
import os
import unittest
from pathlib import Path
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone

from payroll.services import create_payroll_run, submit_for_review, finalize_payroll_run
from schedules.services import create_shift
from .factories import workspace, employee, completed, payroll_setup, PASSWORD


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

    def login(self, user):
        if self.context is None:
            from playwright.sync_api import sync_playwright
            self.runtime = sync_playwright().start()
            self.browser = self.runtime.chromium.launch()
            self.context = self.browser.new_context(viewport={"width": 1440, "height": 900})
            self.page = self.context.new_page()
            self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.live_server_url + "/login/")
        self.page.locator('[name="username"]').fill(user.email)
        self.page.locator('[name="password"]').fill(PASSWORD)
        self.page.locator('button[type="submit"]').click()
        self.page.wait_for_url("**/home/" if user.role == "EMPLOYER" else "**/attendance/my/")

    def inspect(self, path, name):
        response = self.page.goto(self.live_server_url + path)
        self.assertEqual(response.status, 200, path)
        self.page.screenshot(path=str(self.artifacts / f"{name}.png"), full_page=True)
        dimensions = self.page.evaluate("""() => ({width: innerWidth, content: document.documentElement.scrollWidth})""")
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

    def test_empty_employer_and_employee_pages_at_three_widths(self):
        self.login(self.owner)
        for width in (1440, 1024, 390):
            self.page.set_viewport_size({"width": width, "height": 900})
            for path, name in (("/home/", "dashboard"), ("/employees/", "employees"), ("/schedules/", "schedules"),
                               ("/attendance/", "attendance"), ("/timesheets/", "timesheets"), ("/reports/", "reports"),
                               ("/payroll/", "payroll"), ("/payroll/setup/", "payroll-settings"), ("/payroll/employees/", "pay-profiles"),
                               ("/payroll/holidays/", "holidays"), ("/settings/", "settings"), ("/schedules/new/", "shift-form"),
                               (f"/payroll/employees/{self.emp.pk}/", "pay-profile")):
                with self.subTest(path=path, width=width):
                    self.inspect(path, f"empty-{name}-{width}")
        self.context.clear_cookies()
        self.login(self.emp.user)
        for width in (1440, 390):
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
        run = submit_for_review(run=run, actor=self.owner)
        run = finalize_payroll_run(run=run, actor=self.owner, review_note="Synthetic UI data")
        statement = run.statements.get()
        self.login(self.owner)
        for width in (1440, 390):
            self.page.set_viewport_size({"width": width, "height": 900})
            for path, name in ((f"/employees/{self.emp.pk}/", "employee-detail"), (f"/schedules/{work.pk}/", "shift-detail"),
                               (f"/timesheets/{sheet.pk}/", "timesheet-detail"), (f"/payroll/runs/{run.pk}/", "run-detail"),
                               ("/payroll/setup/", "rules"), ("/payroll/employees/", "pay-profiles"), ("/reports/?tab=hours", "hours")):
                with self.subTest(path=path, width=width):
                    self.inspect(path, f"populated-{name}-{width}")
        self.context.clear_cookies()
        self.login(self.emp.user)
        for width in (1440, 390):
            self.page.set_viewport_size({"width": width, "height": 900})
            for path, name in ((f"/timesheets/my/{sheet.pk}/", "sheet"), ("/payroll/my/", "statements"),
                               (f"/payroll/my/{statement.pk}/", "payslip")):
                with self.subTest(path=path, width=width):
                    self.inspect(path, f"employee-populated-{name}-{width}")
