# Payroll and modal walkthrough: implementation solution plan

**Prepared:** 2026-10-09  
**Status:** Implemented; automated regression and a live 1024 × 668 browser pass completed on 2026-10-09.  
**Scope:** The five issues reported after the full application walkthrough.  
**Evidence:** Reported browser behavior, source inspection, Django regression tests, and live local-browser checks. The remaining viewport matrix and a live successful statutory save still require a dedicated acceptance pass.

### Implementation record

- Individual statutory review now has an explicit reversed form action in both render contexts, handles structured HTTP 422 responses, refreshes saved rows, preserves accurate pending counts, and keeps assessment state valid when a review is created on demand.
- Payroll setup preview now uses the requested dates, run type, employee scope, effective attendance, and reviewed period inputs through a read-only organization-scoped endpoint. The client debounces changes, discards stale responses, and reports unavailable previews instead of showing false zeroes.
- Historical statement, payslip, and export presentation share one pay-basis resolver for explicit, compensation-version, and legacy rate-version snapshots.
- Add terminal, Sync settings, Add holiday, and Create component dialogs use a single header/body/footer layout. The body is the only scroll region and the biometric dialog now fits its footer inside the dynamic viewport.
- Statutory filters and review rows have shrink-safe layout rules and a narrow stacked-row presentation without a page-level overflow workaround.

Automated verification: `manage.py check` passed; `manage.py test --verbosity 1` passed with 128 tests and 8 expected skips. Live browser verification at 1024 × 668 confirmed the payroll preview period refresh, component and holiday modal footer reachability, Sync settings modal, and Add terminal modal footer reachability after the cache-busted asset update.

Related documents:

- [Full application simulation scenario](FULL_APPLICATION_SIMULATION_SCENARIO.md)
- [Bulk statutory workflow plan](PAYROLL_BULK_STATUTORY_WORKFLOW_IMPLEMENTATION_PLAN.md)
- [Payroll workbook plan](PAYROLL_WORKBOOK_IMPLEMENTATION_PLAN.md)
- [Biometric attendance plan](BIOMETRIC_ATTENDANCE_IMPLEMENTATION_PLAN.md)

## 1. Outcomes and implementation order

| Order | Issue | Priority | Required outcome |
| --- | --- | --- | --- |
| 1 | Individual statutory exception save returns HTTP 404 | P1 | A valid individual review saves; invalid submissions show actionable form errors. |
| 2 | Payroll setup preview reports zero approved timesheets for a paying period | P2 | Counts update for the actual period and employee scope. |
| 3 | Employee statement displays “— pay” | P2 | Historical hourly statements display “Hourly pay,” including older supported snapshot shapes. |
| 4 | Add terminal, holiday, and component dialog content/footer is clipped | P1 | Required fields and actions remain reachable on short and narrow screens. |
| 5 | Statutory workspace overflows horizontally | P2 | Filters, selection controls, and review rows fit the available width without page overflow. |

Implement these as separate, reviewable changes. Address the statutory save before relying on the individual review flow for later acceptance checks. Establish the dialog layout pattern before adapting the bulk review dialog and mobile statutory workspace.

### Constraints

- Preserve organization access checks, CSRF protection, draft-only mutations, audit evidence, and statutory validation.
- Preserve finalized payroll snapshots and financial totals. A display fix must not require recalculating finalized payroll.
- The preview must be read-only: no draft creation, recalculation, assessment generation, or audit writes on a preview request.
- Use synthetic records for verification. Keep existing finalized runs intact.
- Database migrations are not expected. Reassess this only if implementation reveals an actual schema requirement.
- Do not expand this work into automatic statutory calculations, payroll classification changes, or changes to biometric reconciliation.

## 2. Issue A — Individual statutory exception save returns HTTP 404

### Evidence and diagnosis

The individual exception page opened, but submitting the review returned HTTP 404. Bulk review succeeded.

Source inspection found:

1. `templates/payroll/_statutory_review.html` contains a hidden input named `action`, with value `statutory_review`. The form does not declare an explicit submission URL.
2. `static/js/payroll-statutory-review.js` sends the request using `fetch(form.action || window.location.href, ...)`.
3. A form control named `action` can shadow the form's native `action` property. JavaScript can therefore pass an input element rather than the intended URL to `fetch`.
4. The dedicated route already exists in `payroll/urls.py`, and `statutory_exception` supports GET and POST with organization/run/assessment checks.

