# Payroll bulk statutory workflow implementation plan

**Prepared:** 2026-10-04  
**Status:** Phase 0 and Phase 1 implemented in the draft workflow (2026-10-04); automatic legal calculations and import remain later phases  
**Primary problem:** Manual payroll lines and four one-by-one statutory reviews per employee do not scale beyond a very small payroll.  
**Intended reader:** A developer or coding agent implementing and verifying one phase at a time.

## Implemented in this slice

Phase 0 and Phase 1 are now wired into the draft payroll workflow:

- `PayrollStatutoryAssessment` stores one durable assessment per statement and agency, with a scoped input fingerprint, reviewer evidence, source type, and draft-only mutation rules.
- **Generate assessments** creates an idempotent queue from existing reviewed manual statutory lines. Rows without an unambiguous line remain **Needs attention**; the workflow never guesses a legal amount.
- The run-level workspace is paginated and filterable by employee, agency, status, and source. It supports selecting the visible page or all rows matching the active filters.
- A bulk review modal applies one explicit treatment, source reference, and review note to the selected population. It supports reviewed line amounts, zero, other cutoff, and not-applicable decisions with server-side validation.
- Exception rows open a dedicated individual review page. The existing manual adjustment editor remains available for bonuses, reimbursements, one-time deductions, and reviewed overrides.
- Draft calculation changes increment a revision and stale bulk submissions are rejected. Finalized runs remain immutable. Generation and bulk review record audit events.

Automatic SSS, PhilHealth, Pag-IBIG, and BIR calculations, legal rule-table import, and bulk employee coverage setup remain later phases because they require approved adviser-reviewed tables and cutoff policies.

## 1. Problem to solve

The current draft payroll workflow requires an employer to:

1. Add each SSS, PhilHealth, Pag-IBIG, and withholding amount as a separate manual payroll line.
2. Open every employee's statutory section.
3. Save one statutory review per agency.
4. Repeat the same source, registration status, and review reason for every employee.

For 200 employees, the statutory section alone can require up to 800 review submissions. Manual employee and employer contribution lines can add more than 1,000 additional form submissions. This is too slow and creates avoidable selection, labeling, amount, and duplication errors.

The detailed employee form is still valuable for exceptions. It should not be the primary path for a normal payroll run.

## 2. Target outcome

Shiftly should generate or import proposed statutory amounts for the complete payroll scope, group employees by readiness, and let an authorized employer review the normal population in one controlled action.

The target workflow is:

```text
Employee statutory setup
        +
Approved effective-dated statutory rules or reviewed import
        ↓
Generate proposed assessments for the payroll run
        ↓
Ready population ────────────── Exceptions
        ↓                           ↓
Bulk review and confirm        Resolve individually
        └──────────────┬────────────┘
                       ↓
              Submit payroll for review
```

For a typical 200-employee payroll, the employer should perform:

- one generation or import action;
- one review of aggregate totals and rule sources;
- one bulk confirmation for ready employees;
- individual work only for exceptions;
- one final submission after all blocking exceptions are resolved.

## 3. Product rules

### 3.1 Manual lines become an exception tool

Keep **Add manual reviewed line** for:

- bonuses and allowances;
- reimbursements;
- one-time deductions;
- accountant adjustments;
- off-cycle corrections;
- a statutory override supported by review evidence.

Do not require ordinary SSS, PhilHealth, Pag-IBIG, or withholding amounts to be entered through this modal.

### 3.2 Review is exception-first

The run page should classify each employee-agency assessment as one of:

- **Ready** — rule, coverage, inputs, and calculated/imported amounts are complete;
- **Needs attention** — configuration or evidence is missing or inconsistent;
- **Reviewed** — an authorized reviewer confirmed the assessment;
- **Superseded** — payroll inputs changed after generation and the assessment must be regenerated.

### 3.3 Zero is an explicit decision

A missing registration number must not silently become a zero contribution or exemption. Bulk zero actions are permitted only when all selected rows share an explicit reviewed treatment and source.

### 3.4 Finalized payroll remains immutable

