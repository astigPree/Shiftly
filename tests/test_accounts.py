import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, RequestFactory, Client
from django.utils import timezone

from accounts.models import User
from employees.models import Employee
from employees.services import issue_employee_invitation, accept_employee_invitation
from audit.models import AuditEvent
from .factories import workspace, employee, PASSWORD


class AccountTests(TestCase):
    def test_signup_creates_owner_workspace_and_audit(self):
        response = self.client.post("/signup/", {"email": "New@Example.test", "first_name": "New", "last_name": "Owner",
            "organization_name": "New company", "timezone": "Asia/Manila", "password1": PASSWORD, "password2": PASSWORD})
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="new@example.test")
        self.assertEqual(user.organization.timezone, "Asia/Manila")
        self.assertTrue(AuditEvent.objects.filter(organization=user.organization).exists())

    def test_signup_invalid_password_timezone_duplicate_email(self):
        org, owner = workspace()
        base = {"email": owner.email, "first_name": "A", "last_name": "B", "organization_name": "Test",
                "timezone": "Invalid/Zone", "password1": "123", "password2": "456"}
        response = self.client.post("/signup/", base)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(response.context["form"].errors)

    def test_login_casefold_remember_and_post_logout(self):
        _, owner = workspace()
        self.assertEqual(authenticate(username=owner.email.upper(), password=PASSWORD), owner)
        response = self.client.post("/login/", {"username": owner.email.upper(), "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.assertEqual(self.client.get("/logout/").status_code, 405)
        self.assertEqual(self.client.post("/logout/").status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_reset_email_and_one_time_reset(self):
        _, owner = workspace()
        self.client.post("/password-reset/", {"email": owner.email})
        self.assertEqual(len(mail.outbox), 1)
        path = re.search(r"http://testserver(/reset/\S+)", mail.outbox[0].body).group(1)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        confirm_path = response.url
        response = self.client.post(confirm_path, {"new_password1": PASSWORD + "new", "new_password2": PASSWORD + "new"})
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(authenticate(username=owner.email, password=PASSWORD + "new"))
        self.assertFalse(Client().get(path).context["validlink"])

    def test_employee_creation_invitation_accept_and_resend(self):
        org, owner = workspace()
        self.client.force_login(owner)
        response = self.client.post("/employees/new/", {"employee_code": "001", "first_name": "New", "last_name": "Employee",
            "email": "new-staff@example.test", "job_title": "Staff"})
        self.assertEqual(response.status_code, 302)
        person = org.employees.get()
        old_token = re.search(r"/invitations/([^/]+)/", mail.outbox[-1].body).group(1)
        response = self.client.post(f"/employees/{person.pk}/invitation/")
        self.assertEqual(response.status_code, 302)
        new_token = re.search(r"/invitations/([^/]+)/", mail.outbox[-1].body).group(1)
        with self.assertRaises(ValidationError):
            accept_employee_invitation(old_token, PASSWORD)
        user = accept_employee_invitation(new_token, PASSWORD)
        self.assertEqual(user.role, "EMPLOYEE")
        person.refresh_from_db()
        self.assertEqual(person.user_id, user.pk)
        with self.assertRaises(ValidationError):
            accept_employee_invitation(new_token, PASSWORD)

    def test_expired_invitation_and_email_failure_roll_back(self):
        org, owner = workspace()
        person = employee(org, account=False)
        invitation = issue_employee_invitation(person, owner, RequestFactory().get("/"))
        token = re.search(r"/invitations/([^/]+)/", mail.outbox[-1].body).group(1)
        with patch("employees.services.timezone.now", return_value=invitation.expires_at + timedelta(seconds=1)), self.assertRaises(ValidationError):
            accept_employee_invitation(token, PASSWORD)
        self.client.force_login(owner)
        with patch("employees.services.send_mail", side_effect=OSError("offline")):
            response = self.client.post("/employees/new/", {"employee_code": "002", "first_name": "Other", "last_name": "Employee",
                "email": "failed@example.test", "job_title": "Staff"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Employee.objects.filter(email="failed@example.test").exists())

    def test_deactivate_reactivate_employee_and_block_login(self):
        org, owner = workspace()
        person = employee(org)
        self.client.force_login(owner)
        self.client.post(f"/employees/{person.pk}/status/")
        self.assertIsNone(authenticate(username=person.email, password=PASSWORD))
        person.refresh_from_db()
        self.assertEqual(person.status, "INACTIVE")
        self.client.post(f"/employees/{person.pk}/status/")
        self.assertIsNotNone(authenticate(username=person.email, password=PASSWORD))

    def test_employee_profile_and_employer_settings(self):
        org, owner = workspace()
        person = employee(org)
        self.client.force_login(person.user)
        response = self.client.post("/profile/", {"first_name": "Updated", "last_name": "Employee", "preferred_timezone": "America/Los_Angeles"})
        self.assertEqual(response.status_code, 302)
        person.refresh_from_db()
        person.user.refresh_from_db()
        self.assertEqual(person.first_name, "Updated")
        self.assertEqual(person.user.preferred_timezone, "America/Los_Angeles")
        self.client.force_login(owner)
        response = self.client.post("/settings/", {"settings_section": "organization", "organization_name": "Renamed", "timezone": "UTC"})
        self.assertEqual(response.status_code, 302)
        org.refresh_from_db()
        self.assertEqual(org.name, "Renamed")

    def test_csrf_required_for_signup_and_clock_actions(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/signup/", {}).status_code, 403)
        org, _ = workspace()
        person = employee(org)
        client.force_login(person.user)
        self.assertEqual(client.post("/attendance/shifts/1/clock-in/").status_code, 403)

    def test_audit_is_append_only(self):
        org, owner = workspace()
        from audit.services import record_event
        entry = record_event(organization=org, actor=owner, action="ORGANIZATION_CREATED",
            target_type="organization", target_id=org.pk, summary="Test")
        for action in (lambda: entry.save(), lambda: entry.delete(),
                       lambda: AuditEvent.objects.all().update(summary="Changed"), lambda: AuditEvent.objects.all().delete()):
            with self.assertRaises(ValidationError):
                action()
