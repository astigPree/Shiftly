import csv
import io
from datetime import date

from django.test import TestCase
from django.urls import reverse

from payroll.services import create_payroll_run, submit_for_review, finalize_payroll_run
from reports.services import export_timesheets_csv, CSV_HEADERS
from .factories import workspace, employee, completed, payroll_setup, DAY


class PageAndPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org, cls.owner = workspace()
        cls.emp = employee(cls.org)
        cls.work, cls.session, cls.sheet = completed(cls.org, cls.emp)
        payroll_setup(cls.org, cls.emp)
        cls.pay_run = create_payroll_run(organization=cls.org, actor=cls.owner,
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))
        cls.org2, cls.owner2 = workspace("other")
        cls.emp2 = employee(cls.org2, "other")
        cls.work2, _, cls.sheet2 = completed(cls.org2, cls.emp2)

    def employer_pages(self):
        emp, work, sheet, run = self.emp.pk, self.work.pk, self.sheet.pk, self.pay_run.pk
        return ["/home/", "/settings/", "/employees/", "/employees/new/", f"/employees/{emp}/",
            f"/employees/{emp}/edit/", f"/employees/{emp}/schedules/", f"/employees/{emp}/attendance/", f"/employees/{emp}/timesheets/",
            "/schedules/", "/schedules/new/", f"/schedules/{work}/", "/attendance/", "/timesheets/", f"/timesheets/{sheet}/",
            "/reports/", "/reports/?tab=hours", "/reports/?tab=timesheets", "/reports/?tab=activity", "/payroll/",
            "/payroll/setup/", "/payroll/employees/", f"/payroll/employees/{emp}/", f"/payroll/employees/{emp}/rates/new/",
            "/payroll/holidays/", "/payroll/runs/new/", f"/payroll/runs/{run}/"]

    def test_all_employer_pages_render(self):
        self.client.force_login(self.owner)
        for path in self.employer_pages():
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_anonymous_cannot_access_employer_pages(self):
        for path in self.employer_pages():
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 302)

    def test_employee_cannot_access_employer_pages(self):
        self.client.force_login(self.emp.user)
        for path in self.employer_pages():
            if path == "/home/":
                continue
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_employee_pages_and_own_records(self):
        self.client.force_login(self.emp.user)
        for path in ("/attendance/my/", "/schedules/my/", "/timesheets/my/", f"/timesheets/my/{self.sheet.pk}/", "/profile/", "/payroll/my/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, self.emp2.full_name)
        self.assertEqual(self.client.get(f"/timesheets/my/{self.sheet2.pk}/").status_code, 404)

    def test_foreign_object_read_and_write_are_blocked(self):
        self.client.force_login(self.owner2)
        for path in (f"/employees/{self.emp.pk}/", f"/schedules/{self.work.pk}/", f"/timesheets/{self.sheet.pk}/",
                     f"/payroll/employees/{self.emp.pk}/", f"/payroll/runs/{self.pay_run.pk}/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        for path in (f"/employees/{self.emp.pk}/status/", f"/schedules/{self.work.pk}/cancel/",
                     f"/timesheets/{self.sheet.pk}/approve/", f"/payroll/runs/{self.pay_run.pk}/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, {"action": "void", "reason": "Foreign"}).status_code, 404)

    def test_action_gets_cannot_mutate_data(self):
        self.client.force_login(self.owner)
        for path in (f"/employees/{self.emp.pk}/status/", f"/employees/{self.emp.pk}/invitation/",
                     f"/schedules/{self.work.pk}/cancel/", f"/timesheets/{self.sheet.pk}/approve/",
                     f"/timesheets/{self.sheet.pk}/reject/", "/payroll/runs/create/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 405)
        self.client.force_login(self.emp.user)
        for path in (f"/attendance/shifts/{self.work.pk}/clock-in/", f"/attendance/sessions/{self.session.pk}/clock-out/",
                     f"/attendance/sessions/{self.session.pk}/break/start/", f"/attendance/sessions/{self.session.pk}/break/end/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 405)

    def test_invalid_filters_and_page_numbers_do_not_crash(self):
        self.client.force_login(self.owner)
        for path in ("/employees/", "/schedules/", "/attendance/", "/timesheets/", "/reports/", "/payroll/", "/payroll/employees/", "/payroll/holidays/"):
            for params in ({"page": "oops"}, {"page": "-1"}, {"page": "999"},
                           {"start_date": "bad", "end_date": "bad", "employee": "bad", "status": "bad"}):
                with self.subTest(path=path, params=params):
                    self.assertIn(self.client.get(path, params).status_code, (200, 302, 400))

    def test_csv_filters_timezone_and_formula_protection(self):
        self.org.name = "=FORMULA()"
        self.org.save()
        response = export_timesheets_csv(organization=self.org,
            filters={"start_date": DAY, "end_date": DAY, "employee": self.emp, "status": "APPROVED"})
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0], CSV_HEADERS)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], "'=FORMULA()")
        self.assertIn("+08:00", rows[1][4])
        self.assertEqual(rows[1][10], "480")
        self.assertNotIn(self.emp2.full_name, response.content.decode())

    def test_finalized_payslip_export_and_employee_visibility(self):
        statement = self.pay_run.statements.get()
        self.client.force_login(self.emp.user)
        self.assertEqual(self.client.get(f"/payroll/my/{statement.pk}/").status_code, 404)
        self.client.force_login(self.owner)
        self.assertIn(self.client.get(f"/payroll/runs/{self.pay_run.pk}/export.csv").status_code, (302, 400))
        run = submit_for_review(run=self.pay_run, actor=self.owner)
        finalize_payroll_run(run=run, actor=self.owner, review_note="Reference verified")
        self.assertEqual(self.client.get(f"/payroll/runs/{run.pk}/export.csv").status_code, 200)
        self.client.force_login(self.emp.user)
        response = self.client.get(f"/payroll/my/{statement.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "800.00")
        self.client.force_login(self.emp2.user)
        self.assertEqual(self.client.get(f"/payroll/my/{statement.pk}/").status_code, 404)