Generation, import, bulk review, and overrides are available only while the run is a draft. A finalized run retains the exact rules, inputs, amounts, reviewer, and evidence used at finalization.

### 3.5 Production calculations require approved rule versions

Automatic amounts may only use an effective `StatutoryRuleVersion` that:

- covers the payroll cutoff or pay date according to the agency policy;
- has a source reference;
- has review evidence;
- has been approved;
- does not overlap another approved version for the same organization and agency.

Test-only rules must be clearly labeled and must not be usable for production finalization.

## 4. Existing foundations to reuse

The current code already provides:

- `EmployeeStatutoryCoverage` for effective-dated employee coverage and registration evidence;
- `StatutoryRuleVersion` for reviewer-gated, effective-dated statutory tables;
- `PayrollRun`, `PayrollStatement`, and `PayrollLine` for run and statement snapshots;
- manual payroll lines with employee, employer, amount, effective date, and source information;
- statutory review validation in `payroll/statutory.py`;
- run locking after review/finalization;
- AJAX statutory saves that update the open employee section without a page reload;
- audit events for payroll and statutory actions.

The new implementation should extend these structures. It should not create a parallel employee coverage or rule-version system.

## 5. Proposed user experience

### 5.1 Payroll settings

Add a **Statutory rules** section under Payroll Settings.

For each agency, show:

- rule status: missing, draft, reviewed, or approved;
- effective period;
- calculation basis;
- bracket or rate summary;
- rounding method;
- official source reference;
- reviewer and approver;
- employees affected by the current version.

Primary actions:

- **Add rule version**;
- **Review version**;
- **Approve version**;
- **View version history**;
- **Import rule table**, if a validated table format is introduced later.

Approved versions are immutable. A correction creates a new effective-dated version.

### 5.2 Employee pay profile

Add a **Statutory setup** section to the employee pay profile.

Display one row per agency:

| Agency | Coverage | Effective period | Evidence | Readiness |
|---|---|---|---|---|
| SSS | Covered | Jan 1, 2026–Current | Reviewed | Ready |
| PhilHealth | Covered | Jan 1, 2026–Current | Reviewed | Ready |
| Pag-IBIG | Needs review | — | Missing | Action required |
| BIR withholding | Covered | Jan 1, 2026–Current | Reviewed | Ready |

Government identifiers must not appear on the payroll-run page, in URLs, toast messages, or general audit summaries. Restrict access to identifier values and avoid copying them into calculation snapshots when a non-sensitive coverage reference is sufficient.

Provide a bulk employee-setup tool for organizations onboarding many employees:

- select employees;
- choose agency and coverage status;
- set the effective date;
- enter shared review evidence;
- preview affected employees;
- confirm once;
- record one batch audit event plus individual effective-dated rows.

### 5.3 Draft payroll statutory workspace

Replace the repeated expanded employee forms with one run-level workspace.

Recommended structure:

```text
Statutory review
200 employees · 800 agency assessments

[ Generate assessments ] [ Import reviewed amounts ]

Ready for review     Needs attention     Reviewed
186 employees        14 employees        0 employees

[ Review 186 ready employees ] [ Open exceptions ]

Employee/agency table
Employee | Agency | Basis | Employee | Employer | Source | Status | Action
```

Required filters:

- employee search;
- agency;
- status;
- registration/coverage status;
- calculation source: automatic, import, or manual override;
- zero amounts;
- changed since last review.

The table must use server-side pagination and bulk selection that is scoped to the active filters. The UI must clearly distinguish **select visible rows** from **select all matching rows**.

### 5.4 Bulk review confirmation

The bulk confirmation modal must show enough information to make a review decision:

- number of employees and assessments;
- agencies included;
- total employee deductions per agency;
- total employer contributions per agency;
- rule-version/source references;
- count of zero treatments;
- exclusions and warnings;
- reviewer note;
- confirmation that the run will remain a draft.

Actions:

- **Cancel**;
- **Confirm reviewed assessments**.

Do not show 200 repeated forms inside the modal.

### 5.5 Exception detail

Keep an individual employee-agency editor for:

