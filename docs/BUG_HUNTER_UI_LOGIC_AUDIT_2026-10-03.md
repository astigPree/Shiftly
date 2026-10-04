# Bug hunter audit — 2026-10-03

## Scope and verification status

This began as a source-backed audit and now includes a **partial live browser pass** on the local server using the `Shiftly Payroll Scenario Workspace` employer account. The live pass used the seeded 200-employee payroll dataset, including draft run `PAY-20261001-20261031` (`/payroll/runs/3/`). Findings explicitly marked **Live reproduced** were observed in the rendered application. Findings marked **Confirmed from code** still need a focused browser reproduction before closure.

The audit focuses on the employer payroll run and statutory review flow because it was the latest area changed and contains the highest impact submit actions. Existing working-tree changes were not modified as part of this audit.

## Implementation update — 2026-10-03

The audited payroll pages were revised against `SHIFTLY_PROJECT_DESIGN_SKILL.md` and checked in the live local application.

- **BH-01 fixed:** Submit for review now stays disabled until both blocking exceptions and statutory reviews are complete. The page explains the remaining prerequisite.
- **BH-02 fixed:** Completed statutory banners use a reliable `[hidden]` rule, and the readiness banner and submit action update in place.
- **BH-03 fixed:** The statutory summary is now a scrollable run-wide queue. Every employee has a direct link to the correct statement page and review panel.
- **BH-04 fixed:** Background saves return the first specific field or validation error, keep the panel open, scroll to the invalid field, and preserve inline errors.
- **BH-05 fixed:** Duplicate submit events are prevented before the in-flight guard returns.
- **BH-07 fixed:** Monthly compensation remains visible, but employees are marked **Monthly calculation unavailable** until a supported conversion exists. Employee list, employee profile, payroll overview readiness, and new-run preview use the same state.
- **BH-08 fixed:** Monthly exception summaries now describe the supported resolution instead of directing employers to an unsupported period input.
- **BH-09 fixed:** Payroll run actions now sit directly below the heading at tablet and mobile widths; the blank responsive header region is removed.
- **BH-10 fixed:** Rule-profile creation now opens a focused modal with clear cancel and close actions.
- **BH-11 fixed:** An empty components page presents one contextual creation action; filtered empty results present **Clear filters** instead.

Live checks completed at 1440 × 900, 768 × 900, and 390 × 844. Django's system check completed with no issues. BH-06 remains a test-suite maintenance item because automated browser tests were outside this UI implementation pass.

## Findings to fix

### BH-01 — “Submit for review” is enabled before statutory reviews are complete

- **Severity:** High · **Type:** UI/logic mismatch · **Confidence:** Confirmed from code
- **Route:** `/payroll/runs/<id>/` while the run is a draft
- **Steps:** Open a draft with zero blocking exceptions and at least one employee whose SSS, PhilHealth, Pag-IBIG, or withholding review is pending. Click **Submit for review**.
- **Actual:** The button is enabled because its `disabled` condition checks only `unresolved_exception_count`. The server then rejects the action through `assert_statutory_reviewed`, producing an error toast.
- **Expected:** The button should reflect every submit prerequisite. Show the number of pending statutory reviews beside the action and link directly to the first affected employee. Keep the server validation.
- **Evidence:** `templates/payroll/run_detail.html` draft header action; `payroll/services.py` `submit_for_review()` and `payroll/statutory.py` `assert_statutory_reviewed()`.

### BH-02 — Completed statutory warning can remain visible after an in-place save

- **Severity:** Medium · **Type:** CSS/interaction · **Confidence:** Strong code evidence; browser confirmation needed
- **Route:** `/payroll/runs/<id>/`
- **Steps:** Complete the final outstanding statutory review through **Save statutory review**.
- **Actual risk:** JavaScript sets `banner.hidden = true`, but `.payroll-run-banner { display: flex; }` is an author CSS rule and there is no matching `.payroll-run-banner[hidden] { display: none; }` rule. The warning may remain visible while its count changes to `0`.
- **Expected:** Remove or hide the warning reliably when pending reaches zero. Verify the same behavior at desktop and mobile widths.
- **Evidence:** `static/js/payroll-statutory-review.js` `updatePendingCount()`; `static/css/payroll.css` `.payroll-run-banner`.

### BH-03 — Statutory summary shows a run-wide count but only the current statement page

