from zoneinfo import available_timezones

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.models import User
from organizations.validators import validate_iana_timezone


class EmployerSignupForm(forms.Form):
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "placeholder": "you@company.com"}
        ),
    )
    first_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "given-name", "placeholder": "e.g. Miguel"}
        ),
    )
    last_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "family-name", "placeholder": "e.g. Tan"}
        ),
    )
    organization_name = forms.CharField(
        max_length=120,
        label="Company / workspace name",
        widget=forms.TextInput(
            attrs={"autocomplete": "organization", "placeholder": "e.g. Acme Co."}
        ),
    )
    timezone = forms.ChoiceField(
        choices=[(name, name) for name in sorted(available_timezones())],
        initial="UTC",
        label="Time zone",
        help_text="Used for schedules, attendance times, and reports.",
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        help_text="Use at least 8 characters and avoid common passwords.",
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "At least 8 characters",
            }
        ),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Re-enter your password",
            }
        ),
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


class OrganizationSettingsForm(forms.Form):
    organization_name = forms.CharField(max_length=120, label="Organization name")
    timezone = forms.ChoiceField(
        choices=[(name, name) for name in sorted(available_timezones())],
        label="Organization time zone",
        help_text="Used for schedules, attendance, and timesheets.",
    )

    def __init__(self, *args, organization, timezone_locked, **kwargs):
        self.organization = organization
        self.timezone_locked = timezone_locked
        super().__init__(*args, **kwargs)
        self.fields["organization_name"].initial = organization.name
        self.fields["timezone"].initial = organization.timezone
        if timezone_locked:
            self.fields["timezone"].disabled = True
            self.fields["timezone"].help_text = "Time zone changes are locked after shifts exist to preserve historical records."

    def clean_organization_name(self):
        value = self.cleaned_data["organization_name"].strip()
        if not value:
            raise ValidationError("Enter an organization name.")
        return value

    def clean_timezone(self):
        value = self.cleaned_data["timezone"]
        validate_iana_timezone(value)
        return value


class EmployerProfileSettingsForm(forms.Form):
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name")
    preferred_timezone = forms.ChoiceField(
        choices=[(name, name) for name in sorted(available_timezones())],
        label="Your time zone",
        help_text="Used for your local time display. Schedules stay in your organization's time zone.",
    )

    def __init__(self, *args, user, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].initial = user.first_name
        self.fields["last_name"].initial = user.last_name
        self.fields["preferred_timezone"].initial = (
            user.preferred_timezone or organization.timezone
        )

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

    def clean_preferred_timezone(self):
        value = self.cleaned_data["preferred_timezone"]
        validate_iana_timezone(value)
        return value