- missing coverage;
- pending registration;
- exemptions;
- no effective rule version;
- invalid calculation basis;
- imported amount mismatch;
- zero or negative source basis requiring review;
- compensation changed after generation;
- manual override;
- stale assessment after recalculation.

Use a modal or dedicated detail page. Do not append a large editor above or below the table.

### 5.6 Manual adjustments

Rename the current section to **Manual adjustments** and clarify its scope:

```text
Manual adjustments
Add a one-time earning, reimbursement, deduction, employer contribution,
or reviewed statutory override. Ordinary statutory amounts are generated
or imported from the Statutory review workspace.
```

Add optional component presets so the employer can select a stable code instead of retyping labels.

## 6. Data model changes

### 6.1 `PayrollStatutoryAssessment`

Add a first-class model instead of storing the active workflow only inside `PayrollStatement.snapshot`.

Suggested fields:

```text
statement                     FK PayrollStatement
organization                  FK Organization
employee                      FK Employee
agency                        SSS / PHILHEALTH / PAGIBIG / BIR
status                        PROPOSED / READY / NEEDS_REVIEW / REVIEWED / SUPERSEDED
source_type                   CALCULATED / IMPORTED / MANUAL_OVERRIDE / ZERO / EXEMPT
coverage                      FK EmployeeStatutoryCoverage, nullable
rule_version                  FK StatutoryRuleVersion, nullable
employee_line                 FK PayrollLine, nullable
employer_line                 FK PayrollLine, nullable
employee_amount               Decimal
employer_amount               Decimal
calculation_basis             Decimal, nullable
calculation_snapshot          JSON
source_reference              CharField
review_note                   TextField
registration_follow_up        TextField
input_fingerprint             CharField
reviewed_by                   FK User, nullable
reviewed_at                   DateTime, nullable
created_at / updated_at
```

Constraints:

- unique `(statement, agency)`;
- amounts cannot be negative;
- reviewed rows require reviewer, time, source, and a current fingerprint;
- calculated rows require an approved rule version;
- `employee_line` must be a deduction line on the same statement;
- `employer_line` must be an employer-contribution line on the same statement;
- BIR assessments cannot have an employer contribution line;
- a line cannot be assigned to more than one active assessment;
- organization, employee, statement, coverage, rule, and lines must belong to the same tenant and run.

### 6.2 Payroll line provenance

Extend `PayrollLine.source` into documented choices or add a separate origin field:

```text
CALCULATED_PAY
CALCULATED_COMPONENT
CALCULATED_STATUTORY
IMPORTED_STATUTORY
MANUAL_ADJUSTMENT
MANUAL_STATUTORY_OVERRIDE
```

Add a stable `source_key` or uniqueness constraint so regeneration cannot create duplicate statutory lines. A suggested key is:

```text
statement + agency + share + source_type
```

Keep existing source values readable for historical rows.

### 6.3 Import batch records

Add `PayrollStatutoryImport` and `PayrollStatutoryImportRow` when CSV/XLSX import is implemented.

The batch records:

- original filename;
- file hash;
- run;
- uploaded by and uploaded at;
- row counts by valid, warning, and invalid status;
- confirmation actor/time;
- parser/schema version.

Each row records the employee code, agency, amounts, source reference, validation result, and resulting assessment. Do not store government identifiers in the import unless a separately approved secure import design requires them.

## 7. Calculation and orchestration services

Create a dedicated service module, such as `payroll/statutory_assessments.py`.

### 7.1 Resolution functions

Implement and verify:

```text
resolve_employee_coverage(employee, agency, cutoff_date)
resolve_statutory_rule(organization, agency, cutoff_date)
resolve_statutory_basis(statement, agency, rule_version)
calculate_statutory_amounts(statement, agency, coverage, rule_version)
```

All functions must use explicit dates. Do not use the server's current date to select a payroll rule.

### 7.2 Generation

Implement:

```text
generate_statutory_assessments(run, actor, selected_agencies=None)
```

Generation must:

