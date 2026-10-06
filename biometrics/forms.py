from django import forms

from .models import AttendanceDevice, DeviceIdentityAssignment, OrganizationBiometricSettings
from .services import encrypt_password


class BiometricSettingsForm(forms.ModelForm):
    class Meta:
        model = OrganizationBiometricSettings
        fields = ["enabled", "default_sync_interval_seconds", "early_clock_in_minutes", "post_shift_capture_minutes", "duplicate_window_seconds"]
        widgets = {field: forms.NumberInput(attrs={"min": 0}) for field in fields if field != "enabled"}


class AttendanceDeviceForm(forms.ModelForm):
    communication_password = forms.CharField(
        label="Communication password",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Stored encrypted and never shown again. Leave blank to keep the existing password.",
    )

    class Meta:
        model = AttendanceDevice
        fields = ["name", "model", "host", "port", "timezone", "sync_interval_seconds", "status"]
        widgets = {"sync_interval_seconds": forms.NumberInput(attrs={"min": 30, "max": 86400})}

    def clean_communication_password(self):
        password = self.cleaned_data.get("communication_password", "")
        if password and not password.isdigit():
            raise forms.ValidationError("Use the numeric communication password configured on the terminal.")
        return password

    def save(self, commit=True):
        instance = super().save(commit=False)
        password = self.cleaned_data.get("communication_password", "")
        if password:
            # Encryption can fail when the deployment key or cryptography
            # dependency is unavailable.  Keep that as a typed configuration
            # error so the view can attach it to the form instead of returning
            # a server error.
            instance.communication_password_encrypted = encrypt_password(password)
        if commit:
            instance.save()
        return instance


class DeviceIdentityAssignmentForm(forms.ModelForm):
    class Meta:
        model = DeviceIdentityAssignment
        fields = ["employee", "effective_from", "effective_until"]
        widgets = {
            "effective_from": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "effective_until": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, organization=None, identity=None, **kwargs):
        self.identity = identity
        super().__init__(*args, **kwargs)
        # ModelForm._post_clean() runs the model's clean() method during
        # is_valid().  Bind the identity before that lifecycle step; assigning
        # it only in save() leaves DeviceIdentityAssignment.clean() with an
        # unloaded foreign-key relation and causes RelatedObjectDoesNotExist.
        if identity is not None:
            self.instance.device_identity = identity
        if organization is not None:
            self.fields["employee"].queryset = organization.employees.filter(status="ACTIVE").order_by("last_name", "first_name")

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.device_identity = self.identity
        if commit:
            instance.save()
        return instance
