# Shiftly full application simulation

**Purpose:** run the employer experience from sign-in through a reviewed payroll
run using the seeded demo workspace. This is a test workflow. Use synthetic
values only and do not finalize or pay a real employee from this checklist.

**Primary account:** `max@gmail.com`  
**Workspace:** `makietech2`  
**Timezone:** `Asia/Manila`  
**Currency:** PHP  
**Browser start URL:** `http://127.0.0.1:8000/login/`

## Latest walkthrough status — 2026-10-09

The payroll and modal fixes from `PAYROLL_UI_WALKTHROUGH_FIX_IMPLEMENTATION_PLAN.md`
are implemented. Automated verification passed with `manage.py check` and 128
Django tests (8 expected skips). A live local-browser pass at 1024 × 668 also
confirmed that changing the payroll period refreshes the preview, component and
holiday modal actions remain reachable, and Sync settings/Add terminal dialogs
keep their footer actions inside the viewport. The full 320/390/mobile viewport
matrix and a live successful individual statutory-save walkthrough remain
acceptance work; do not treat this status block as completion of those checks.

> Use the password already stored in `.secrets/email_password.txt`. Do not copy
> the password into this document, a screenshot, or a commit.

## Test data

Use the existing seeded employees when they are present:

| Employee | Code | Basis | Test rate |
| --- | --- | --- | ---: |
| Part-time Seed Employee | `PT-SEED-001` | Hourly | PHP 120.00/hour |
| Regular Seed Employee | `REG-SEED-001` | Hourly | PHP 150.00/hour |

Use this deterministic payroll period throughout the run:

- **Run type:** Regular
- **Scope:** Selected employees (the two employees above)
- **Period:** 01/09/2026 through 30/09/2026
- **Pay date:** 05/10/2026
- **Evidence label:** `TEST-ONLY Sep 2026 payroll simulation`

If the employees or rates are missing, create them in the employee and pay
profile steps before continuing. If a payroll run already exists for this exact
period, use it only when it is still a draft; otherwise create a new test run.

## Prerequisites

- Start from the Shiftly project directory with the demo database loaded.
- Run `python manage.py migrate` after pulling new migrations.
- Start the local server with `python manage.py runserver 127.0.0.1:8000`.
- Keep the browser in one tab for the main flow. Use a second tab only for the
  optional stale-data test.
- If the login page is unavailable, check `/health/` first and confirm the
  server is listening on port 8000.

## How to use this guide

- Complete the checkboxes in order.
- After each save, verify the expected result before moving on.
- Use `Refresh` only when the page tells you to; normal saves should show a
  success message and keep you at the relevant section.
- Do not enter government ID numbers. The statutory values below are synthetic
  workflow data, not legal contribution calculations.
- If a button is disabled, open the readiness or exception link shown beside it
  instead of bypassing the guard.

## 1. Sign in and confirm the workspace

- [/] Start the server and open `http://127.0.0.1:8000/login/`.
- [/] Enter `max@gmail.com` and the saved demo password.
- [/] Select **Sign in**.
- [/] Confirm the employer navigation is visible: **Overview, Employees,
  Schedules, Attendance, Timesheets, Payroll, Reports, Settings**.
- [/] Confirm the workspace header says **makietech2** and the timezone is
  **Asia/Manila**.

**Expected result:** the employer dashboard opens at `/home/`. No employee
clock-in controls should be shown in the employer navigation.

## 2. Review the dashboard

- [/] Open `/home/`.
- [/] Check the active employee count, today’s attendance cards, pending
  timesheets, and attention items.
- [/] Open each attention link once. Return with the page breadcrumb or the
  browser Back button.

**Expected result:** dashboard cards link to the matching filtered list. Empty
states explain the next action; they are not errors.

## 3. Verify workspace settings

Open `/settings/`.

- [/] Open the **Organization** section and confirm the workspace name and
  timezone. Do not change the timezone after shifts exist; historical attendance
  uses it.