1. lock the draft payroll run;
2. load statements, coverage, approved rules, compensation, and relevant lines in bounded queries;
3. resolve one assessment per statement and agency;
4. generate deterministic employee and employer payroll lines where amounts apply;
5. classify incomplete rows as exceptions instead of guessing;
6. save an input fingerprint;
7. update statement deduction, employer contribution, and net totals;
8. record aggregate and per-exception audit evidence;
9. return counts and totals for the UI.

Use `bulk_create`/`bulk_update` where safe. For 200 employees and four agencies, generation should not issue queries inside the employee-agency loop.

### 7.3 Bulk review

Implement:

```text
bulk_review_statutory_assessments(
    run,
    actor,
    assessment_ids_or_filter,
    review_note,
    expected_run_revision,
)
```

The service must:

- lock the run and selected assessments;
- reject non-draft runs;
- reject `NEEDS_REVIEW` and stale assessments;
- recompute fingerprints before saving;
- require one explicit reviewer note;
- update reviewer/time on every selected assessment;
- record a batch audit event with counts, agencies, totals, filters, and assessment IDs;
- never accept employee IDs outside the run or organization.

### 7.4 Recalculation behavior

Payroll recalculation must have explicit behavior:

- attendance/pay changes supersede affected calculated assessments;
- changing any relevant payroll line invalidates the related assessment fingerprint;
- manual adjustments unrelated to statutory calculations should not invalidate every statutory review;
- statutory lines are regenerated idempotently;
- reviewed assessments remain visible as prior evidence but return to **Review again** when their inputs change;
- the UI explains which input changed.

Refine the current statement fingerprint so it includes only inputs relevant to the agency assessment. The current whole-statement line fingerprint can invalidate unrelated reviews after an unrelated manual line is added.

## 8. Import workflow

### 8.1 Initial CSV schema

Support this minimum schema:

```csv
employee_code,agency,employee_amount,employer_amount,period_start,period_end,source_reference
PT-SEED-001,SSS,300.00,600.00,2026-09-01,2026-09-30,TEST-ONLY Sep 2026 sample
```

Use stable agency codes: `SSS`, `PHILHEALTH`, `PAGIBIG`, and `BIR`.

### 8.2 Import sequence

1. Upload file.
2. Parse into a temporary import batch.
3. Show a preview with valid rows, warnings, and errors.
4. Require the employer to confirm the preview.
5. Apply valid rows transactionally and generate imported statutory lines.
6. Keep invalid rows unapplied and downloadable as an error report.
7. Require bulk review after import unless the uploader and reviewer roles are deliberately allowed to be the same.

### 8.3 Import validation

Reject or flag:

- employee code not in the run;
- duplicate employee-agency rows;
- unsupported agency code;
- negative amount;
- employer amount on BIR withholding;
- period mismatch;
- organization mismatch;
- missing source reference;
- changed run revision after preview;
- an existing reviewed assessment that would be overwritten without an explicit replacement action.

## 9. Views and endpoints

Prefer dedicated endpoints over adding more branches to the existing run-detail POST handler.

Suggested routes:

```text
POST /payroll/runs/<run>/statutory/generate/
GET  /payroll/runs/<run>/statutory/
POST /payroll/runs/<run>/statutory/bulk-review/
GET  /payroll/runs/<run>/statutory/<assessment>/
POST /payroll/runs/<run>/statutory/<assessment>/override/
POST /payroll/runs/<run>/statutory/import/preview/
POST /payroll/runs/<run>/statutory/import/<batch>/confirm/
```

Each mutation must enforce organization ownership and employer authorization in the service layer as well as the view.

JSON responses should return:

- success or failure;
- a specific error message;
- updated counts and totals;
- changed row HTML or normalized row data;
- run revision;
- whether submission is now enabled.

## 10. UI behavior and design requirements

Follow `SHIFTLY_PROJECT_DESIGN_SKILL.md`:

- use a compact operational dashboard, not oversized cards;
- make status visible with text and color;
- keep the main action obvious;
- use a modal or dedicated page for row details;
- maintain 44 px minimum touch targets;
- provide visible keyboard focus;
- use semantic tables and labeled controls;
- provide loading, success, empty, and error states;
- do not show a success toast until the server confirms the mutation;
- preserve the user's filters, page, selection, and scroll position after save;
- avoid full-page reloads for bulk review and individual exception saves;
- make destructive replacement actions require confirmation.

