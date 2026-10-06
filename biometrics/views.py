from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from accounts.permissions import employer_required, organization_for_user
from audit.models import AuditEvent
from audit.services import record_event
from employees.models import Employee

from .forms import AttendanceDeviceForm, BiometricSettingsForm, DeviceIdentityAssignmentForm
from .models import AttendanceDevice, BiometricAttendanceProjection, BiometricPunch, BiometricPunchIssue, DeviceIdentity, DeviceSyncRun, OrganizationBiometricSettings
from .services import (
    assign_identity,
    materialize_biometric_projection,
    reconcile_biometric_projection,
    refresh_due_biometric_projections,
    safe_operation_error,
    sync_device_punches,
    sync_device_users,
    test_device_connection,
)


def _safe_error(error, fallback="Shiftly could not complete this biometric operation."):
    safe = safe_operation_error(error, fallback=fallback)
    if safe.operator_action:
        return f"{safe.operator_message} {safe.operator_action}"
    return safe.operator_message


def _add_form_error(form, error):
    if isinstance(error, ValidationError):
        if hasattr(error, "message_dict"):
            for field, field_messages in error.message_dict.items():
                for message in field_messages:
                    form.add_error(None if field == "__all__" else field, message)
        else:
            for message in error.messages:
                form.add_error(None, message)
        return
    form.add_error(None, _safe_error(error))


@employer_required
def device_list(request):
    organization = organization_for_user(request.user)
    settings_obj, _ = OrganizationBiometricSettings.objects.get_or_create(organization=organization)
    devices = list(AttendanceDevice.objects.filter(organization=organization).prefetch_related("identities"))
    settings_modal_open = False
    add_terminal_modal_open = False
    if request.method == "POST":
        settings_form = BiometricSettingsForm(request.POST, instance=settings_obj)
        device_form = AttendanceDeviceForm(request.POST)
        if "save-settings" in request.POST:
            settings_modal_open = True
            if settings_form.is_valid():
                settings_form.save()
                messages.success(request, "Biometric sync settings saved.")
                return redirect("biometrics:devices")
        if "add-device" in request.POST:
            add_terminal_modal_open = True
            try:
                if device_form.is_valid():
                    device = device_form.save(commit=False)
                    device.organization = organization
                    device.full_clean()
                    device.save()
                    record_event(
                        organization=organization,
                        actor=request.user,
                        action=AuditEvent.Action.BIOMETRIC_DEVICE_ADDED,
                        target_type="biometric_device",
                        target_id=device.pk,
                        summary=f"Added biometric device {device.name}.",
                        metadata={"model": device.model, "host": device.host, "port": device.port},
                    )
                    messages.success(request, f"{device.name} was added. Test the connection before assigning employees.")
                    return redirect("biometrics:devices")
            except Exception as error:
                _add_form_error(device_form, error)
    else:
        settings_form = BiometricSettingsForm(instance=settings_obj)
        device_form = AttendanceDeviceForm()
    now = timezone.now()
    identities = list(
        DeviceIdentity.objects.filter(device__organization=organization)
        .prefetch_related("assignments")
    )
    mapped_ids = 0
    mapped_employee_ids = set()
    for identity in identities:
        assignment = next(
            (
                item
                for item in identity.assignments.all()
                if item.effective_from <= now and (item.effective_until is None or item.effective_until > now)
            ),
            None,
        )
        if assignment:
            mapped_ids += 1
            mapped_employee_ids.add(assignment.employee_id)
    open_issue_count = BiometricPunchIssue.objects.filter(
        organization=organization, status=BiometricPunchIssue.Status.OPEN
    ).count()
    last_successful_sync = (
        DeviceSyncRun.objects.filter(device__organization=organization, status=DeviceSyncRun.Status.SUCCEEDED)
        .select_related("device")
        .first()
    )
    return render(request, "biometrics/devices.html", {
        "organization": organization,
        "settings_form": settings_form,
        "device_form": device_form,
        "devices": devices,
        "recent_runs": DeviceSyncRun.objects.filter(device__organization=organization).select_related("device")[:10],
        "open_issue_count": open_issue_count,
        "mapped_employee_count": len(mapped_employee_ids),
        "mapped_id_count": mapped_ids,
        "unmapped_id_count": max(0, len(identities) - mapped_ids),
        "healthy_device_count": sum(1 for device in devices if device.health == AttendanceDevice.Health.HEALTHY),
        "last_successful_sync": last_successful_sync,
        "settings_modal_open": settings_modal_open,
        "add_terminal_modal_open": add_terminal_modal_open,
        "setup_steps": [
            {"label": "Enable biometric attendance", "detail": "Turn on sync settings", "done": settings_obj.enabled},
            {"label": "Add a terminal", "detail": "Connect your office device", "done": bool(devices)},
            {"label": "Test the connection", "detail": "Verify communication", "done": any(device.health == AttendanceDevice.Health.HEALTHY for device in devices)},
            {"label": "Map terminal users", "detail": "Assign IDs to employees", "done": bool(identities) and mapped_ids == len(identities)},
            {"label": "Review scans and issues", "detail": "Check imported evidence", "done": bool(devices) and open_issue_count == 0},
        ],
    })