**Diagnosis confidence:** Strong source-backed explanation for the 404. Capture the failed request URL during implementation to confirm the browser used an unintended path. Do not treat this as a missing Django route or remove legitimate 404 checks.

The same handler also rejects every non-2xx response before rendering returned form HTML. The dedicated view intentionally returns HTTP 422 for invalid input, so field errors can be replaced by a generic toast. Its JSON response omits `pending_count`, while the client currently converts a missing count to zero. These are adjacent defects in the same submission contract.

### Implementation steps

- [ ] Reproduce the individual save with browser Network tools and record request URL, HTTP method, response status, and sanitized response shape. Do not log statutory identifiers or full submitted evidence.
- [ ] Define an explicit submission URL for both render contexts: the dedicated exception page and the statutory form embedded in run detail. Use Django URL reversal and pass the URL into the shared partial, including AJAX replacement renders.
- [ ] Read the URL with `form.getAttribute("action")`, resolving a missing/empty attribute against the current page URL. Do not use `form.action`. Keep the hidden `action` field where the run-detail POST dispatcher requires it.
- [ ] Preserve `statement_id`, prefixed field names, CSRF token, request headers, and organization/run/assessment validation.
- [ ] Treat a structured 422 response containing form HTML as an expected validation result: replace the form, retain submitted values, expose errors, focus the first invalid field, and re-enable submission.
- [ ] Handle authorization, missing-resource, server, malformed-response, and network failures separately from validation. Preserve the form and entered values; never show success after failure.
- [ ] Align both save endpoints' response contract. Include accurate run pending counts where available; the client must only update counters when a valid count is present. An absent count must not become zero.
- [ ] Refresh the saved statement data before producing review rows, totals, completion state, and replacement HTML. The service re-fetches the statement, so the view must use the returned/refreshed snapshot while retaining the bound form for validation errors.
- [ ] Confirm that the agency selected in the form is the agency saved and reported to the user. The URL still must identify an assessment belonging to the authorized run.
- [ ] Keep double-submit protection and verify that one successful save creates the intended review/audit change only once.

### Related service regression to cover

`payroll/statutory.py::record_statutory_review` creates a missing assessment with status `REVIEWED` before assigning reviewer, timestamp, source evidence, and fingerprint. If model validation runs at that creation point, it can reject the incomplete reviewed record.

Cover the path where individual review is used before assessment generation. If reproduced, create the assessment in a valid non-reviewed state and complete it within the existing transaction, or supply all required evidence before its first reviewed save. Preserve model validation and transaction rollback. This is a separate potential validation failure, not the explanation for the observed HTTP 404.

### Files

- `static/js/payroll-statutory-review.js`
- `templates/payroll/_statutory_review.html`
- `templates/payroll/statutory_exception.html`
- `templates/payroll/run_detail.html`
- `payroll/views.py` — dedicated and embedded review handlers
- `payroll/statutory.py` — only for the verified service regression above
- `tests/test_payroll.py` and/or focused statutory regression tests

### Acceptance checks

- Valid individual review: correct POST URL, HTTP 200 JSON, updated row/counts, and persisted result after reload.
- Invalid individual review: HTTP 422, visible field or non-field errors, values retained, no partial write.
- Both dedicated and embedded forms work; ordinary non-AJAX submission still works.
- Missing assessment creation and pre-generated assessment update both work through supported entry points.
- An assessment from another organization or run remains inaccessible. Finalized runs remain protected.
- Bulk review still produces correct selected/matching counts and review results.
- Network failure, session expiry, and unexpected server response never imply that a review saved.

## 3. Issue B — Payroll preview shows zero approved timesheets

### Confirmed source mismatch

`payroll/views.py::_run_form_context` always chooses the previous period for preview counts. `static/js/payroll-run-form.js` updates the displayed date labels when the user changes the period, but approved/review counts come from the original HTML data attributes. Reviewed period inputs are also computed for the original dates.

There are additional scope differences:

- The initial timesheet count filters all active employees, while the form has a more specific selectable employee queryset.
- Reviewed period inputs are initially counted across the organization rather than the selected employees.
- The calculator searches a date margin and uses effective attendance in the employee's payroll timezone. A simple `shift__work_date` range is not equivalent at period boundaries, with corrections, or across timezones.

The reported PHP 960 calculation is consistent with valid input being found by the calculator despite stale preflight counts. It does not establish that every preview mismatch has the same cause.

### Counting contract