- [/] Open the **Profile** section and confirm the signed-in employer name and
  email.
- [/] Save an unchanged section once and verify the success feedback appears
  without losing the active section.

**Expected result:** organization settings and personal profile are separate,
and the login email is displayed as read-only.

## 4. Verify employees and payroll profiles

The **Employees** area holds personal, account, schedule, attendance, and
timesheet information. Payroll work details, compensation, components, period
inputs, rule assignment, and payroll audit history are on the separate
**Payroll → Pay profiles** area.

### Verify the employee record

Open `/employees/`.


- [/] Search for `PT-SEED-001` and open its employee profile.
- [/] Confirm the employee is **Active**, the code is `PT-SEED-001`, and the
  work email and job title are correct.
- [/] Use **Schedules**, **Attendance**, and **Timesheets** to confirm those
  record pages load. The standard employee profile does **not** show payroll
  rates or payroll work details.

### Verify the payroll profile

Open `/payroll/employees/` and search for `PT-SEED-001`.

- [/] In the **Employee readiness** table, confirm **Current compensation** is
  `PHP 120.00 / hourly` and has an effective date.
- [ ] Select **Manage pay** for `PT-SEED-001`. This opens
  `/payroll/employees/<employee-id>/`.
- [/] Review the **Work details** section. Confirm the work location, payroll
  region, work timezone, and rest day are set.
- [/] Scroll to **Compensation history** and confirm the effective date and
  hourly amount.
- [/] Scroll to **Payroll rule profile** and confirm an effective payroll rule profile is
  assigned or inherited from the organization default.
- [/] Continue through **Reviewed period inputs**, **Recurring pay components**,
  and **Audit history** to confirm their loaded or empty states are understandable.
- [/] Repeat these payroll-profile checks for `REG-SEED-001`; the table and
  compensation history should show `PHP 150.00 / hourly`.

If payroll information is missing, use the payroll-profile actions:

- **Edit employee details:** `/employees/<employee-id>/edit/`
- **Manage payroll details:** `/payroll/employees/<employee-id>/`
- **Add compensation:** choose **Add compensation** in the Compensation section.
- **Assign a rule override:** choose **Assign override** in the Rule assignment
  section. Use a date that does not overlap an existing employee override.

**Expected result:** each selected employee shows a complete payroll profile or
an explicit readiness warning that identifies the missing item.