The bulk toolbar should become sticky only inside the statutory workspace and only while rows are selected. On mobile, replace the wide table with compact employee cards and a filter drawer.

## 11. Concurrency, idempotency, and audit controls

### 11.1 Run revision

Add a run calculation/review revision or reuse a deterministic run fingerprint. Every preview and bulk confirmation submits the revision it was based on. Reject stale writes with:

```text
This payroll changed after you opened the review. Refresh the assessment preview before confirming.
```

### 11.2 Idempotent generation

Running generation twice with unchanged inputs must produce the same assessments and line totals without duplicates.

### 11.3 Transactions and locks

Generation, import confirmation, bulk review, and override actions must use `transaction.atomic()` and `select_for_update()` on the run and affected statements/assessments.

### 11.4 Audit events

Record:

- who generated assessments;
- rule and coverage versions used;
- aggregate totals;
- exceptions produced;
- who imported a file and its hash;
- who bulk-reviewed which population;
- who overrode an amount and why;
- which prior review was superseded and what input changed.

Avoid putting government identifiers in general audit metadata.

## 12. Phased implementation

### Phase 0 — Safety groundwork

- [ ] Add explicit payroll-line source choices and backward-compatible mapping. *(The existing line source values remain readable; assessment source types are now explicit.)*
- [x] Add run revision/fingerprint support.
- [x] Add `PayrollStatutoryAssessment` and its constraints/indexes.
- [x] Read existing snapshot reviews for compatibility.
- [x] Keep finalized historical statements unchanged.
- [x] Add organization ownership checks to every new service.

### Phase 1 — Immediate bulk-review relief

This phase improves the existing manual model before automatic calculations are enabled.

- [x] Add a run-level statutory table with filters and pagination.
- [x] Add **select visible** and **select all matching** behavior.
- [x] Add bulk review for rows that already have valid manual lines.
- [x] Add controlled bulk zero, other-cutoff, and not-applicable treatments.
- [x] Require shared evidence and show affected employee/agency counts.
- [x] Keep exception rows out of bulk confirmation.
- [x] Replace repeated expanded forms with one focused exception detail section.
- [x] Rename **Manual reviewed lines** to **Manual adjustments** and clarify its purpose.

### Phase 2 — Batch line entry and CSV import

- [ ] Add a multi-row adjustment grid for small batches.
- [ ] Add CSV template download.
- [ ] Add import upload, preview, validation, confirmation, and error export.
- [ ] Convert confirmed import rows into assessments and payroll lines idempotently.
- [ ] Show import batch history and audit evidence.

### Phase 3 — Employee statutory setup

- [ ] Add employee-profile statutory coverage UI.
- [ ] Add effective-dated coverage creation and history.
- [ ] Add organization-wide setup dashboard.
- [ ] Add bulk coverage assignment with preview and confirmation.
- [ ] Add readiness exceptions to employee pay profiles and payroll creation.

### Phase 4 — Automatic statutory calculation

- [ ] Add reviewed/approved statutory rule-version management UI.
- [ ] Define and validate the JSON bracket schema for each agency.
- [ ] Implement agency calculators with explicit rounding and cutoff policies.
- [ ] Generate assessment and line snapshots for all statements.
- [ ] Add calculation explanations visible to reviewers.
- [ ] Block production finalization when an automatic amount uses an unapproved or test-only rule.

### Phase 5 — Exception-first workflow and hardening

- [ ] Add exception categories and recommended resolution actions.
- [ ] Add stale-review explanations after recalculation.
- [ ] Add role separation where required for prepare/review/finalize.
- [ ] Verify query counts and response time with 200, 1,000, and 5,000 employees.
- [ ] Add accessible desktop, tablet, and mobile states.
- [ ] Complete shadow payroll comparison before enabling production automation.

## 13. Migration and compatibility