Define the preview as **source availability for the requested period and employee scope**. An approved timesheet count is not a promise that every source passes all payroll calculation checks or produces positive pay.

- Resolve the employee population using the same selection rules as new-run creation. Selected employees means exactly that validated set; an empty selection must not fall back to everyone.
- Count distinct approved timesheets whose effective attendance overlaps the period under the calculator's existing timezone/date rules.
- Count non-approved timesheets using the same population and period rules, preserving the current “Need review” meaning.
- Count reviewed period-input records for the selected employees and the exact requested period, as the daily-input calculator does.
- Missing or invalid attendance must remain an explicit readiness issue and must not be silently presented as valid payable input.
- Off-cycle runs must explain their adjustment-based source behavior; do not display ordinary attendance counts as if off-cycle creation recalculated attendance.
- Retain existing business rules for daily input/attendance conflicts, missing profiles, historical compensation, and already-used sources in the authoritative draft calculation.

### Implementation steps

- [ ] Extract small read-only helpers for employee scope and source date eligibility. Reuse the relevant predicates in preview and calculation without moving mutation logic into preview.
- [ ] Add a dedicated preview input form/validator for dates, scope, employee IDs, run type, and parent-run context. Reuse period rules from run creation; do not require draft-creation request keys to fetch a preview.
- [ ] Add an employer-only, organization-scoped read-only endpoint, proposed name `payroll:run_preview`. Return counts and the normalized request context, with structured validation errors for invalid inputs.
- [ ] Reject foreign employee IDs and unauthorized parent runs. Do not expose another organization's counts.
- [ ] Use the same helper for the initial server-rendered preview. Bound form dates and selected employees take precedence over defaults after a failed create submission.
- [ ] Refresh counts when period shortcuts, custom dates, employee scope, employee selection, run type, or parent context change. Add a live update target for reviewed period inputs.
- [ ] Debounce rapid changes and abort/discard superseded requests. Only the response matching the latest requested context may update the preview.
- [ ] Show “Updating…” while waiting. On failure, show “Preview unavailable” with retry guidance; never display stale counts as current or convert errors to zero.
- [ ] Keep create-run validation authoritative. A preview transport failure alone must not cause an incorrect draft or bypass server validation.
- [ ] Make the source-availability wording clear. Avoid claiming that this lightweight preview has completed the full payroll calculation.

### Files

- `payroll/views.py` — `_run_form_context`, create-run context, new preview view
- `payroll/forms.py`, `payroll/urls.py`
- `payroll/services.py` — shared scope/date predicates only; preserve calculation behavior
- Proposed `payroll/preview.py` for read-only preview assembly
- `templates/payroll/run_form.html`
- `static/js/payroll-run-form.js`
- `tests/test_payroll.py`, `tests/test_payroll_scenarios.py`

### Acceptance checks

- Fixture: one approved eight-hour timesheet at PHP 120/hour in the chosen period. Preview shows one approved source; an otherwise clean draft calculates PHP 960.
- Switching to an empty previous period shows zero; switching back restores one without reloading.
- Selected/all-active modes, select-all, clear-selection, inactive employees, and payroll-disabled employees follow the creation scope rules.
- Invalid bound dates retain the user's input and show validation; they do not quietly show previous-period counts.
- Effective corrections, overnight work, and differing employee/organization timezones use the same boundary semantics as calculation.
- Reviewed daily inputs update with dates and selected employees. Duplicate-source warnings still occur during draft calculation.
- Responses arriving out of order cannot overwrite the latest preview.
- Repeated preview requests create no runs, statements, assessments, payroll lines, or audit events.

## 4. Issue C — Statement modal displays “— pay”

### Confirmed source mismatch

Run-detail presentation reads `snapshot.pay_basis` and `snapshot.compensation_versions`. Hourly calculation stores its historical compensation entries under `snapshot.rate_versions`. Consequently, the modal and employee statement row can miss a basis that is present in the saved snapshot.

`payroll/payslips.py::_snapshot_pay_basis` already supports both version keys, although it picks the first basis it finds. Presentation logic is duplicated across these paths.

### Implementation steps

