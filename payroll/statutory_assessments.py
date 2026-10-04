"""Run-level statutory assessment generation and bulk review services.

This module intentionally handles evidence and workflow, not Philippine legal
calculation tables. Existing reviewed manual lines can be queued and confirmed
in bulk; rows without a safe source stay in the exception queue.
"""

import hashlib
import json
from collections import Counter
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from audit.models import AuditEvent
from audit.services import record_event
from .models import (
    EmployeeStatutoryCoverage,
    PayrollLine,
    PayrollRun,
    PayrollStatement,
    PayrollStatutoryAssessment,
)
from .statutory import AGENCIES, REGISTRATIONS, TREATMENTS


AGENCY_KEYWORDS = {
    "SSS": ("sss",),
    "PHILHEALTH": ("philhealth", "phil-health"),
    "PAGIBIG": ("pag-ibig", "pagibig", "pag ibig"),
    "WITHHOLDING": ("withholding", "bir", "income tax", "tax"),
}


def _money(value):
    return Decimal(value or "0.00").quantize(Decimal("0.01"))


def _line_matches_agency(line, agency):
    haystack = " ".join(
        str(value or "") for value in (line.code, line.label, line.note)
    ).casefold()
    return any(keyword in haystack for keyword in AGENCY_KEYWORDS[agency])


def _current_coverage(statement, agency):
    coverage_agency = "BIR" if agency == "WITHHOLDING" else agency
    return (
        EmployeeStatutoryCoverage.objects.filter(
            organization_id=statement.run.organization_id,
            employee_id=statement.employee_id,
            agency=coverage_agency,
            effective_from__lte=statement.run.period_end,
        )
        .filter(
            models_q_effective_until(statement.run.period_end)
        )
        .order_by("-effective_from", "-pk")
        .first()
    )


def models_q_effective_until(cutoff):
    # Kept as a function to make the date policy explicit at every call site.
    from django.db.models import Q

    return Q(effective_until__isnull=True) | Q(effective_until__gte=cutoff)