> **Where statutory review happens:** SSS, PhilHealth, Pag-IBIG, and withholding
> tax amounts are not entered in an employee payroll profile. After creating a
> payroll draft, complete them in that run's **Statutory review** workspace in
> [Step 11](#11-fast-statutory-review-for-the-whole-run).

### Optional employee lifecycle branch

Use this branch only when a fresh employee is required; otherwise keep the
existing seeded employees so the payroll totals remain reproducible.

- [/] Open `/employees/new/`.
- [/] Create a synthetic employee such as `Simulation Employee` with code
  `SIM-001`, a work email inbox you control, and a job title. The employee form
  creates an **active** employee and sends an activation link; it does not
  collect payroll status, pay basis, or compensation.
- [/] Save and confirm the employee appears in `/employees/`.
- [/] Open the employee profile and verify **Edit**, **Schedules**, **Attendance**,
  and **Timesheets** links.
- [/] Open `/payroll/employees/`, search for `SIM-001`, and choose **Manage
  pay**. Add the synthetic employee's work details and a dated hourly
  compensation of PHP 100.00 there if payroll setup is part of the test.
- [/] Use **Send activation link** only if you intentionally test email
  invitation handling. Never put a password in the employee record.
- [/] Toggle the status only on the synthetic employee, then restore it to
  active before creating payroll.

## 5. Verify payroll setup

Open `/payroll/setup/`.

- [ ] In **Payroll configuration**, confirm currency is PHP, frequency is
  Monthly, and timezone is Asia/Manila.
- [ ] Confirm the active rule version has an effective date covering
  01/09/2026–30/09/2026.
- [ ] Confirm the test rules: 8 regular hours, 1.250 ordinary overtime, 1.300
  rest-day work, 1.690 rest-day overtime, and 10.00% night differential.
- [ ] Confirm the night window is 10:00 PM–06:00 AM.
- [ ] Confirm a source reference and reviewer are recorded.
- [ ] Save only after reviewing the confirmation prompt.

**Expected result:** the setup page reports the rules as reviewed. Do not create
an overlapping rule version; a new version must start after the current one.

Open `/payroll/components/`.

- [ ] Confirm shared components are present or create one test component such as
  `MEAL` / `Meal allowance` / **Earning** / **Per payroll period**.
- [ ] Save and verify the component appears in the table.
- [ ] Open the component edit action and close it without changing data.

Open `/payroll/holidays/`.

- [ ] Confirm the 2026 holiday calendar has the reviewed holidays needed by the
  test period, or add a clearly synthetic test holiday.
- [ ] Save and verify the holiday appears once in the calendar.

## 6. Create or inspect shifts

Open `/schedules/`.

- [ ] Filter to September 2026.
- [ ] Confirm at least one shift exists for each seeded employee.
- [ ] If a shift is missing, open `/schedules/new/` and create a test shift:
  - Employee: one seeded employee
  - Date: `03/09/2026`
  - Start: `09:00`
  - End: `18:00`
  - Timezone: `Asia/Manila`
  - Break: 60 minutes, if the form provides a break field
- [ ] Repeat for `05/09/2026` and `07/09/2026` only if the payroll period needs
  more approved attendance examples.
- [ ] Open a shift detail page and verify the scheduled times before recording
  attendance.

**Expected result:** the schedule list shows the employee, local date, local
start/end, and a clear status. Editing a scheduled shift does not rewrite an
already recorded attendance punch.

- [ ] Open a shift’s detail page and test **Edit** with a small time change
  before attendance starts; save and verify the list updates.
- [ ] If you created a shift only for a temporary test, use **Cancel shift** and
  confirm the cancellation dialog. A cancelled shift should no longer invite a
  clock-in.

## 7. Record and correct attendance

Use the employee’s attendance experience when available. For employer review,
open `/attendance/`.

- [ ] Filter to `03/09/2026` and confirm the expected shift is listed.
- [ ] Record a test session using the employee action or the shift’s
  **Record attendance** page.
- [ ] Use a clock-in around `09:00` and clock-out around `18:00` in
  Asia/Manila.
- [ ] Start and end a break if the shift has one.
- [ ] Confirm the attendance row changes to **Completed**.
- [ ] Open `/timesheets/` and locate the generated timesheet.
- [ ] Review the payable minutes and approve the timesheet.

To test employer control over a missed or incorrect punch:

- [ ] Open the attendance row’s **Edit attendance** action. The URL is
  `/attendance/sessions/<session-id>/correct/`.
- [ ] Enter corrected local clock-in/clock-out values, optional break intervals,
  and a required reason such as `TEST-ONLY corrected punch for Sep 2026`.
- [ ] Confirm the save dialog only after checking the dates. An overnight shift
  may end on the following local date.
- [ ] Verify the original punch remains in the audit history and the effective
  timesheet returns to review.
- [ ] Re-approve the corrected timesheet.

**Expected result:** local dates are displayed consistently, the correction is
audited, and the payroll input is recalculated only from the effective reviewed
attendance.

## 8. Review timesheets and reports

- [ ] On `/timesheets/`, filter by **Needs review** and **Approved** once.
- [ ] Open a timesheet detail page, check the source attendance, and verify the
  approve/reject action.
- [ ] If rejecting a test timesheet, provide a reason, correct it, and approve
  it again.
- [ ] Open `/reports/` and filter to September 2026.
- [ ] Review the timesheet report totals.
- [ ] Use **Export CSV** and confirm the downloaded report matches the visible
  filter.

**Expected result:** only approved attendance is eligible for payroll
calculation, and the report/export respects the selected date range.

## 9. Create the payroll draft

Open `/payroll/`, then select **Create payroll run**. The form is also
available at `/payroll/runs/new/`.

Enter:

| Field | Value |
| --- | --- |
| Run type | Regular |
| Scope mode | Selected employees |
| Employees | `PT-SEED-001`, `REG-SEED-001` |
| Period start | `01/09/2026` |
| Period end | `30/09/2026` |
| Pay date | `05/10/2026` |
| Parent run | blank |

- [ ] Confirm the live preview shows Monthly, Sep 1–30, 2026, pay date Oct 5,
  Asia/Manila, PHP, and 2 employees.
- [ ] Confirm readiness shows payroll settings, employee profiles, holiday
  calendar, and attendance sources.
- [ ] Select **Create draft**.
- [ ] On the draft page, select **Recalculate**.

**Expected result:** a draft payroll run is created with statements for both
employees. Review the exceptions before trying to submit.

## 10. Review calculated statements

On `/payroll/runs/<run-id>/`:

- [ ] Confirm the period, pay date, employee count, gross pay, deductions, and
  net pay.
- [ ] Open **Employee statements → View details** for both employees.
- [ ] Verify basic hourly pay, approved timesheet source rows, and any component
  lines.
- [ ] Close the statement modal/page and confirm the run remains at the same
  scroll position where possible.
- [ ] Open **Exceptions**. Resolve every blocking exception before continuing.

**Expected result:** the run reports `0 blocking` exceptions. Monthly or missing
work-data blockers must be fixed in the employee profile or period inputs; do
not hide them with a manual adjustment.

## 11. Fast statutory review for the whole run

The current release does not calculate SSS, PhilHealth, Pag-IBIG, or BIR
withholding tables automatically. It records reviewed decisions and amounts.
Use the run’s **Statutory review** workspace instead of filling one employee at
a time.

- [ ] Open the **Statutory review** tab on the run.
- [ ] If the workspace is empty, select **Generate assessments**.
- [ ] Filter by agency or status to see the rows needing attention.
- [ ] Use **Select visible** or **Select all matching**.
- [ ] Select **Review selected**.
- [ ] In the modal, choose the registration status, shared employee/employer
  treatment, source reference, and review note.
- [ ] Use a source reference such as `TEST-ONLY Sep 2026 payroll simulation`.
- [ ] Confirm the review. The workspace should update without a full page
  reload and show the reviewed count.
- [ ] Repeat for SSS, PhilHealth, Pag-IBIG, and Withholding tax until every
  employee has `4 of 4 reviewed`.

For a zero or exempt test item, explicitly select the corresponding treatment
and explain it in the review reason. A missing registration number is not an
automatic exemption. Pending registration also requires a follow-up note.

### Fallback: seed manual lines only when no reviewed amount exists

Use **Add line** for a one-off or for this synthetic fallback. Add each line
through the modal, using the exact employee, kind, label, amount, effective date
`01/09/2026`, and reason `TEST-ONLY Sep 2026 payroll simulation`.

| Employee | Kind | Line item | Amount |
| --- | --- | --- | ---: |
| Part-time Seed Employee | Employee deduction / withholding | SSS employee - Sep 2026 | 300.00 |
| Part-time Seed Employee | Employee deduction / withholding | PhilHealth employee - Sep 2026 | 150.00 |
| Part-time Seed Employee | Employer contribution | SSS employer - Sep 2026 | 600.00 |
| Part-time Seed Employee | Employer contribution | PhilHealth employer - Sep 2026 | 150.00 |
| Part-time Seed Employee | Employee deduction / withholding | Pag-IBIG employee - Sep 2026 | 100.00 |
| Part-time Seed Employee | Employer contribution | Pag-IBIG employer - Sep 2026 | 100.00 |
| Regular Seed Employee | Employee deduction / withholding | SSS employee - Sep 2026 | 1,000.00 |
| Regular Seed Employee | Employer contribution | SSS employer - Sep 2026 | 2,000.00 |
| Regular Seed Employee | Employee deduction / withholding | PhilHealth employee - Sep 2026 | 500.00 |
| Regular Seed Employee | Employer contribution | PhilHealth employer - Sep 2026 | 500.00 |
| Regular Seed Employee | Employee deduction / withholding | Pag-IBIG employee - Sep 2026 | 100.00 |
| Regular Seed Employee | Employer contribution | Pag-IBIG employer - Sep 2026 | 100.00 |
| Regular Seed Employee | Employee deduction / withholding | Withholding tax - Sep 2026 | 500.00 |

After adding lines:

- [ ] Confirm the line count increases and the employee statement reflects the
  employee deduction or employer share in the correct column.
- [ ] Recalculate the draft.
- [ ] Generate or refresh statutory assessments.
- [ ] Bulk-review the matching agency rows.

Do not use these synthetic amounts for a real filing. The employer remains
responsible for the correct legal calculation and reviewer evidence.

## 12. Test validation and stale-data protection (optional)

- [ ] Open the statutory workspace in two browser tabs.
- [ ] In tab A, select a group for review but do not confirm it.
- [ ] In tab B, add a test manual line or recalculate the draft.
- [ ] Return to tab A and confirm the old selection.
- [ ] Verify the app rejects the stale review and asks you to refresh.
- [ ] Refresh, reselect the current rows, and save again.

**Expected result:** the app does not silently overwrite newer payroll data.

## 13. Submit, review, and finalize

- [ ] Confirm the run shows no payroll-blocking exceptions.
- [ ] Confirm every employee shows `4 of 4 reviewed` in statutory review.
- [ ] Confirm the deductions and net pay match the itemized statements.
- [ ] Select **Submit for review** and confirm the review prompt.
- [ ] On the review state, inspect employee statements, statutory evidence, and
  audit history.
- [ ] If the run needs correction, use **Return to draft** while it is in
  review, make the correction, recalculate, and repeat the reviews.
- [ ] When the test review is complete, select **Finalize** and confirm the
  finalization prompt only if you intend to keep the test record.
- [ ] Open **Export CSV** from the finalized run and verify the exported totals.

**Expected result:** finalization locks the payroll snapshot. Finalized data and
scope cannot be edited; later corrections require a linked off-cycle run.

## 14. Employee self-service check

If an employee login is available:

- [ ] Sign out from the employer account at `/logout/`.
- [ ] Sign in with the invited employee account.
- [ ] Open `/attendance/my/`, `/schedules/my/`, `/timesheets/my/`, and
  `/payroll/my/`.
- [ ] Confirm the employee can view assigned work and finalized statements but
  cannot access employer payroll setup, statutory review, or other employees.
- [ ] Sign out and sign back in as `max@gmail.com` before further employer work.

## 15. Clean up a test run

- [ ] If the run is still a draft and should not be retained, select **Void
  draft** and confirm the reason.
- [ ] Do not delete audit records or edit the database directly.
- [ ] Keep screenshots, run ID, validation text, and exported CSV only if they
  contain synthetic data.

## Completion checklist

- [ ] Logged in as `max@gmail.com` and confirmed `makietech2` / Asia-Manila.
- [ ] Verified two employees, rates, work details, and rule assignments.
- [ ] Verified setup, components, and holidays.
- [ ] Created or reviewed shifts and recorded attendance.
- [ ] Corrected one test punch and re-approved its timesheet.
- [ ] Reviewed timesheets and exported a report.
- [ ] Created a selected-employee September payroll draft.
- [ ] Recalculated and resolved all payroll exceptions.
- [ ] Generated and bulk-reviewed all four statutory items per employee.
- [ ] Submitted the run for review and inspected audit history.
- [ ] Finalized only when intentionally retaining the synthetic test run, or
  voided the draft for cleanup.

## Evidence to record

For each failed step, record the URL, run/employee/session ID, exact visible
error, whether a network request was sent, and a screenshot. Never record real
government numbers, bank credentials, or the demo password in the evidence.
