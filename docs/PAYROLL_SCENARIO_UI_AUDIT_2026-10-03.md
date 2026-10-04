# Payroll scenario UI and workflow audit — 2026-10-03

## Purpose

This is a read-only browser walkthrough of the scenarios in
`PAYROLL_SCENARIOS.md`. It records UI, workflow, and presentation problems for
a later fixing pass. No payroll run, employee record, attendance record, or
review was submitted or changed during this audit.

## Environment and evidence

- Base URL: `http://127.0.0.1:8000/`
- Organization: Shiftly Payroll Scenario Workspace (organization ID `1`)
- Browser: Codex in-app browser
- Viewports checked: default desktop (`1226px` content width) and phone
  (`390 × 844` browser viewport, `375px` document width)
- Existing large workspace: 200 active payroll employees
- Existing payroll runs:
  - Run `1`: `PAY-20260401-20260430`, Voided, one selected employee
  - Run `2`: `PAY-20260301-20260331`, Draft, monthly calculation blocked
  - Run `3`: `PAY-20261001-20261031`, Draft, 200 selected employees
- Browser console: no warning or error entries were recorded during the
  walkthrough.

## Result summary

The main hourly and daily payroll paths are visible and navigable, but the
scenario cannot be completed entirely through the employer UI. The audit found
five high-priority workflow or state problems, seven medium-priority usability
problems, and several scenario capabilities that currently exist only in the
model/service layer.

The most important mismatch is on payroll run creation: a monthly-paid
employee is labelled **Ready**, and the live preview shows approved timesheets,
even though creating the run will produce a monthly-calculation blocker. The
preview also reports organization-wide readiness instead of readiness for the
selected employee scope.

## Implementation status — October 4, 2026

- [x] PSUI-01: monthly compensation is labelled as needing attention in the run picker.
- [x] PSUI-02: selected-scope readiness is calculated in the live preview.
- [x] PSUI-03: the run list prefers immutable employee membership counts and shows statements separately in code.
- [x] PSUI-04: off-cycle is unavailable until a finalized parent exists; missing parent disables draft creation.
- [x] PSUI-05: void runs receive a terminal historical-state banner and active review queues are hidden.
- [~] PSUI-06: the statutory queue now has search and server pagination; route-level separation remains recommended.
- [x] PSUI-07: human-readable exception labels replace raw codes in the workspace and history.
- [x] PSUI-08: monthly compensation remains an explicit calculation blocker in readiness copy.
- [x] PSUI-09: default profile counts include employees inheriting the organization default.
- [x] PSUI-10: mobile create actions no longer use a sticky overlay.
- [x] PSUI-11: payroll dialogs lock the page and scroll internally.
- [~] PSUI-12: the payroll run employee filter is searchable; the timesheet employee picker still needs server-backed autocomplete.

Additional implementation:

- New all-active payroll runs snapshot employee memberships for immutable scope.
- Employers can record a missed attendance session from a dedicated, reason-required page; a timesheet and audit event are created.
- A broader state-by-state review is recorded in `UI_STATE_RECOMMENDATIONS_2026-10-04.md`.

## Findings

### PSUI-01 — Monthly employees are incorrectly labelled Ready in the run picker

- Priority: High
- Type: UI plus workflow logic
- Route: `/payroll/runs/new/`
- Scenario: Monthly compensation attendance blocker

Reproduction:

1. Open **Create payroll run**.
2. Choose **Selected employees**.
3. Search for `Monthly Employee`.
4. Observe `SCN-MONTHLY · monthly · PHP 24000.00`.

Observed:

- The employee row displays the green/positive label **Ready**.
- Selecting only this employee shows `20` approved timesheets and no
  employee-specific warning in the run preview.
- Run `2` and run `3` prove that this pay basis produces
  `MONTHLY_INPUT_NOT_SUPPORTED` / monthly-calculation exceptions.

Expected:

- The employee should be labelled **Calculation unavailable** or **Will block
  payroll** before the draft is created.
- The preview should name the unsupported pay basis and explain the available
  actions: change to a supported effective compensation version, exclude the
  employee, or wait for an approved monthly conversion policy.

### PSUI-02 — Run readiness is organization-wide instead of scope-aware

- Priority: High
- Type: Workflow logic and decision support
- Route: `/payroll/runs/new/`
- Scenario: Selected employee scope

Reproduction:

1. Choose **Selected employees**.
2. Select only `Monthly Employee`.
3. Read the **Readiness** panel.

Observed:

- The preview says `Employees: 1 selected`.
- The readiness row still says `150 of 200 employees configured · 50 monthly
  calculation(s) unavailable`.
- It does not say that the one selected employee is one of the unsupported 50.

Expected:

- Readiness should be calculated from the chosen run scope and period.
- Suggested copy: `0 of 1 selected employees can be calculated` followed by the
  employee-specific blocker.
- Organization-wide context can remain secondary, but it should not replace
  the decision needed for this draft.

### PSUI-03 — Payroll list employee count disagrees with the immutable run scope

- Priority: High
- Type: Data presentation consistency
- Routes: `/payroll/` and `/payroll/runs/3/`
- Scenario: All-active and selected scope evidence

Observed:

- The payroll list reports run `3` with `150` employees.
- The run detail reports `200 employees selected for this period`, `200
  employees in scope`, and `150 of 200` statements generated.

Impact:

- The list appears to count generated statements rather than payroll-run
  members. An employer can incorrectly conclude that 50 employees were never
  included in the run.

Expected:

- The list should show the immutable scope count (`200`).
- If useful, add a separate statement count such as `150 calculated · 50
  blocked`.

### PSUI-04 — Off-cycle creation is actionable when no finalized parent exists

- Priority: High
- Type: Validation and empty-state workflow
- Route: `/payroll/runs/new/`
- Scenario: Linked off-cycle adjustment

Reproduction:

1. Choose **Off-cycle**.
2. Observe the **Parent run** select.

Observed:

- The parent select contains only `---------` because the workspace has no
  finalized run.
- **Create draft** remains enabled.
- The page does not explain that off-cycle runs require a finalized parent.

Expected:

- Disable the off-cycle choice or the primary action when no eligible parent
  exists.
- Show a clear empty state: `Finalize a regular payroll run before creating an
  off-cycle correction.`
- Do not wait for a postback validation error to explain the prerequisite.

### PSUI-05 — Voided run displays draft/review instructions as if it can continue

- Priority: High
- Type: State-dependent UI
- Route: `/payroll/runs/1/`
- Scenario: Immutable non-draft run

Observed on the voided run:

- The page still displays the three-stage Draft → In review → Finalized
  progress presentation without a terminal Voided state.
- It says `Calculation checks passed` and `Complete the statutory reviews
  before submitting this draft.`
- The statutory queue says one employee is pending even though the run is
  voided and manual lines are locked.

Expected:

- Present **Voided** as the terminal state.
- Replace actionable submission/review instructions with a read-only status
  explanation.
- Keep historical calculation and review evidence visible, but label it as a
  snapshot that cannot continue.

### PSUI-06 — Large payroll run is one extremely long mixed-purpose page

- Priority: Medium
- Type: Information architecture and scale
- Route: `/payroll/runs/3/`
- Scenario: 200-employee run

Observed:

- Document height is approximately `15,431px` at the default desktop viewport.
- The page combines summary, 150 pending statutory queue items, 50 detailed
  exception rows, manual lines, paginated statements, 25 statutory forms on
  the current statement page, and audit history.
- The statutory queue has no employee search, status filter, or its own
  pagination.
- Page navigation for statements also changes which statutory forms are
  rendered, coupling two different tasks.

Expected:

- Keep the Overview page focused on counts, blockers, and next actions.
- Move detailed exceptions, statements, and statutory review to dedicated tab
  views or pages.
