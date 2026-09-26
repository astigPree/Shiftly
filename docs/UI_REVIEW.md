# Browser layout review

Reviewed September 26, 2026 against `SHIFTLY_PROJECT_DESIGN_SKILL.md`.

## Result

Visited the current public, employer, and employee application screens using
Chromium. The authenticated live-server review covered 41 route/state variants
at 320, 390, 768, 1024, 1366, 1440, and 1920 pixels: **287 visits**. All returned
HTTP 200 with no detected document overflow, table-column misalignment,
oversized input controls, or JavaScript errors in the final pass. Five public
screens were also visited at desktop and mobile widths: **10 visits**.

The complete automated suite passed **68 tests**, including seven browser
tests covering empty/populated screens, public account pages, confirmation
dialogs, validation errors, calendar selections, and schedule action menus.
Browser screenshots were also inspected to identify problems that document
overflow measurements alone do not detect.

## Pages covered

`<id>` denotes records belonging to the synthetic review workspace.

| Area | Screens and states |
| --- | --- |
| Public account pages | `/login/`, `/signup/`, `/password-reset/`, `/password-reset/done/`, `/reset/done/`; valid reset-password and valid/invalid invitation screens in the isolated browser tests |
| Employer overview | `/home/`, including populated attendance and its displayed update time |
| Employees | `/employees/`, pagination, `/employees/new/`, `/employees/<id>/`, uninvited employee details, edit, schedules, attendance, and timesheet tabs |
| Schedules | `/schedules/`, `/schedules/new/`, shift detail/edit; multiple employees and dates, overnight preview, batch review, row actions, and cancellation confirmation |
| Attendance | `/attendance/`, `/attendance/my/`; clock-in, start-break, end-break, and clock-out confirmation/cancellation |
| Timesheets | Employer list/detail/review, `/timesheets/my/`, employee detail; empty, pending, and approved records |
| Payroll | `/payroll/`, `/payroll/setup/`, `/payroll/employees/`, employee pay profile, new hourly rate, holiday list/edit, new run, draft/finalized run, `/payroll/my/`, and employee payslip |
| Payroll interactions | Expanded rule-profile form, invalid submission, finalize/void confirmations, assignment form layout, and draft adjustment inputs |
| Reports | Attendance, employee hours, timesheet, and activity tabs with populated date ranges |
| Account preferences | Employer `/settings/` and employee `/profile/`, including different company and personal timezones |

Action endpoints are exercised through their page controls. CSV downloads and
the framework's Django administration screens are not counted as custom UI
pages. The live payroll employee list's out-of-range page request also checked
its fallback behavior; it is not evidence of a populated second payroll page.

## Changes made

| Finding | Fix |
| --- | --- |
| Pay-profile tables widened the whole page on smaller screens | Allowed grid children to shrink; wide tables remain inside their horizontal scroll container |
| Bulk-assignment heading displaced the fields | Placed the heading and validation message across the full grid row |
| Employee deactivation button overflowed its mobile card | Removed the extra left margin on full-width mobile controls |
| Payroll empty-state title was squeezed into an icon-sized column | Scoped the icon/text/action grid to payroll-run list messages; plain messages use a full text column |
| Draft-payroll inputs became excessively tall on mobile | Reset the flex basis when the form stacks vertically |
| Form controls stretched to match adjacent help text | Aligned field contents to the top |
| Mobile payroll notices and actions wrapped awkwardly | Stacked notice text and allowed action rows to wrap |
| Payroll settings had a large always-expanded profile creation form | Added an accessible disclosure; it opens automatically for validation errors or when no profiles exist |
| Employee Home summary cards inherited an unrelated flex layout | Restored the intended grid and constrained mobile heading/button sizing |
| Mobile company/personal clocks truncated their labels | Gave employee clocks more width and retained their date/UTC offset context |
| Pending status used the scheduled-state color | Applied the design guide's amber pending treatment |
| Overview update time did not use the organization timezone | Applied the organization timezone before formatting it |
| Mobile timesheet actions reverted to plain links | Reused the shared outlined action-button treatment with 44px mobile targets |
| The final schedule row's action menu was clipped by the table | Positioned the menu in the browser's popover layer, with a fixed-position fallback; added outside-click, Escape, and focus dismissal |

## Data and evidence

With the user's approval, a new workspace named
`Shiftly UI QA 20260926153411` was created through signup on the running local
server. Only this workspace received synthetic employees, shifts, timesheets,
payroll records, and a holiday. Existing company records were not changed.
The temporary workspace remains available locally.

Automated state-changing scenarios run against a separate Django test database.
No invitation email was sent from the live review workspace. Generated
credentials and screenshots are ignored local artifacts, not source files.

- Live screenshots and measurements: `.artifacts/ui/live/`
- Live review results: `.artifacts/ui/live/audit-results-320-390-768-1024-1366-1440-1920.json`
- Public live checks: `.artifacts/ui/live/results.json`
- Isolated browser screenshots: `.artifacts/ui/`
- Complete test log: `.artifacts/ui-final-tests.log`
- Browser regression source: `tests/test_browser.py`

## Repeat the automated checks

Install the project dependencies, Playwright, and Chromium in a development
environment, then run from the project root in PowerShell:

```powershell
$env:RUN_BROWSER_TESTS = '1'
python manage.py test tests --settings=config.test_settings --noinput
```

For the browser scenarios alone:

```powershell
python manage.py test tests.test_browser --settings=config.test_settings --noinput
```

This review used Chromium. Safari, Firefox, and physical-device behavior have
not been verified. The results cover the listed states and viewport sizes;
they do not replace review of future pages or unusual content. Wider financial
tables intentionally scroll within their cards on small screens.