@employer_required
def issue_list(request):
    organization = organization_for_user(request.user)
    issues = BiometricPunchIssue.objects.filter(organization=organization).select_related("device", "employee", "projection").order_by("status", "-created_at")
    today = timezone.localdate()
    urgent_codes = {BiometricPunchIssue.Code.UNMAPPED_ID, BiometricPunchIssue.Code.OFFLINE, BiometricPunchIssue.Code.SOURCE_CONFLICT}
    return render(request, "biometrics/issues.html", {
        "organization": organization,
        "issues": issues,
        "open_issue_count": issues.filter(status=BiometricPunchIssue.Status.OPEN).count(),
        "urgent_issue_count": issues.filter(status=BiometricPunchIssue.Status.OPEN, code__in=urgent_codes).count(),
        "resolved_today_count": issues.filter(status=BiometricPunchIssue.Status.RESOLVED, resolved_at__date=today).count(),
        "unmapped_id_count": issues.filter(status=BiometricPunchIssue.Status.OPEN, code=BiometricPunchIssue.Code.UNMAPPED_ID).count(),
    })


@employer_required
@require_POST
def resolve_issue(request, issue_pk):
    organization = organization_for_user(request.user)
    issue = get_object_or_404(BiometricPunchIssue, pk=issue_pk, organization=organization)
    issue.resolve(request.user)
    messages.success(request, "Biometric issue marked resolved. Review the raw timeline before applying attendance.")
    return redirect("biometrics:issues")


@employer_required
def edit_device(request, device_pk):
    organization = organization_for_user(request.user)
    device = get_object_or_404(AttendanceDevice, pk=device_pk, organization=organization)
    if request.method == "POST":
        form = AttendanceDeviceForm(request.POST, instance=device)
        try:
            if form.is_valid():
                form.save()
                record_event(
                    organization=organization,
                    actor=request.user,
                    action=AuditEvent.Action.BIOMETRIC_DEVICE_UPDATED,
                    target_type="biometric_device",
                    target_id=device.pk,
                    summary=f"Updated biometric device {device.name}.",
                    metadata={"status": device.status},
                )
                messages.success(request, f"{device.name} was updated.")
                return redirect("biometrics:devices")
        except Exception as error:
            _add_form_error(form, error)
    else:
        form = AttendanceDeviceForm(instance=device)
    return render(request, "biometrics/device_edit.html", {"organization": organization, "device": device, "form": form})


@employer_required
@require_POST
def test_device(request, device_pk):
    organization = organization_for_user(request.user)
    device = get_object_or_404(AttendanceDevice, pk=device_pk, organization=organization)
    try:
        result = test_device_connection(device, actor=request.user)
        if result.get("status") == DeviceSyncRun.Status.SKIPPED:
            messages.warning(request, f"A sync is already running for {device.name}. Refresh the activity history.")
        else:
            messages.success(request, f"{device.name} is reachable. Connection verified.")
    except Exception as error:
        messages.error(request, _safe_error(error, f"{device.name} could not be tested."))
    return redirect("biometrics:devices")