- Add employee search, review-status filters, and pagination to the statutory
  queue.
- Preserve the active tab, page, filter, and expanded employee after a save.

### PSUI-07 — Raw exception codes are exposed beside human-readable messages

- Priority: Medium
- Type: Content design
- Routes: `/payroll/runs/2/` and `/payroll/runs/3/`

Observed examples:

- `No_Payroll_Time`
- `Monthly_Input_Not_Supported`

Expected:

- Show `No payroll time` and `Monthly calculation not supported` as user-facing
  titles.
- Keep stable codes in an optional technical-details disclosure or audit export.

### PSUI-08 — Employee profile wording contradicts the actual monthly blocker

- Priority: Medium
- Type: Content and rule clarity
- Route: `/payroll/employees/3/`
- Scenario employee: `SCN-MONTHLY`

Observed:

- The readiness card correctly says monthly-to-payroll conversion is not
  supported.
- The **Primary pay basis** help says `Monthly and mixed bases remain
  reviewer-configured until conversion rules are approved`, which sounds like
  the employee can still be processed through manual review.
- The **Reviewed period inputs** section says it is for daily-paid employees,
  while the monthly test employee contains a reviewed period input.

Expected:

- State directly that Monthly is metadata-only and blocks payroll calculation
  in this release.
- Explain Mixed behavior independently because current run `3` successfully
  calculates mixed employees from attendance.
- For a monthly employee, label the existing period input as retained test or
  source evidence and explain that it does not enable monthly calculation.

### PSUI-09 — Default rule profile card reports zero assignments while employees inherit it

- Priority: Medium
- Type: Misleading metric
- Route: `/payroll/setup/`

Observed:

- `Scenario default · 0 assigned employees` is shown.
- Employee profiles state `Scenario default · Inherited default` across the
  200-employee workspace.

Expected:

- Distinguish direct overrides from inherited use.
- Suggested copy: `200 employees inherit this default · 0 dated overrides`.

### PSUI-10 — Mobile run-creation action bar covers the form content

- Priority: Medium
- Type: Responsive layout
- Route: `/payroll/runs/new/`
- Viewport: `390 × 844`

Observed:

- The sticky **Cancel / Create draft** bar appears within the first viewport and
  overlays the beginning of the **Employee scope** section.
- Content scrolls behind the action bar without compensating bottom space.

Expected:

- On narrow screens, place actions after the form, or use a bottom sticky bar
  with safe-area padding and matching content padding.
- The bar must never cover a heading, input, help text, or validation message.

### PSUI-11 — Rule profile modal has weak mobile close and scrolling behavior

- Priority: Medium
- Type: Responsive modal behavior
- Route: `/payroll/setup/`
- Viewport: `390 × 844`

Observed:

- The close control renders as a standalone `×` below the introduction rather
  than a stable top-right modal action.
- The modal has its own scrollbar while the document body remains scrollable.
- The footer actions are below the first viewport and are not visible until the
  user scrolls the inner modal.

Expected:

- Lock background scrolling while the modal is open.
- Keep the close action in the header.
- Use a sticky modal footer for **Cancel** and **Create profile** on small
  screens, with validation errors kept near their fields.

### PSUI-12 — High-volume employee filters depend on very large native selects

- Priority: Medium
- Type: Scalability and navigation
- Routes: `/payroll/` and `/timesheets/`

Observed:

- The employee filter renders all 200 employees in a native select.
- The timesheet list contains 25,900 rows across 864 pages.
- The run list employee filter and timesheet employee filter do not provide a
  searchable combobox.

Expected:

- Use a searchable employee picker that shows name and employee code.
- Preserve date, employee, status, and page-size filters in pagination links.
- Consider a bounded page jump or result-range control for hundreds of pages.

## Missing employer-facing scenario workflows

The models exist for the first four areas below, but `payroll/urls.py` exposes
no employer page or action for them. These are functional UI gaps rather than
visual polish items.