- [ ] Introduce a shared, read-only snapshot presentation helper, proposed location `payroll/presentation.py`. Keep it independent of PDF rendering dependencies.
- [ ] Resolve a recognized explicit snapshot basis first. Otherwise inspect valid entries in both `compensation_versions` and `rate_versions`.
- [ ] If the versions contain one recognized basis, display its label. If they contain multiple recognized bases, display “Mixed pay.” Different rates with the same hourly basis must still display “Hourly pay.”
- [ ] Handle absent/malformed data gracefully. Use “Pay basis not recorded” when there is no trustworthy historical basis, rather than “— pay” or an assumed Hourly value.
- [ ] Use the helper for the run-detail row and statement modal. Align the existing payslip basis label with the same helper and cover its output in regression checks.
- [ ] Inspect workbook/export basis presentation for the same inconsistency. Share the helper where compatible, while retaining export validation and all monetary mapping rules.
- [ ] Never use today's employee profile to fill missing historical data. Never rewrite finalized snapshots merely to fix the label.

### Files

- `payroll/views.py` — run-detail statement enrichment
- `payroll/payslips.py`
- Proposed `payroll/presentation.py`
- `templates/payroll/run_detail.html`
- `payroll/exports.py` — inspect basis presentation; change only if the same contract applies
- Focused statement/payslip presentation tests

### Acceptance checks

- Hourly snapshot using `rate_versions`: row says Hourly and modal says “Hourly pay.”
- Daily snapshot using `compensation_versions`: “Daily pay.”
- Explicit monthly/mixed snapshots retain accurate labels; this does not enable unsupported monthly calculation.
- Multiple hourly rates remain Hourly; genuinely mixed bases display Mixed.
- Missing/invalid historical basis displays the fallback without an extra “pay” suffix.
- Changing the current profile after finalization does not change the finalized statement's historical basis or amounts.

## 5. Issue D — Long modal fields and buttons are clipped

### Source findings

Payroll dialogs constrain height on both the dialog and its direct form, then scroll the form. Shared overlay rules add sticky headers/footers with negative margins. The relevant rules are spread across `payroll.css` and `overlays.css`, with different selector specificity and viewport-height limits.

Biometric dialogs have separate rules and markup. Their form is a grid with a maximum height, but no explicit header/body/footer row sizing. The body has scrolling rules, yet the outer sizing can still exceed the usable viewport once padding, borders, and intrinsic sizing are included.

**Diagnosis confidence:** The source contains competing sizing/scroll rules consistent with the reported clipping. Confirm the precise overflowing elements using computed styles and bounding rectangles at the failing viewport before editing.

Internal scrolling is appropriate for a long form. The required fix is one controlled scroll region, with no hidden fields or unreachable actions.

### Agreed dialog layout

```text
Dialog: constrained to the available viewport, including borders
  Form: grid rows auto / minmax(0, 1fr) / auto
    Header: title, short description, close button
    Body: fields, help text, validation; the only vertical scroll region
    Footer: Cancel and primary action, outside the scrolling body
```

### Implementation steps

- [ ] Inventory the existing payroll and biometric dialog selectors and all shared-overlay consumers before changing common CSS.
- [ ] Add an opt-in common form-dialog structure/class in `static/css/overlays.css`; migrate Add terminal, Add holiday, and Create component first. Preserve existing dialog IDs and JS hooks.
- [ ] Constrain the actual dialog/form grid to available dynamic viewport height with border-box sizing, `min-height: 0`, `min-width: 0`, and explicit row tracks. Include viewport margins and safe-area padding.
- [ ] Allow vertical scrolling only in the body. Remove conflicting form scrolling and sticky negative-margin header/footer behavior for migrated dialogs.
- [ ] Keep the final input and its validation/help text fully reachable above the footer. Use consistent spacing and visible focus states.
- [ ] Use two field columns where the modal has enough room, collapsing to one on narrow screens. Long descriptions and checkbox explanations should span the form width as needed.
- [ ] Keep primary and cancel actions readable, reachable, and in sensible visual/tab order. Stack buttons when necessary without covering the body.
- [ ] Preserve native dialog focus containment, Escape behavior, close controls, background scroll lock, and return focus to the opening button. On invalid submission, reopen the correct dialog and focus the first error.
- [ ] Apply the same structure to Sync settings and the statutory bulk confirmation dialog if they exhibit the same sizing defect, then check other shared dialogs for regressions.
- [ ] At very short heights or with a virtual keyboard, shorten nonessential header copy and prioritize the form body; if a full-screen dialog variant is needed, retain one body scroll region and accessible actions.

### Files

