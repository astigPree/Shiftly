from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .models import Employee


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ("employee_code", "job_title", "first_name", "last_name", "email")
        labels = {
            "employee_code": "Employee code",
            "job_title": "Job title (optional)",
            "first_name": "First name",
            "last_name": "Last name",
            "email": "Email address",
        }
        help_texts = {
            "employee_code": "Internal identifier used in schedules and reports.",
            "email": "Used to send the employee their Shiftly account invitation.",
        }
        widgets = {
            "employee_code": forms.TextInput(
                attrs={"autocomplete": "off", "placeholder": "e.g. EMP-001"}
            ),
            "job_title": forms.TextInput(
                attrs={"autocomplete": "organization-title", "placeholder": "e.g. Customer Support"}
            ),
            "first_name": forms.TextInput(
                attrs={"autocomplete": "given-name", "placeholder": "e.g. Alex"}
            ),
            "last_name": forms.TextInput(
                attrs={"autocomplete": "family-name", "placeholder": "e.g. Santos"}
            ),
            "email": forms.EmailInput(
                attrs={"autocomplete": "email", "placeholder": "name@company.com"}
            ),
        }

    def clean_employee_code(self):
        return self.cleaned_data["employee_code"].strip().upper()

    def clean_first_name(self):
        value = self.cleaned_data["first_name"].strip()
        if not value:
            raise ValidationError("Enter the employee's first name.")
        return value

    def clean_last_name(self):
        value = self.cleaned_data["last_name"].strip()
        if not value:
            raise ValidationError("Enter the employee's last name.")
        return value

    def clean_email(self):
        email = self.cleaned_data["email"].strip().casefold()
        employees = Employee.objects.filter(email__iexact=email)
        if self.instance.pk:
            employees = employees.exclude(pk=self.instance.pk)
        if employees.exists():
            raise ValidationError("An employee already uses this email address.")

        linked_user_id = getattr(self.instance, "user_id", None)
        users = get_user_model().objects.filter(email__iexact=email)
        if linked_user_id:
            users = users.exclude(pk=linked_user_id)
        if users.exists():
            raise ValidationError("An account already uses this email address.")
        return email

    def clean_job_title(self):
        return self.cleaned_data["job_title"].strip()


class EmployeeProfileForm(forms.Form):
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name")

    def clean_first_name(self):
        value = self.cleaned_data["first_name"].strip()
        if not value:
            raise ValidationError("Enter your first name.")
        return value

    def clean_last_name(self):
        value = self.cleaned_data["last_name"].strip()
        if not value:
            raise ValidationError("Enter your last name.")
        return value