| Scenario capability | Browser result | Required employer workflow |
| --- | --- | --- |
| Employee statutory coverage dates | No page, profile section, or modal | Add/view effective-dated SSS, PhilHealth, Pag-IBIG, and BIR coverage; record exemption evidence without displaying sensitive identifiers |
| Statutory rule versions | Model exists; no dedicated statutory rule administration UI | Create draft version, detect overlap, review/approve, and show append-only history |
| Cash / bank-transfer payment methods | No page, profile section, or modal | Add adjacent effective-dated methods, show current method/history, and avoid bank credential fields |
| Employee obligations and ledger | No page, profile section, or run workflow | Add reviewed obligation terms, preview installment, and add correction/reversal ledger rows |
| Paper timecard evidence | No import or manual timecard screen | Record morning, afternoon, and overtime segments, day-off/closed marker, reviewer/source, and signature evidence separately from raw punches |
| Employer-entered attendance for a missing punch | Existing attendance rows only expose **Edit attendance** when a session already exists | Add a controlled **Record attendance** action for an absent/no-session shift with reason, audit history, timesheet recalculation, and payroll lock checks |

## Scenario checklist status from this walkthrough

| Checklist item | UI status | Notes |
| --- | --- | --- |
| Organization, rule profile, hourly/daily/monthly/mixed employees | Partially available | Setup and employee profiles exist; monthly readiness is inconsistent |
| Separate Regular and Probation/Part-time selected runs | Available in create flow | No existing labeled probation run was mutated during this read-only audit |
| Idempotency token reuse | Not exercised in UI | Requires creating/submitting synthetic drafts; service coverage remains the current evidence |
| Four-agency statutory coverage records | Not available in employer UI | Model-only workflow |
| Statutory rule version overlap/approval/immutability | Not available as a complete employer workflow | Payroll premium rule versions are visible, but statutory-rule administration is absent |
| Cash and bank-transfer method history | Not available in employer UI | Model-only workflow |
| Obligation proposal, correction, and reversal | Not available in employer UI | Model-only workflow |
| Monthly blocker and daily reviewed input | Visible | Blocker appears after calculation; preflight labels are misleading |
| Paper timecard segments and evidence | Not available in employer UI | No visible source-entry workflow |
| Finalized selected-run scope immutability | Blocked by fixture state | Workspace has no finalized run; off-cycle UI does not explain this prerequisite |

## Behaviors that worked during the walkthrough

- Payroll run creation changes between All active and Selected employee scope
  without a page reload.
- Employee picker search reduced the 200 employee list to the matching employee.
- Selected employee count and attendance-source counts updated in the preview.
- Employee pay profile list pagination showed 30 rows per page and seven pages.
- Attendance pagination showed 30 of 200 shifts for a populated work date.
- Payroll statement pagination showed the correct `126–150 of 150` range on
  page six.
- Monthly calculation exceptions were visible and prevented submission.
- No browser console errors appeared during the audited navigation.

## Recommended repair order

1. Correct scope-aware readiness and monthly employee labels on run creation.
2. Correct employee counts on the payroll list and terminal messaging for
   voided runs.
3. Prevent unusable off-cycle creation when no finalized parent exists.
4. Split the large run page into task-focused views and add statutory queue
   search/filter/pagination.
5. Fix the mobile sticky action bar and modal behavior.
6. Add employer pages for statutory coverage, payment methods, obligations,
   and paper timecards.
7. Replace raw exception codes and clarify monthly/mixed wording.
8. Improve high-volume employee filters and long-list navigation.

## Re-test notes

After the fixes, repeat the walkthrough with a fresh synthetic organization
that includes one hourly, one daily, one monthly, and one mixed employee. Keep
one finalized selected run so the off-cycle and finalized-scope scenarios can
be exercised. Capture desktop and phone evidence for run creation, the run
overview, statutory review, employee setup, and each new employer-facing
workflow.