@employer_required
@require_POST
def sync_users(request, device_pk):
    organization = organization_for_user(request.user)
    device = get_object_or_404(AttendanceDevice, pk=device_pk, organization=organization)
    try:
        result = sync_device_users(device, actor=request.user)
        if result.get("status") == DeviceSyncRun.Status.SKIPPED:
            messages.warning(request, f"A sync is already running for {device.name}. Refresh the activity history.")
        elif result.get("status") == DeviceSyncRun.Status.PARTIAL:
            messages.warning(request, f"User sync partially completed: {result.get('users_seen', 0)} users read.")
        else:
            messages.success(request, f"User sync complete: {result.get('users_seen', 0)} terminal users read.")
    except Exception as error:
        messages.error(request, _safe_error(error, f"User sync failed for {device.name}."))
    return redirect("biometrics:devices")


@employer_required
@require_POST
def sync_punches(request, device_pk):
    organization = organization_for_user(request.user)
    device = get_object_or_404(AttendanceDevice, pk=device_pk, organization=organization)
    try:
        result = sync_device_punches(device, actor=request.user)
        if result.get("status") == DeviceSyncRun.Status.SKIPPED:
            messages.warning(request, f"A sync is already running for {device.name}. Refresh the activity history.")
        elif result.get("status") == DeviceSyncRun.Status.PARTIAL:
            messages.warning(request, f"Punch sync partially completed: {result.get('punches_created', 0)} scans imported.")
        else:
            messages.success(request, f"Punch sync complete: {result.get('punches_created', 0)} new scans imported.")
    except Exception as error:
        messages.error(request, _safe_error(error, f"Punch sync failed for {device.name}."))
    return redirect("biometrics:devices")


@employer_required
def identity_list(request, device_pk):
    organization = organization_for_user(request.user)
    device = get_object_or_404(AttendanceDevice, pk=device_pk, organization=organization)
    identities = list(device.identities.prefetch_related("assignments__employee"))
    if request.method == "POST":
        identity = DeviceIdentity.objects.filter(pk=request.POST.get("identity"), device=device).first()
        form = DeviceIdentityAssignmentForm(request.POST, organization=organization, identity=identity)
        if identity is not None and form.is_valid():
            try:
                assign_identity(
                    identity=identity,
                    employee=form.cleaned_data["employee"],
                    effective_from=form.cleaned_data["effective_from"],
                    effective_until=form.cleaned_data.get("effective_until"),
                    actor=request.user,
                )
                record_event(
                    organization=organization,
                    actor=request.user,
                    action=AuditEvent.Action.BIOMETRIC_IDENTITY_ASSIGNED,
                    target_type="biometric_identity",
                    target_id=identity.pk,
                    summary=f"Mapped terminal ID {identity.terminal_user_id} to {form.cleaned_data['employee'].employee_code}.",
                    metadata={"effective_from": form.cleaned_data["effective_from"].isoformat()},
                )
                messages.success(request, f"Terminal ID {identity.terminal_user_id} is now mapped to {form.cleaned_data['employee'].full_name}.")
                return redirect("biometrics:identities", device_pk=device.pk)
            except Exception as error:
                _add_form_error(form, error)
        elif identity is None:
            form.is_valid()
            form.add_error(None, "This terminal user is no longer available. Refresh the page and select it again.")
    else:
        form = DeviceIdentityAssignmentForm(organization=organization)
    mapping_identity_id = request.POST.get("identity", "") if request.method == "POST" else ""
    mapping_employee_id = request.POST.get("employee", "") if request.method == "POST" else ""
    mapping_effective_from = request.POST.get("effective_from", "") if request.method == "POST" else ""
    mapping_effective_until = request.POST.get("effective_until", "") if request.method == "POST" else ""
    employees = organization.employees.filter(status=Employee.Status.ACTIVE).order_by("last_name", "first_name")
    now = timezone.now()
    identity_rows = []
    for identity in identities:
        current = next(
            (
                item
                for item in identity.assignments.all()
                if item.effective_from <= now and (item.effective_until is None or item.effective_until > now)
            ),
            None,
        )
        upcoming = next((item for item in identity.assignments.all() if item.effective_from > now), None)
        identity_rows.append({"identity": identity, "current": current, "upcoming": upcoming})
    expiring_cutoff = now + timedelta(days=30)
    mapped_ids = sum(1 for row in identity_rows if row["current"])
    expiring_mappings = sum(
        1 for row in identity_rows
        if row["current"] and row["current"].effective_until and row["current"].effective_until <= expiring_cutoff
    )
    backfilled_scans = BiometricPunch.objects.filter(device=device, identity_assignment__isnull=False).count()
    return render(request, "biometrics/identities.html", {
        "organization": organization,
        "device": device,
        "identities": identities,
        "identity_rows": identity_rows,
        "employees": employees,
        "form": form,
        "mapped_id_count": mapped_ids,
        "unmapped_id_count": max(0, len(identity_rows) - mapped_ids),
        "expiring_mapping_count": expiring_mappings,
        "backfilled_scan_count": backfilled_scans,
        "mapping_identity_id": mapping_identity_id,
        "mapping_employee_id": mapping_employee_id,
        "mapping_effective_from": mapping_effective_from,
        "mapping_effective_until": mapping_effective_until,
    })


