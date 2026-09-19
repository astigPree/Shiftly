from zoneinfo import available_timezones

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.models import User
from organizations.validators import validate_iana_timezone


class EmployerSignupForm(forms.Form):
    email = forms.EmailField(max_length=254)
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    organization_name = forms.CharField(max_length=120, label="Company name")
    timezone = forms.ChoiceField(
        choices=[(name, name) for name in sorted(available_timezones())],
        initial="UTC",
        label="Organization time zone",
    )
    password1 = forms.CharField(
        label="Password", strip=False, widget=forms.PasswordInput
    )
    password2 = forms.CharField(
        label="Confirm password", strip=False, widget=forms.PasswordInput
    )

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address already exists.")
        return email

    def clean_organization_name(self):
        value = self.cleaned_data["organization_name"].strip()
        if not value:
            raise ValidationError("Enter your company name.")
        return value

    def clean_timezone(self):
        value = self.cleaned_data["timezone"]
        validate_iana_timezone(value)
        return value

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
        elif password1:
            candidate = User(
                email=cleaned.get("email", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
            )
            try:
                validate_password(password1, user=candidate)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned


class EmployeeInvitationAcceptanceForm(forms.Form):
    password1 = forms.CharField(
        label="Create password", strip=False, widget=forms.PasswordInput
    )
    password2 = forms.CharField(
        label="Confirm password", strip=False, widget=forms.PasswordInput
    )

    def __init__(self, *args, employee, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
        elif password1:
            candidate = User(
                email=self.employee.email,
                first_name=self.employee.first_name,
                last_name=self.employee.last_name,
            )
            try:
                validate_password(password1, user=candidate)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned
