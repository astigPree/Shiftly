# Shiftly MVP Acceptance Criteria and Operating Rules

## Authority and scope

This document resolves the product decisions left open by the Shiftly project documents. It is the authoritative source for MVP behavior and acceptance. The Project Description defines product scope, the Tech Stack defines implementation constraints, and the Project Design Skill guides presentation. If a design example suggests a feature outside this document's MVP boundary, defer that feature.

The MVP is a single-owner-per-organization attendance and timesheet product. It records attendance and produces reviewable work-minute records; it does not calculate wages or payroll.

## Accounts and organizations

- An employer can sign up with an email and password. Successful signup creates one organization and makes that user its owner.
- An organization has exactly one employer owner in MVP. Employer users and employee users each belong to exactly one organization and have exactly one role.
- The employer creates employee records and sends an email invitation with a one-time password setup link that expires after 72 hours. An employee cannot self-select an organization.
- Use Django's password reset flow by email. A deactivated employee cannot log in, but their employee profile, shifts, attendance, timesheets, and audit history remain.
- Users and organizations are not hard-deleted through the application when records exist. Employer account deletion and organization transfer are outside MVP.
- Employee email is required and unique across Shiftly because it is the login identifier. Employee code is unique within its organization.

## Organization timezone and date handling

- Require an IANA timezone when the employer creates the organization.
- Store timestamps as timezone-aware instants in UTC. Render schedules, attendance, reports, and CSV timestamps in the organization's timezone.
- The employer may change the organization timezone only until the first shift is created. After that, timezone changes are locked in MVP so historical dates and schedules keep a stable interpretation.
- Report date filters use dates in the organization's timezone, with inclusive start and end dates.

## Shifts and scheduling

- MVP schedules are one-off shifts assigned to one employee; recurring schedules, templates, and split shifts are out of scope.
- An employee may have at most one shift on a local work date.
- Two shifts assigned to the same employee may not overlap, including shifts whose local work dates differ because one shift ends the following day.
- A shift is entered as a local work date, start time, end time, and unpaid scheduled break allowance. If the end time is earlier than the start time, it is on the following local date. Equal start and end times are invalid.
- The scheduled break allowance is a nonnegative whole number of minutes and cannot exceed the shift's gross scheduled duration.
- Convert local start and end to timezone-aware UTC instants for storage. Calculate elapsed scheduled duration from those instants.
- Reject nonexistent or ambiguous local start/end times caused by daylight-saving transitions with a clear validation message. A shift whose endpoints are valid may span a timezone transition; its scheduled duration is actual elapsed time.
- A cancelled shift cannot be clocked into. Once attendance has begun, the employer cannot edit the shift's scheduled times or employee assignment. The employer may cancel only before attendance begins.

## Clock-in, attendance states, and breaks

- An employee can clock only into their own assigned, active shift. Unscheduled clocking is not supported.
- Clock-in is allowed from 30 minutes before scheduled start until strictly before scheduled end. An early clock-in is recorded as actual work. Clock-in at or after scheduled end is rejected.
- There is no lateness grace period in MVP. Any clock-in timestamp after scheduled start is late; late minutes are whole elapsed minutes, rounded down. Late minutes remain on the timesheet after the employee's live state changes to Working or On Break.
- If an employee has not clocked in by scheduled end, mark the shift Absent. Absence is derived from the schedule and current time; a shift cannot be clocked into after it becomes absent.
- The employee may clock out any time after clock-in, including after scheduled end. Actual elapsed work continues until clock-out; overtime rates or premium rules are not calculated.
- Employees may take multiple non-overlapping breaks. They may start a break only while working, and must end an open break before clock-out.
- All recorded breaks are unpaid and are subtracted from actual work duration. The shift's scheduled break allowance is an informational planned unpaid allowance used in the scheduled-minute baseline; it does not cap actual break time. Overbreak alerts/automation are outside MVP.
- Live timers in the browser are display-only. Django timestamps, validates state transitions, and calculates every stored total.

### Attendance state presentation

- Before the scheduled start: Scheduled or Not Clocked In, depending on the page context.
- From scheduled start until clock-in: Late while before scheduled end; Absent from scheduled end onward.
- After clock-in: Working, or On Break while a break is open. Keep late minutes on the record rather than replacing the live state with Late.
- After clock-out: Completed.
- If the scheduled end passes without clock-out, keep the session visibly flagged as Missing Clock Out while preserving its Working/On Break state. Do not synthesize a clock-out time.

## Time and timesheet calculations

Keep event timestamps at full stored precision. Derive whole-minute fields by summing exact durations first, then flooring once to a whole minute:

- Scheduled minutes = elapsed scheduled shift duration minus the scheduled unpaid break allowance, floored at zero.
- Break minutes = the sum of completed break durations.
- Worked minutes = clock-out minus clock-in minus all completed break durations, floored at zero.
- Payable minutes = worked minutes. This is a recorded duration, not a wage or payroll calculation.
- Late minutes = time from scheduled start to clock-in when clock-in is later than scheduled start; floor the result.
- Undertime minutes = time from clock-out to scheduled end when clock-out is earlier than scheduled end; floor the result. It is measured against scheduled end and is independent of lateness.
- Do not round each break separately before summing. Store all calculated fields as integer minutes.

A completed shift creates exactly one Pending timesheet after clock-out. An absent shift has no timesheet. A session without clock-out has no final timesheet and cannot be approved. Keep it visibly flagged for employer follow-up; manual clock corrections and automatic clock-out are outside MVP.

Use Needs Review when a completed record fails a calculation or consistency check. A Needs Review record cannot be approved. The employer may reject it with a required comment; resolution/correction is outside MVP.

## Timesheet review and employee hour summaries

- Pending timesheets may be approved or rejected only by the employer owner of the organization.
- Rejection requires a comment. Record reviewer, decision, comment, and review timestamp.
- Approved and Rejected are terminal in MVP. Employees and employers cannot edit attendance events or recalculate a reviewed timesheet. Resubmission and timesheet corrections are future work.
- Only Approved records are considered payroll-ready. Reports and exports include a timesheet status so pending, rejected, and needs-review records remain distinguishable.
- Employee weekly hours sum worked minutes for all completed shifts whose local work date falls in the ISO week (Monday through Sunday), regardless of approval status. Display each timesheet's review state separately. Incomplete sessions are not included.

## Reports and CSV

- Daily attendance is grouped by the shift's local work date and includes every shift scheduled on the selected organization-local date, including absent shifts.
- Weekly employee hours use ISO weeks, Monday 00:00 through the next Monday 00:00 in the organization timezone, and attribute an overnight shift to its local work date.
- Timesheet status reports may filter by inclusive local date range, employee, and status.
- CSV export uses the active report filters and organization authorization. Include a header row and these columns: organization name, employee code, employee name, local shift date, scheduled start, scheduled end, clock-in, clock-out, break minutes, scheduled minutes, worked minutes, payable minutes, late minutes, undertime minutes, attendance status, timesheet status, reviewed by, and reviewed at.
- Format timestamps as ISO 8601 with the organization timezone offset. Escape untrusted text safely, including formula-leading values. Do not export another organization's data.

## Audit and records

- Keep clock-in, clock-out, break start, and break end timestamps as the attendance record; they are created by the employee's validated clock actions and cannot be edited in MVP.
- Record organization creation, employee create/update/deactivation, shift create/update/cancellation, and timesheet approval/rejection in append-only audit history with actor, action, target, timestamp, and a concise change summary.
- Do not put passwords, invitation/reset tokens, or unnecessary sensitive data in audit metadata.
- Corrections, overrides, and a dedicated audit-management UI are outside MVP. Show relevant timesheet review history on timesheet detail.

## End-to-end acceptance scenarios

- Employer signup creates one organization with the selected timezone; an employee invitation is tied to that organization and cannot be used to enter another one.
- An overnight shift displays and reports against its local work date, with correct UTC instants and elapsed duration.
- Invalid daylight-saving local times are rejected before saving a shift.
- Clock-in before the 30-minute window, at/after scheduled end, or without an assigned active shift is rejected; an allowed early clock-in is included in actual work.
- Late, absent, break, completed, and missing-clock-out states follow the rules above.
- Repeated or concurrent clock actions cannot create duplicate sessions, overlapping breaks, duplicate timesheets, or invalid transitions.
- A completed shift's scheduled, break, worked, payable, late, and undertime minutes match the defined formulas, including seconds and fractional-minute boundaries.
- A missing clock-out stays visibly unresolved and cannot produce an approved timesheet.
- Approvals/rejections are organization-scoped and auditable; rejection requires a comment; reviewed records cannot be silently changed.
- Weekly employee hours and daily attendance use organization-local boundaries; CSV rows, filters, and totals match the report and remain organization-scoped.
- Desktop employer pages and mobile employee clocking are usable with keyboard navigation, visible focus, labels, and text status indicators.