- `templates/biometrics/devices.html`
- `templates/payroll/holiday_calendar.html`
- `templates/payroll/component_definitions.html`
- `templates/payroll/_statutory_bulk_workspace.html` if migrating bulk confirmation
- `static/css/overlays.css`, `static/css/payroll.css`, `static/css/biometrics.css`
- `static/js/overlay-ui.js`, `static/js/biometric-dialogs.js`, `static/js/payroll-statement-dialog.js` — inspect; modify behavior only where required

### Acceptance checks

- At approximately 1024 × 668 and 1242 × 668, all fields, bottom help text, Cancel, Save, and close controls are reachable and unobscured.
- At 390 × 844, 320 × 568, and 844 × 390, no dialog or page horizontal overflow occurs.
- Check 200% browser zoom and a mobile virtual keyboard where available; label any untested device-specific behavior explicitly.
- Only the dialog body scrolls; the underlying page stays locked while the modal is open.
- Long help text, all field errors, and non-field errors do not cover controls or create a second scrollbar.
- Tab/Shift+Tab, Escape, cancel, submit, and focus restoration work. Clicking inside the form does not dismiss it.
- Existing confirmation, employee, attendance, and statement dialogs remain usable after shared CSS changes.

## 6. Issue E — Statutory workspace causes horizontal scrolling

### Source findings

The filter grid has fixed minimum column widths, but switches layout using a viewport breakpoint. With the sidebar open, the content area can be too narrow even when the viewport is above that breakpoint. The workspace grid also needs explicit minimum-width constraints so child content can shrink.

At mobile widths, the stylesheet explicitly gives the statutory table a 760px minimum width. This forces a wide table rather than a layout adapted to the available space.

### Implementation steps

- [ ] Constrain the workspace, containing cards, grid/flex children, and table wrapper with appropriate `min-width: 0` and `max-width: 100%`.
- [ ] Make filters respond to their available content width, using a wrapping grid or container-based rules. Keep visible labels and comfortable input sizes; place the search field and filter action on separate rows when needed.
- [ ] Allow the selection toolbar to wrap without pushing the page width. Keep the selected count, all-matching state, and Review selected action readable.
- [ ] Retain a conventional table at roomy widths. Contain any intermediate-width horizontal scroll within an explicitly labeled, keyboard-accessible table region.
- [ ] At narrow widths, present each assessment as a stacked row/card: selection and employee first, then agency, reviewed amounts, source, status, and action. Remove the mobile 760px minimum in this mode.
- [ ] Prefer one rendered set of rows/checkboxes with responsive labels. Preserve semantic associations and verify the accessibility tree; do not create duplicate focusable controls or duplicate element IDs for desktop/mobile variants.
- [ ] Keep employee/employer amounts distinct. Wrap long employee codes and source text, align action controls, and avoid ellipsis for information required to review a row.
- [ ] Preserve pagination, filters, selection across the supported scope, skipped/ineligible row rules, and bulk submission behavior. Update JS selectors only if markup changes require it.
- [ ] Check sticky selection controls against the global header. They must not cover the first row, error messages, or open dialogs.
- [ ] Do not mask the defect with `overflow-x: hidden` on the whole page or by hiding essential columns.

### Files

- `templates/payroll/_statutory_bulk_workspace.html`
- `static/css/payroll.css`
- `static/js/payroll-statutory-bulk.js` if responsive markup affects row targeting
- The run-detail wrapper only if its intrinsic sizing is part of the overflow chain

### Acceptance checks

- No document-level horizontal overflow at 320, 390, 640, 768, 1024, 1242, and 1440px widths, including with the sidebar visible where supported.
- Narrow layout exposes every assessment value and action without horizontal scrolling.
- Any intermediate-width table scroll is confined to its own region; filters and selection controls remain within the page.
- Long names, codes, source labels, empty results, and 25/50/100-row pages remain usable.
- Select visible and Select all matching still identify the correct population and display truthful counts.
- Review selected opens a fully usable confirmation dialog and submits only the intended eligible rows.

## 7. Verification and evidence plan

Use the existing Django test infrastructure and focused browser checks. Test additions and execution belong to the implementation phase; none were run to produce this plan.

### Automated regression coverage

| Area | Required coverage |
| --- | --- |
| Statutory backend | Valid and invalid individual requests, missing/generated assessments, persistence, draft-only behavior, organization/run isolation, rollback, bulk compatibility |
| Statutory browser | Correct outgoing URL despite hidden `action`, 422 error rendering, optional counters, duplicate clicks, recovery after failure |
| Preview | Period changes, exact employee scope, bound forms, timezone/overnight/correction boundaries, daily inputs, off-cycle behavior, no writes |
| Preview browser | Date shortcuts, selection changes, unavailable/loading state, stale-response prevention |
| Statement labels | Supported snapshot shapes, mixed/missing data, historical stability, unchanged totals |
| Layout | Viewport screenshots, overflow measurements, keyboard navigation, errors, dialog footer/body boundaries |