- Do not rewrite finalized payroll runs.
- Continue rendering legacy `snapshot["statutory_reviews"]` data.
- For draft runs, provide an explicit one-time **Migrate reviews to the new workspace** action or regenerate assessments after warning the user that current draft reviews will be superseded.
- Copy compatible current draft reviews into `PayrollStatutoryAssessment` only when their fingerprints are current and their referenced lines exist.
- Do not silently convert a missing review into zero, exemption, or not applicable.
- Keep old manual lines visible. Map them to the new source labels without changing amounts.

## 14. Verification plan

### 14.1 Service cases

- 200 employees × 4 agencies generate exactly 800 assessments.
- Running generation twice produces no duplicate lines or assessments.
- BIR creates no employer contribution.
- An employee with missing coverage becomes an exception.
- An agency without an approved effective rule becomes an exception.
- Bulk review rejects stale, exceptional, cross-tenant, or out-of-run rows.
- Adding an unrelated bonus does not invalidate SSS review.
- Changing compensation invalidates assessments whose basis depends on compensation.
- Recalculation preserves manual adjustments and supersedes affected calculated statutory lines.
- Import confirmation rejects duplicate employee-agency rows and stale run revisions.
- Finalized runs reject every statutory mutation.

### 14.2 UI states

- no assessments generated;
- generating/loading;
- all rows ready;
- mixed ready and exception rows;
- all reviewed;
- empty search result;
- one row selected;
- visible page selected;
- all matching rows selected;
- bulk confirmation;
- stale preview error;
- import preview with valid, warning, and invalid rows;
- individual exception editor with and without manual override lines;
- mobile card layout;
- keyboard-only operation;
- server validation error without a page reload.

### 14.3 Acceptance scenario for 200 employees

1. Create a draft run containing 200 configured employees.
2. Generate 800 statutory assessments.
3. Confirm normal employees appear in **Ready** and incomplete employees appear in **Needs attention**.
4. Bulk-review all ready assessments with one confirmation.
5. Resolve only the exception employees individually.
6. Confirm statement deductions, employer contributions, net pay, and run totals.
7. Recalculate after changing one employee's eligible input.
8. Confirm only affected assessments require review again.
9. Submit the run after the pending count reaches zero.
10. Finalize and verify that the stored snapshots remain unchanged after later rule updates.

Target acceptance measures:

- no more than one bulk confirmation for the normal population;
- no repeated source/reason entry for normal employees;
- no duplicate statutory payroll lines;
- all exceptions identify the employee, agency, cause, and next action;
- a 200-employee generation and review page remains responsive and paginated;
- totals reconcile to the sum of statement lines;
- complete audit evidence exists for generation, import, review, override, and finalization.

## 15. Rollout controls

1. Ship behind an organization-level feature flag.
2. Enable Phase 1 bulk review without automatic government calculations.
3. Pilot CSV import with synthetic and adviser-reviewed files.
4. Run automatic calculations in shadow mode against independently reviewed payrolls.
5. Compare every employee and agency amount and document variances.
6. Obtain payroll/legal review of rule tables, cutoff allocation, and rounding.
7. Enable automatic line generation only for approved organizations and rule versions.
8. Keep manual override and rollback-to-draft procedures available.

## 16. Definition of done

This work is complete when:

- manual lines are no longer required for ordinary statutory processing;
- an employer can process a normal 200-employee statutory population through one generation/import and one bulk review;
- individual forms are limited to exceptions and overrides;
- employee statutory coverage and rule tables are effective-dated and auditable;
- generation and import are idempotent and tenant-safe;
- stale data cannot be reviewed or finalized;
- recalculation invalidates only affected assessments;
- the run cannot be submitted while blocking statutory exceptions remain;
- finalized statements preserve their exact statutory inputs, sources, amounts, and reviewers;
- the UI follows Shiftly's compact, status-driven operational design system.

## 17. Recommended first implementation slice

Implement **Phase 0 plus Phase 1** first.

This delivers the largest usability improvement without claiming that Shiftly already has legally approved automatic contribution calculations. It changes the 200-employee workflow from hundreds of repeated forms to a filtered bulk review plus an exception queue, while keeping the existing manual line and review evidence model available during the transition.
