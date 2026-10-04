"""Evidence for manually reviewed PH statutory items; no statutory rate engine."""
import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.models import AuditEvent
from audit.services import record_event
from .models import PayrollLine, PayrollRun, PayrollStatement


AGENCIES = (
    ('SSS', 'SSS'), ('PHILHEALTH', 'PhilHealth'),
    ('PAGIBIG', 'Pag-IBIG'), ('WITHHOLDING', 'Withholding tax'),
)
REGISTRATIONS = (
    ('REGISTERED', 'Registration confirmed'),
    ('PENDING', 'Missing number / registration pending'),
    ('NOT_APPLICABLE', 'Registration not applicable (reviewed)'),
)
TREATMENTS = (
    ('LINE', 'Use an itemized line in this run'),
    ('ZERO', 'Reviewed zero for this run'),
    ('OTHER_PERIOD', 'Handled in another cutoff (reference required)'),
    ('NOT_APPLICABLE', 'Not applicable (reason required)'),
)


def statement_fingerprint(statement):
    """Bind the review to the actual run, calculation inputs, and itemized lines."""
    data = {
        'statement': statement.pk, 'employee': statement.employee_id,
        'run': statement.run_id,
        'period': [statement.run.period_start.isoformat(), statement.run.period_end.isoformat()],
        'pay_date': statement.run.pay_date.isoformat(), 'currency': statement.run.currency,
        'frequency': statement.run.pay_frequency, 'run_type': statement.run.run_type,
        'inputs': {k: v for k, v in statement.snapshot.items() if k != 'statutory_reviews'},
        'lines': sorted([
            [line.pk, line.kind, line.code, line.label, str(line.amount), line.source,
             str(line.effective_date), line.note]
            for line in statement.lines.all()
        ]),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode('utf-8')).hexdigest()


def statutory_review_rows(statement):
    fingerprint = statement_fingerprint(statement)
    reviews = statement.snapshot.get('statutory_reviews', {})
    assessments = {}
    try:
        from .models import PayrollStatutoryAssessment
        from .statutory_assessments import assessment_fingerprint
        prefetched = getattr(statement, '_prefetched_objects_cache', {}).get('statutory_assessments')
        assessment_query = prefetched if prefetched is not None else PayrollStatutoryAssessment.objects.filter(statement=statement).select_related(
            'employee_line', 'employer_line', 'reviewed_by'
        )
        assessments = {item.agency: item for item in assessment_query}
    except Exception:
        # Historical installations may be read before the new migration is
        # applied. The legacy snapshot remains the compatibility fallback.
        assessments = {}
    rows = []
    for agency, label in AGENCIES:
        review = reviews.get(agency, {})
        assessment = assessments.get(agency)
        if assessment:
            scoped_fingerprint = assessment_fingerprint(
                statement, agency, employee_line=assessment.employee_line, employer_line=assessment.employer_line
            )
            current = bool(
                assessment.status == 'REVIEWED'
                and assessment.input_fingerprint == scoped_fingerprint
                and assessment.reviewed_by_id
            )
            if current and not review:
                review = {
                    'employee': {'amount': str(assessment.employee_amount), 'treatment': 'LINE' if assessment.employee_line_id else 'ZERO'},
                    'employer': {'amount': str(assessment.employer_amount), 'treatment': 'LINE' if assessment.employer_line_id else 'NOT_APPLICABLE'},
                    'source_reference': assessment.source_reference,
                    'review_note': assessment.review_note,
                    'reviewed_by': assessment.reviewed_by.get_full_name() if assessment.reviewed_by else '',
                    'registration_follow_up': assessment.registration_follow_up,
                }
        else:
            current = bool(review.get('fingerprint') == fingerprint and review.get('reviewed_by_id'))
        rows.append({
            'agency': agency, 'label': label, 'review': review, 'current': current,
            'status': 'Reviewed' if current else ('Review again' if review else 'Not reviewed'),
            'registration_label': dict(REGISTRATIONS).get(review.get('registration'), ''),
            'employee_treatment_label': dict(TREATMENTS).get(review.get('employee', {}).get('treatment'), ''),
            'employer_treatment_label': dict(TREATMENTS).get(review.get('employer', {}).get('treatment'), ''),
        })
    return rows


def assert_statutory_reviewed(statement):
    missing = [row['label'] for row in statutory_review_rows(statement) if not row['current']]
    if missing:
        raise ValidationError(
            f"Complete the statutory review for {statement.employee.full_name}: {', '.join(missing)}. "
            "Missing registration details do not automatically mean zero contributions."
        )