- **Severity:** Medium · **Type:** Navigation/clarity · **Confidence:** Confirmed from code
- **Route:** A payroll run with more than 25 statements, such as a 200 employee run
- **Steps:** Open page 1 of a draft with pending reviews on later statement pages. Read the statutory summary and follow **Review now**.
- **Actual:** The pending count covers all run statements, while the summary rows and review panels are generated only from `statements.object_list` (10, 25, or 50 per page). Every **Review now** link points to the section heading, not to that employee's panel. Employees on later pages are absent until the user changes the statement page.
- **Expected:** Show the full pending queue with pagination or provide a direct employee link that opens the correct page and panel. State clearly when a list represents only the current page.
- **Evidence:** `payroll/views.py` `statement_page` and `statutory_pending`; `templates/payroll/run_detail.html` summary rows, links, and review panels.

### BH-04 — Invalid statutory submissions still use a generic toast

- **Severity:** Medium · **Type:** Error feedback · **Confidence:** Confirmed from code
- **Route:** `/payroll/runs/<id>/`
- **Steps:** Submit a review with a pending registration and no follow-up note, or choose an incompatible treatment.
- **Actual:** The server returns the field or non-field errors in replacement HTML, but the JSON `message` says only “Check the statutory review fields and try again.” The toast does not name the field or rule that failed. Users must scan a long form below the cards to locate it.
- **Expected:** Return a short error summary and focus/scroll the first invalid field while keeping the current panel open. Retain inline field errors.
- **Evidence:** `payroll/views.py` AJAX response and `static/js/payroll-statutory-review.js` response handler.

### BH-05 — A second submit event can escape the background-save handler

- **Severity:** Low · **Type:** Submission guard · **Confidence:** Confirmed from code; user impact requires reproduction
- **Route:** `/payroll/runs/<id>/`
- **Steps:** Trigger another submit event while the first statutory save is still pending (for example with keyboard submission or a scripted `requestSubmit`).
- **Actual risk:** The handler returns when `form.dataset.submitting === "true"` **before** calling `event.preventDefault()`. The second event can use the browser's normal full-page form submission, causing a reload or duplicate action.
- **Expected:** Prevent the second event before returning; allow only the first request to reach the server.
- **Evidence:** `static/js/payroll-statutory-review.js` document submit listener.

### BH-06 — Browser regression test still expects navigation after statutory save

- **Severity:** Medium · **Type:** Test coverage gap · **Confidence:** Confirmed from code
- **Scenario:** Statutory review validation and four-agency completion
- **Actual:** `tests/test_browser.py` wraps statutory saves in `expect_navigation()`. The current page uses `fetch` and replaces the panel without navigation, so the test no longer checks the intended behavior and would time out when run.
- **Expected:** Assert that the current URL and scroll position remain stable, the panel stays open, inline errors appear, and counts/cards update after the request.
- **Evidence:** `tests/test_browser.py` `test_statutory_review_missing_number_and_return_to_draft`; `static/js/payroll-statutory-review.js` fetch handler.

## Live browser findings

### BH-07 — Payroll readiness marks monthly employees ready even though payroll cannot calculate them

- **Severity:** High · **Type:** Cross-screen logic contradiction · **Confidence:** Live reproduced
- **Routes:** `/payroll/employees/`, `/payroll/employees/3/`, `/payroll/runs/3/`, and `/payroll/runs/new/`
- **Steps:** Open the employee pay-profile list and inspect **Monthly Employee**. Open that employee's profile, then open the October 2026 draft run.
- **Actual:** The list says **200 of 200 employees configured** and shows Monthly Employee as **Pay profile complete** with `PHP 24,000.00 / monthly`. The employee profile says **Payroll ready**, **Payroll readiness complete**, and **5 of 5 complete**, but its summary card simultaneously says **Current compensation: Not configured**. The draft run then has 50 blocking `Monthly_Input_Not_Supported` exceptions because monthly register conversion is unavailable. The new-run preview also reports all 200 employees as configured.
- **Expected:** A monthly or mixed pay basis must show a blocking readiness state until the product can calculate it or the employer has supplied the supported reviewed input. Use one consistent explanation, for example: **Monthly pay conversion is not configured — exclude this employee or configure approved conversion rules.** Do not call the employee payroll-ready before a run can calculate them.
- **Evidence:** Live employer session on October 3, 2026. The affected employee was `Monthly Employee` (`SCN-MONTHLY`); 50 of 200 employees were blocked in run 3.