def assessment_fingerprint(statement, agency, *, employee_line=None, employer_line=None):
    """Fingerprint only inputs relevant to this agency.

    An unrelated bonus or reimbursement must not invalidate every statutory
    review in the run.
    """
    lines = list(statement.lines.all())
    relevant = [
        line for line in lines
        if _line_matches_agency(line, agency)
        or line.pk in {getattr(employee_line, "pk", None), getattr(employer_line, "pk", None)}
    ]
    data = {
        "statement": statement.pk,
        "employee": statement.employee_id,
        "run": statement.run_id,
        "period": [statement.run.period_start.isoformat(), statement.run.period_end.isoformat()],
        "pay_date": statement.run.pay_date.isoformat(),
        "currency": statement.run.currency,
        "frequency": statement.run.pay_frequency,
        "agency": agency,
        "inputs": {
            key: value for key, value in (statement.snapshot or {}).items()
            if key not in {"statutory_reviews", "components"}
        },
        "lines": sorted([
            [line.pk, line.kind, line.code, line.label, str(line.amount), line.source,
             str(line.effective_date), line.note]
            for line in relevant
        ]),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def _matching_lines(statement, agency):
    lines = [line for line in statement.lines.all() if line.source == "MANUAL"]
    deductions = [line for line in lines if line.kind == PayrollLine.Kind.DEDUCTION and _line_matches_agency(line, agency)]
    employer = [line for line in lines if line.kind == PayrollLine.Kind.EMPLOYER_CONTRIBUTION and _line_matches_agency(line, agency)]
    return deductions, employer


def _legacy_review(statement, agency):
    return (statement.snapshot or {}).get("statutory_reviews", {}).get(agency) or {}


def _reviewed_from_legacy(statement, agency, fingerprint):
    review = _legacy_review(statement, agency)
    # Legacy reviews use the original whole-statement fingerprint. They are
    # accepted once during migration, then rewritten with the scoped fingerprint.
    from .statutory import statement_fingerprint
    if not review or review.get("fingerprint") not in {fingerprint, statement_fingerprint(statement)} or not review.get("reviewed_by_id") or not review.get("reviewed_at"):
        return False
    employee = review.get("employee") or {}
    employer = review.get("employer") or {}
    return bool(employee.get("treatment") or employer.get("treatment"))


def _source_from_review(review):
    treatments = {
        ("ZERO", "ZERO"): PayrollStatutoryAssessment.SourceType.ZERO,
        ("NOT_APPLICABLE", "NOT_APPLICABLE"): PayrollStatutoryAssessment.SourceType.EXEMPT,
        ("OTHER_PERIOD", "OTHER_PERIOD"): PayrollStatutoryAssessment.SourceType.OTHER_PERIOD,
    }
    key = ((review.get("employee") or {}).get("treatment"), (review.get("employer") or {}).get("treatment"))
    return treatments.get(key, PayrollStatutoryAssessment.SourceType.MANUAL)


@transaction.atomic
def generate_statutory_assessments(*, run, actor, selected_agencies=None):
    """Create or refresh one assessment per statement and agency, idempotently."""
    from .services import _owner_organization

    organization = _owner_organization(actor, run.organization_id)
    locked_run = PayrollRun.objects.select_for_update().get(pk=run.pk, organization=organization)
    if locked_run.status != PayrollRun.Status.DRAFT:
        raise ValidationError("Statutory assessments can only be generated for a draft payroll run.")
    agencies = [code for code, _ in AGENCIES if not selected_agencies or code in selected_agencies]
    statements = list(
        PayrollStatement.objects.filter(run=locked_run)
        .select_related("employee", "run")
        .prefetch_related("lines")
        .order_by("employee__last_name", "employee__first_name", "pk")
    )
    existing = {
        (item.statement_id, item.agency): item
        for item in PayrollStatutoryAssessment.objects.filter(statement__run=locked_run)
    }
    creates, updates = [], []
    counts = Counter()
    for statement in statements:
        for agency in agencies:
            deductions, employer_lines = _matching_lines(statement, agency)
            employee_line = deductions[0] if len(deductions) == 1 else None
            employer_line = employer_lines[0] if len(employer_lines) == 1 else None
            ambiguous = len(deductions) > 1 or len(employer_lines) > 1
            if agency == "WITHHOLDING":
                employer_line = None
                ambiguous = len(deductions) > 1
            fingerprint = assessment_fingerprint(
                statement, agency, employee_line=employee_line, employer_line=employer_line
            )
            key = (statement.pk, agency)
            assessment = existing.get(key)
            old_reviewed_current = bool(
                assessment and assessment.status == PayrollStatutoryAssessment.Status.REVIEWED
                and assessment.input_fingerprint == fingerprint
            )
            legacy_current = _reviewed_from_legacy(statement, agency, fingerprint)
            review = _legacy_review(statement, agency)
            if old_reviewed_current or legacy_current:
                status = PayrollStatutoryAssessment.Status.REVIEWED
                source_type = _source_from_review(review) if legacy_current else (assessment.source_type if assessment else PayrollStatutoryAssessment.SourceType.MANUAL)
                counts["reviewed"] += 1
            elif ambiguous:
                status = PayrollStatutoryAssessment.Status.NEEDS_REVIEW
                source_type = PayrollStatutoryAssessment.SourceType.MANUAL
                counts["needs_review"] += 1
            elif employee_line or employer_line:
                status = PayrollStatutoryAssessment.Status.READY
                source_type = PayrollStatutoryAssessment.SourceType.MANUAL
                counts["ready"] += 1
            else:
                status = PayrollStatutoryAssessment.Status.NEEDS_REVIEW
                source_type = PayrollStatutoryAssessment.SourceType.MANUAL
                counts["needs_review"] += 1

            values = {
                "organization_id": locked_run.organization_id,
                "employee_id": statement.employee_id,
                "status": status,
                "source_type": source_type,
                "employee_line_id": getattr(employee_line, "pk", None),
                "employer_line_id": getattr(employer_line, "pk", None),
                "employee_amount": _money(employee_line.amount if employee_line else (review.get("employee", {}) or {}).get("amount", "0.00") if legacy_current else "0.00"),
                "employer_amount": _money(employer_line.amount if employer_line else (review.get("employer", {}) or {}).get("amount", "0.00") if legacy_current else "0.00"),
                "source_reference": (review.get("source_reference") or "").strip() if legacy_current else "",
                "review_note": (review.get("review_note") or "").strip() if legacy_current else "",
                "registration_follow_up": (review.get("registration_follow_up") or "").strip() if legacy_current else "",
                "input_fingerprint": fingerprint,
                "reviewed_by_id": (
                    review.get("reviewed_by_id") if legacy_current else
                    (assessment.reviewed_by_id if old_reviewed_current and assessment else None)
                ),
                "reviewed_at": (
                    parse_datetime(review.get("reviewed_at")) if legacy_current and review.get("reviewed_at") else
                    (assessment.reviewed_at if old_reviewed_current and assessment else None)
                ),
                "calculation_snapshot": {
                    "agency": agency,
                    "source": "existing_manual_lines",
                    "line_count": len(deductions) + len(employer_lines),
                    "run_revision": locked_run.review_revision,
                },
            }
            if assessment is None:
                assessment = PayrollStatutoryAssessment(
                    statement=statement, agency=agency, **values
                )
                creates.append(assessment)
            else:
                if assessment.status == PayrollStatutoryAssessment.Status.REVIEWED and not old_reviewed_current and not legacy_current:
                    values["status"] = PayrollStatutoryAssessment.Status.SUPERSEDED
                    counts["superseded"] += 1
                for field, value in values.items():
                    setattr(assessment, field, value)
                updates.append(assessment)
    if creates:
        PayrollStatutoryAssessment.objects.bulk_create(creates, batch_size=500)
    if updates:
        PayrollStatutoryAssessment.objects.bulk_update(
            updates,
            [
                "organization", "employee", "status", "source_type", "employee_line", "employer_line",
                "employee_amount", "employer_amount", "source_reference", "review_note",
                "registration_follow_up", "input_fingerprint", "reviewed_by", "reviewed_at", "calculation_snapshot", "updated_at",
            ],
            batch_size=500,
        )
    locked_run.review_revision += 1
    locked_run.save(update_fields=["review_revision", "updated_at"])
    record_event(
        organization=organization,
        actor=actor,
        action=AuditEvent.Action.PAYROLL_STAT_ASSESSMENTS_GEN,
        target_type="payroll_run",
        target_id=locked_run.pk,
        summary=f"Generated statutory assessment queue for {locked_run.reference}.",
        metadata={"run": locked_run.reference, "assessment_count": len(statements) * len(agencies), "counts": dict(counts), "agencies": agencies},
    )
    return {"run": locked_run, "assessment_count": len(statements) * len(agencies), "counts": dict(counts)}


def _apply_snapshot_review(assessment, *, actor, registration, treatment, source_reference, review_note, registration_follow_up):
    statement = assessment.statement
    snapshot = statement.snapshot or {}
    reviews = snapshot.setdefault("statutory_reviews", {})
    employee_line = assessment.employee_line
    employer_line = assessment.employer_line
    employee_share = {
        "treatment": treatment,
        "line_id": employee_line.pk if treatment == "LINE" and employee_line else None,
        "amount": str(assessment.employee_amount if treatment == "LINE" else Decimal("0.00")),
        "label": employee_line.label if treatment == "LINE" and employee_line else "",
    }
    employer_treatment = "NOT_APPLICABLE" if assessment.agency == "WITHHOLDING" else treatment
    employer_share = {
        "treatment": employer_treatment,
        "line_id": employer_line.pk if employer_treatment == "LINE" and employer_line else None,
        "amount": str(assessment.employer_amount if employer_treatment == "LINE" and employer_line else Decimal("0.00")),
        "label": employer_line.label if employer_treatment == "LINE" and employer_line else "",
    }
    reviews[assessment.agency] = {
        "registration": registration,
        "registration_follow_up": registration_follow_up.strip(),
        "employee": employee_share,
        "employer": employer_share,
        "source_reference": source_reference.strip(),
        "review_note": review_note.strip(),
        "reviewed_by_id": actor.pk,
        "reviewed_by": actor.get_full_name() or actor.email,
        "reviewed_at": timezone.now().isoformat(),
        "fingerprint": assessment.input_fingerprint,
    }
    statement.snapshot = snapshot
    statement.save(update_fields=["snapshot", "updated_at"])


@transaction.atomic
def bulk_review_statutory_assessments(*, run, actor, assessment_ids, registration,
                                      treatment, source_reference, review_note,
                                      registration_follow_up="", expected_revision=None):
    """Confirm a selected ready/explicit-zero population in one audited action."""
    from .services import _owner_organization, _record_preview

    organization = _owner_organization(actor, run.organization_id)
    locked_run = PayrollRun.objects.select_for_update().get(pk=run.pk, organization=organization)
    if locked_run.status != PayrollRun.Status.DRAFT:
        raise ValidationError("Statutory reviews can only change while the payroll run is a draft.")
    if expected_revision is not None and str(expected_revision) != str(locked_run.review_revision):
        raise ValidationError("This payroll changed after you opened the review. Refresh the assessment preview before confirming.")
    if not assessment_ids:
        raise ValidationError("Select at least one assessment to review.")
    try:
        normalized_ids = {int(value) for value in assessment_ids}
    except (TypeError, ValueError):
        raise ValidationError("The selected assessment list is invalid. Refresh the queue and try again.")
    if not source_reference.strip() or not review_note.strip():
        raise ValidationError("Record one calculation/source reference and one review note for this batch.")
    if registration == "PENDING" and not registration_follow_up.strip():
        raise ValidationError("Record the follow-up for the missing registration number.")
    if registration not in dict(REGISTRATIONS) or treatment not in dict(TREATMENTS):
        raise ValidationError("Choose a valid registration and treatment.")
    assessments = list(
        PayrollStatutoryAssessment.objects.select_for_update()
        .select_related("statement", "statement__employee", "employee_line", "employer_line")
        .prefetch_related("statement__lines")
        .filter(statement__run=locked_run, pk__in=normalized_ids)
    )
    if len(assessments) != len(normalized_ids):
        raise ValidationError("One or more selected assessments no longer belong to this payroll run.")
    if any(item.status in {PayrollStatutoryAssessment.Status.REVIEWED, PayrollStatutoryAssessment.Status.SUPERSEDED} for item in assessments):
        raise ValidationError("Select only ready or unresolved assessments. Refresh the queue and try again.")
    if treatment == "LINE":
        invalid = [
            item for item in assessments
            if item.status != PayrollStatutoryAssessment.Status.READY
            or not item.employee_line
            or (item.agency != "WITHHOLDING" and not item.employer_line)
        ]
        if invalid:
            raise ValidationError("Only ready assessments with a reviewed employee line can be bulk-confirmed as line amounts.")
    elif any(item.employee_line_id or item.employer_line_id for item in assessments):
        raise ValidationError("Selected assessments already have manual lines. Review the line treatment individually instead of recording a zero or exemption.")
    if registration == "PENDING" and treatment == "NOT_APPLICABLE":
        raise ValidationError("Missing registration is not an exemption. Use a reviewed amount or zero with follow-up evidence.")
    now = timezone.now()
    for assessment in assessments:
        current_fingerprint = assessment_fingerprint(
            assessment.statement,
            assessment.agency,
            employee_line=assessment.employee_line,
            employer_line=assessment.employer_line,
        )
        if current_fingerprint != assessment.input_fingerprint:
            assessment.status = PayrollStatutoryAssessment.Status.SUPERSEDED
            assessment.save(update_fields=["status", "updated_at"])
            raise ValidationError("One selected assessment is stale. Refresh the assessment preview before confirming.")
        if treatment != "LINE":
            assessment.employee_amount = Decimal("0.00")
            assessment.employer_amount = Decimal("0.00")
            assessment.employee_line = None
            assessment.employer_line = None
            assessment.source_type = {
                "ZERO": PayrollStatutoryAssessment.SourceType.ZERO,
                "NOT_APPLICABLE": PayrollStatutoryAssessment.SourceType.EXEMPT,
                "OTHER_PERIOD": PayrollStatutoryAssessment.SourceType.OTHER_PERIOD,
            }[treatment]
        else:
            assessment.source_type = PayrollStatutoryAssessment.SourceType.MANUAL
        assessment.status = PayrollStatutoryAssessment.Status.REVIEWED
        assessment.source_reference = source_reference.strip()[:255]
        assessment.review_note = review_note.strip()[:500]
        assessment.registration_follow_up = registration_follow_up.strip()[:500]
        assessment.reviewed_by = actor
        assessment.reviewed_at = now
        assessment.save(update_fields=[
            "status", "source_type", "employee_line", "employer_line", "employee_amount", "employer_amount",
            "source_reference", "review_note", "registration_follow_up", "reviewed_by", "reviewed_at", "updated_at",
        ])
        _apply_snapshot_review(
            assessment, actor=actor, registration=registration, treatment=treatment,
            source_reference=source_reference, review_note=review_note,
            registration_follow_up=registration_follow_up,
        )
    _record_preview(locked_run, actor)
    locked_run.review_revision += 1
    locked_run.save(update_fields=["review_revision", "updated_at"])
    by_agency = Counter(item.agency for item in assessments)
    record_event(
        organization=organization,
        actor=actor,
        action=AuditEvent.Action.PAYROLL_STATUTORY_BULK_REVIEWED,
        target_type="payroll_run",
        target_id=locked_run.pk,
        summary=f"Bulk-reviewed {len(assessments)} statutory assessments for {locked_run.reference}.",
        metadata={"run": locked_run.reference, "assessment_ids": [item.pk for item in assessments], "agencies": dict(by_agency), "treatment": treatment},
    )
    return {"run": locked_run, "reviewed_count": len(assessments), "agencies": dict(by_agency)}