@employer_required
def punch_list(request, device_pk):
    organization = organization_for_user(request.user)
    device = get_object_or_404(AttendanceDevice, pk=device_pk, organization=organization)
    punch_qs = BiometricPunch.objects.filter(device=device).select_related("identity_assignment__employee", "projection")
    punches = punch_qs[:250]
    return render(request, "biometrics/punches.html", {
        "organization": organization,
        "device": device,
        "punches": punches,
        "punch_count": punch_qs.count(),
        "mapped_punch_count": punch_qs.filter(identity_assignment__isnull=False).count(),
        "unmapped_punch_count": punch_qs.filter(identity_assignment__isnull=True).count(),
        "review_punch_count": punch_qs.filter(projection__status__in=[BiometricAttendanceProjection.Status.NEEDS_REVIEW, BiometricAttendanceProjection.Status.CONFLICT]).count(),
    })


@employer_required
def projection_detail(request, projection_pk):
    organization = organization_for_user(request.user)
    projection = get_object_or_404(
        BiometricAttendanceProjection.objects.select_related(
            "shift", "employee", "shift__organization", "materialized_session"
        ).prefetch_related("punches", "issues"),
        pk=projection_pk,
        shift__organization=organization,
    )
    return render(request, "biometrics/projection_detail.html", {
        "organization": organization,
        "projection": projection,
        "shift": projection.shift,
        "punches": projection.punches.all(),
        "issues": projection.issues.filter(status=BiometricPunchIssue.Status.OPEN),
        "can_apply": projection.status == BiometricAttendanceProjection.Status.READY,
    })


@employer_required
@require_POST
def reprocess_projection(request, projection_pk):
    organization = organization_for_user(request.user)
    projection = get_object_or_404(
        BiometricAttendanceProjection.objects.select_related("shift"),
        pk=projection_pk,
        shift__organization=organization,
    )
    try:
        projection = reconcile_biometric_projection(projection.shift)
        refresh_due_biometric_projections()
        messages.success(request, f"Biometric evidence refreshed for {projection.employee.full_name}.")
    except Exception as error:
        messages.error(request, _safe_error(error, "The biometric projection could not be refreshed."))
    return redirect("biometrics:projection_detail", projection_pk=projection_pk)


@employer_required
@require_POST
def apply_projection(request, projection_pk):
    organization = organization_for_user(request.user)
    projection = get_object_or_404(BiometricAttendanceProjection, pk=projection_pk, shift__organization=organization)
    try:
        materialize_biometric_projection(projection, actor=request.user)
        messages.success(request, "Reviewed biometric scans were applied to attendance and a timesheet was generated.")
    except Exception as error:
        messages.error(request, _safe_error(error, "The reviewed biometric scans could not be applied."))
    return redirect("attendance:list")