### BH-08 — The exception summary recommends an action that does not resolve the exception

- **Severity:** High · **Type:** Error guidance · **Confidence:** Live reproduced
- **Route:** `/payroll/runs/3/`
- **Steps:** Open the October 2026 draft run and compare its exception summary with the detailed exception list.
- **Actual:** The summary labels the issue **Monthly period input required** and tells the employer to **Add a reviewed period input before recalculating this statement**. The detailed record instead says `Monthly_Input_Not_Supported` and explains that **monthly register conversion is not configured**. The two messages describe different remediation paths.
- **Expected:** Use the detailed root cause in the summary and link to the supported resolution. If reviewed period inputs are a valid solution, the detailed exception must say so and payroll recalculation must accept them; otherwise do not instruct the employer to add them.
- **Evidence:** All 50 run-3 exceptions displayed the conversion-not-configured cause while the summary displayed the period-input remedy.

### BH-09 — Payroll-run header breaks at tablet and mobile widths

- **Severity:** High · **Type:** Responsive layout · **Confidence:** Live reproduced
- **Route:** `/payroll/runs/3/`
- **Steps:** Open the run at 768 × 900 and 390 × 844.
- **Actual:** The header retains a large desktop-height action region. At 768 px, more than 400 px of empty space appears between the run title and the action buttons; at 390 px, the three actions sit at the bottom of the first viewport while the title and summary sit at the top. The next content cards are pushed below the viewport, making the first screen look broken and delaying access to the run status.
- **Expected:** At narrower widths, place the actions immediately after the run title in a wrapping stack or compact overflow menu. Keep the run details and progress content directly below the header.
- **Evidence:** Live responsive checks at 768 × 900 and 390 × 844. Desktop layout did not show the blank region.

### BH-10 — Rule-profile creation still appends an inline form instead of opening a dedicated surface

- **Severity:** Medium · **Type:** Interaction/layout consistency · **Confidence:** Live reproduced
- **Route:** `/payroll/setup/`
- **Steps:** Select **Create rule profile**.
- **Actual:** The button expands a full form inline above Payroll configuration and Pay rules. The surrounding content shifts down and the page no longer has a clear cancel/exit boundary for this separate task.
- **Expected:** Open a modal or a dedicated creation page, consistent with the working **Add holiday** and **New component** flows. The form should have a clear close/cancel action and should not reflow the settings screen.
- **Evidence:** Live browser pass. `New component` and `Add holiday` correctly opened dialogs during the same pass.

### BH-11 — The empty components state duplicates the creation action

- **Severity:** Low · **Type:** UI clarity · **Confidence:** Live reproduced
- **Route:** `/payroll/components/` when there are no components
- **Steps:** Open Payroll components in the scenario workspace.
- **Actual:** Both **New component** in the section header and **Create component** in the empty state open the same creation modal. The two same-level primary actions compete for attention.
- **Expected:** Retain the empty-state action as the contextual primary action and reduce the header action to a secondary control, or remove one of them.
- **Evidence:** Live browser pass; both buttons opened the same **Create component** dialog.

## Browser pass still required

When a Browser session is available, use an employer account with a draft run containing at least two employees and another run containing more than 25 statements. Check the following at **1440 px, 768 px, and 390 px**:

1. Complete the remaining employer navigation pages and inspect clipping, overlap, text wrapping, focus visibility, empty states, and sticky controls against `SHIFTLY_PROJECT_DESIGN_SKILL.md`.
2. On a draft payroll run, submit an invalid statutory review, a valid review, and the final review. Confirm that no page reloads, scroll position remains useful, errors are specific, and every count/banner/status changes consistently.
3. Navigate from a pending employee summary row to the correct employee panel, including an employee on a later statement page.
4. Check **Submit for review**, **Recalculate**, manual line, finalize, void, and confirmation paths for clear prerequisites and feedback. Use a disposable test run for state-changing actions.
5. Inspect attendance correction, employee pay profile, payroll setup, components, holidays, payroll creation, employer lists, and employee pay screens at the same widths. Record screenshots and any additional issues in this file.

The live pass covered Payroll overview, employee pay-profile list and a monthly employee profile, components, holidays, payroll setup, payroll-run creation, and the 200-employee draft run. It did not yet execute destructive actions, submit a statutory form, or inspect all Attendance, Timesheets, Reports, and employee-facing pages. Do not treat this file as clearance of those unvisited flows.