@transaction.atomic
def record_statutory_review(*, statement, actor, agency, registration,
                            employee_treatment, employer_treatment,
                            employee_line=None, employer_line=None,
                            source_reference, review_note, registration_follow_up=''):
    # Local import keeps the service layer's ownership/locking policy in one place.
    from .services import _owner_organization, _record_preview

    organization = _owner_organization(actor, statement.run.organization_id)
    run = PayrollRun.objects.select_for_update().get(pk=statement.run_id, organization=organization)
    if run.status != PayrollRun.Status.DRAFT:
        raise ValidationError('Statutory reviews can only change while the run is a draft.')
    statement = PayrollStatement.objects.select_for_update().select_related('employee', 'run').get(
        pk=statement.pk, run=run)
    if agency not in dict(AGENCIES) or registration not in dict(REGISTRATIONS):
        raise ValidationError('Choose a valid agency and registration status.')
    if not source_reference.strip() or not review_note.strip():
        raise ValidationError('Record the calculation/source reference and the reason for this treatment.')
    if len(source_reference) > 255 or len(review_note) > 500 or len(registration_follow_up) > 500:
        raise ValidationError('Keep the source within 255 characters and each review note within 500 characters.')
    if registration == 'PENDING':
        if not registration_follow_up.strip():
            raise ValidationError('Record the follow-up for the missing registration number.')
        if employee_treatment == 'NOT_APPLICABLE':
            raise ValidationError('Missing registration is not an exemption. Review the amount for this cutoff.')
        if agency != 'WITHHOLDING' and employer_treatment == 'NOT_APPLICABLE':
            raise ValidationError('Missing registration is not an exemption from the employer share.')
    if registration == 'NOT_APPLICABLE' and (
        employee_treatment != 'NOT_APPLICABLE' or employer_treatment != 'NOT_APPLICABLE'
    ):
        raise ValidationError('Confirm registration or mark both shares not applicable with evidence.')
    if agency == 'WITHHOLDING' and employer_treatment != 'NOT_APPLICABLE':
        raise ValidationError('Withholding tax has no employer contribution line. Select Not applicable for the employer share.')

    def share(treatment, selected, kind):
        if treatment not in dict(TREATMENTS):
            raise ValidationError('Choose an explicit treatment for both employee and employer amounts.')
        if treatment != 'LINE':
            if selected is not None:
                raise ValidationError('A zero or not-applicable treatment cannot include a payroll line.')
            return {'treatment': treatment, 'line_id': None, 'amount': '0.00', 'label': ''}
        line = statement.lines.filter(pk=getattr(selected, 'pk', None), kind=kind, source='MANUAL').first()
        if line is None or line.amount <= 0:
            raise ValidationError('Select a positive manual line for this employee and the correct share type.')
        for other_agency, review in statement.snapshot.get('statutory_reviews', {}).items():
            if other_agency != agency and any(
                review.get(side, {}).get('line_id') == line.pk for side in ('employee', 'employer')
            ):
                raise ValidationError('This line is already assigned to another statutory item. Use separate itemized lines.')
        return {'treatment': treatment, 'line_id': line.pk, 'amount': str(line.amount), 'label': line.label}

    employee_share = share(employee_treatment, employee_line, PayrollLine.Kind.DEDUCTION)
    employer_share = share(employer_treatment, employer_line, PayrollLine.Kind.EMPLOYER_CONTRIBUTION)
    review = {
        'registration': registration, 'registration_follow_up': registration_follow_up.strip(),
        'employee': employee_share, 'employer': employer_share,
        'source_reference': source_reference.strip(), 'review_note': review_note.strip(),
        'reviewed_by_id': actor.pk, 'reviewed_by': actor.get_full_name() or actor.email,
        'reviewed_at': timezone.now().isoformat(), 'fingerprint': statement_fingerprint(statement),
    }
    statement.snapshot.setdefault('statutory_reviews', {})[agency] = review
    statement.save(update_fields=['snapshot', 'updated_at'])
    # Keep the first-class bulk workspace in sync with the legacy snapshot
    # record. This is deliberately best-effort for old statements that have not
    # yet been generated into the new queue.
    from .models import PayrollStatutoryAssessment
    from .statutory_assessments import assessment_fingerprint
    assessment, _ = PayrollStatutoryAssessment.objects.get_or_create(
        statement=statement,
        agency=agency,
        defaults={
            'organization': organization,
            'employee_id': statement.employee_id,
            'status': PayrollStatutoryAssessment.Status.REVIEWED,
            'source_type': PayrollStatutoryAssessment.SourceType.MANUAL,
        },
    )
    assessment.organization = organization
    assessment.employee_id = statement.employee_id
    assessment.employee_line = employee_line
    assessment.employer_line = employer_line
    assessment.employee_amount = Decimal(employee_share['amount'])
    assessment.employer_amount = Decimal(employer_share['amount'])
    assessment.source_reference = source_reference.strip()
    assessment.review_note = review_note.strip()
    assessment.registration_follow_up = registration_follow_up.strip()
    assessment.input_fingerprint = assessment_fingerprint(
        statement, agency, employee_line=employee_line, employer_line=employer_line
    )
    assessment.status = PayrollStatutoryAssessment.Status.REVIEWED
    assessment.source_type = (
        PayrollStatutoryAssessment.SourceType.ZERO
        if employee_treatment == 'ZERO' and employer_treatment in {'ZERO', 'NOT_APPLICABLE'}
        else PayrollStatutoryAssessment.SourceType.EXEMPT
        if employee_treatment == 'NOT_APPLICABLE' and employer_treatment == 'NOT_APPLICABLE'
        else PayrollStatutoryAssessment.SourceType.OTHER_PERIOD
        if employee_treatment == 'OTHER_PERIOD' and employer_treatment in {'OTHER_PERIOD', 'NOT_APPLICABLE'}
        else PayrollStatutoryAssessment.SourceType.MANUAL
    )
    assessment.reviewed_by = actor
    assessment.reviewed_at = timezone.now()
    assessment.save()
    _record_preview(run, actor)
    record_event(organization=organization, actor=actor,
        action=AuditEvent.Action.PAYROLL_STATUTORY_REVIEWED,
        target_type='payroll_statement', target_id=statement.pk,
        summary=f'Reviewed {dict(AGENCIES)[agency]} for {statement.employee.employee_code}.',
        metadata={'run': run.reference, 'agency': agency, **review})
    return statement