Django tests alone cannot reproduce the browser form-property collision or prove modal layout. Include actual browser interaction for those acceptance criteria. Use the existing browser tooling; introduce a new JavaScript test framework only if the project needs one and the change is justified.

### Complete manual acceptance scenario

The scenario below remains the end-to-end acceptance checklist. The automated and
live checks recorded above cover the read-only preview, historical basis resolver,
statutory request contract, and the desktop modal layout. Do not mark the
remaining browser-only items complete from Django tests alone.

1. Use a clearly named synthetic organization/employee, or a fresh draft fixture in the existing review workspace. Do not alter a finalized run to make it editable.
2. Configure an hourly employee at PHP 120 with reviewed payroll prerequisites and a valid period. Use a synthetic scheduled shift from 09:00 to 18:00 with a one-hour unpaid break, producing eight payable hours.
3. Record and approve the timesheet through supported workflows. Ensure this fixture has no unrelated premiums or deductions so PHP 960 is the expected base/gross amount.
4. Open Create payroll run. Select an empty period, then the fixture period, and change employee selection. Confirm the preview moves from zero to one approved source and follows the selection.
5. Submit an invalid date range and confirm retained inputs/errors. Restore valid dates and create a new draft; confirm PHP 960 and the expected source record.
6. Open the employee statement. Confirm “Hourly pay,” then compare row/modal amounts to the draft.
7. Generate statutory assessments. Open an individual exception, submit incomplete evidence, and confirm inline errors without saving. Submit a valid synthetic review and confirm persistence, accurate counts, and the expected request URL.
8. Complete remaining reviews through bulk selection, using explicitly labeled synthetic evidence. Test both selected-visible and all-matching behavior. Do not interpret synthetic zero amounts as statutory guidance.
9. Repeat statutory filtering and selection at narrow widths; inspect every field/action and the bulk dialog. Confirm the page itself has no horizontal scrollbar.
10. Open Add terminal, Sync settings, Add holiday, and Create component at desktop, short-height, and mobile sizes. Trigger validation errors, reach the final field, and close/reopen each dialog. A real terminal connection is unnecessary for layout checks.
11. On the synthetic run only, complete the normal review/finalization flow if needed to verify the historical statement label. Confirm the basis remains Hourly on reload and money values remain unchanged.
12. Check related dialogs and bulk review for regressions. Record screenshots, viewport sizes, expected/actual results, and any untested hardware/mobile conditions.

### Evidence to retain

- A sanitized before/after request trace for the individual save, including the validation case.
- Preview request context/counts paired with the resulting draft's source records and PHP 960 fixture total.
- Statement label screenshots for hourly and missing-basis cases.
- Screenshots of each affected modal at short and narrow sizes, including errors and the last field/footer.
- Statutory workspace screenshots with long text, selected rows, and no page overflow.
- Targeted test results, known unrelated failures, and explicit remaining limitations.

## 8. Completion, rollout, and rollback

- [ ] All five issue acceptance lists pass, with browser evidence for the original failures. (Core implementation and automated coverage pass; the full viewport matrix and live individual-save browser proof remain.)
- [x] Existing finalized payroll remains unchanged by the read-only preview and presentation changes; regression tests pass.
- [x] No unauthorized data becomes visible through the preview endpoint; a foreign selected employee is rejected with HTTP 422.
- [x] No double-submit or duplicate selection behavior is introduced by the updated response/count contract; the existing regression suite passes.
- [x] Related dialogs remain usable at the verified desktop viewport, including the biometric footer sizing fix.
- [x] Update this document's status and the simulation scenario with actual results; do not mark untested cases complete.
- [ ] Deploy matching templates, JavaScript, CSS, and backend endpoints together. Refresh the project's static asset version references as appropriate so old JavaScript cannot pair with a new response contract.

No data cleanup or migration is planned. If rollback is necessary, revert the corresponding code/static assets together. Retain legitimately saved statutory reviews and audit records; a UI rollback must not delete business history. If a source-selection refactor changes existing payroll totals unexpectedly, stop that change and resolve the discrepancy before release.
