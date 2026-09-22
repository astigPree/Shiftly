# Shiftly user guide

Shiftly connects the complete workforce workflow:

```text
Organization setup → Employees → Schedules → Attendance → Timesheets → Reports → Payroll
```

This guide describes the features currently implemented in the application and the order in which to use them.

## 1. Roles and access

Shiftly has two roles:

### Employer

The employer owns one organization and can:

- configure the organization and employer profile;
- create, invite, edit, activate, and deactivate employees;
- create, edit, view, and cancel shifts;
- monitor organization attendance;
- review, approve, or reject timesheets;
- use reports and export timesheet CSV files;
- configure and operate the Philippine/PHP payroll foundation.

### Employee

An employee belongs to one organization and can:

- view their home dashboard and schedule;
- clock in, start and end breaks, and clock out;
- view their own attendance and timesheets;
- update their personal name and preferred display timezone;
- view finalized payroll statements and printable payslips.

Employees cannot view another employee's records. All employer pages are scoped to the employer's organization.

## 2. Local installation and first launch

The project uses Python 3.9 and Django 4.2 for local development.

### Create the environment

From the project directory:

```cmd
py -3.9 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` before starting the server. A local development file normally contains:

```dotenv
DEBUG=true
SECRET_KEY=use-a-random-development-secret
ALLOWED_HOSTS=localhost,127.0.0.1,[::1]
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

When `DEBUG=true`, the project uses the local `db.sqlite3` file and prints email messages in the terminal. Do not use development settings in production.

### Initialize and run

```cmd
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000/signup/> to create the first employer workspace.

For production, set `DEBUG=false`, a real `SECRET_KEY`, `ALLOWED_HOSTS`, trusted origins as needed, SMTP settings, and a PostgreSQL `DATABASE_URL`. `runserver` is for development only.

## 3. Create the employer workspace

1. Open `/signup/`.
2. Enter the employer email, first name, last name, company/workspace name, password, and an IANA timezone such as `Asia/Manila` or `America/Los_Angeles`.
3. Submit the form. Shiftly creates the user as the organization owner and signs the user in.
4. The organization timezone becomes the default timezone for schedules, attendance, timesheets, reports, and payroll date boundaries.

The organization timezone can be changed in `/settings/?section=organization` until the first shift is created. After that, it is locked to preserve historical records.

## 4. Configure settings

Open `/settings/` as the employer.

### Organization tab

- Change the organization name.
- Review the organization timezone.
- Save organization changes.

### Profile tab

- Change the employer's first and last name.
- Set the employer's preferred timezone for local time display.

An employer's preferred timezone changes the employer's display only. Schedule and attendance records continue to use the organization timezone.

## 5. Home dashboards

After sign-in, `/home/` routes the user to the appropriate dashboard.

### Employer home

The employer dashboard provides a quick operational overview:

- active employee count;
- employees currently working or on break;
- late and absent counts;
- today's attendance table with last activity and actions;
- a **Needs attention** area for incomplete clock-outs and timesheet follow-up.

Use the links on the cards and attendance rows to open the underlying employee, attendance, or timesheet records.

### Employee home

The employee home page shows today's date and shift, the current attendance action, live worked/break time, this week's completed work time, the next shift, recent timesheets, and an employer contact option. The clock controls are available from this page and from `/attendance/my/`.

## 6. Add and invite employees

Open `/employees/` and choose **Add employee**.

Enter:

- a unique employee code within the organization;
- first and last name;
- email address, which is the employee's login identifier;
- an optional job title.

Saving the form creates an active employee and sends a one-time activation invitation. The invitation expires after 72 hours. In local development, the activation URL appears in the terminal because the console email backend is enabled.

The employer can open an employee profile to:

- review account state and invitation state;
- resend an invitation when allowed;
- edit employee details;
- activate or deactivate the employee;
- view that employee's schedules, attendance, and timesheets.

Deactivating an employee prevents sign-in and future employee actions, but preserves existing schedules, attendance, timesheets, and audit history. Records are not hard-deleted through the application.

### Employee activation

1. The employee opens the invitation link.
2. The employee creates and confirms a password.
3. Shiftly activates the account and signs the employee in.
4. The employee can later use `/password-reset/` to request a password reset.

## 7. Schedule shifts

### Create a shift

Open `/schedules/new/`.

For one or many assignments, choose:

- one or more active employees;
- one or more work dates from the calendar;
- start time;
- end time;
- unpaid scheduled break allowance in minutes.

The same time and break settings are applied to every selected employee/date combination. Bulk scheduling supports up to 90 dates and 1,000 employee/date assignments in one submission.

The form shows a review step for bulk submissions. Review it before confirming creation. Shiftly checks duplicate dates, overlapping shifts, inactive employees, and cross-midnight conflicts before saving anything.

### Overnight shifts

If the end time is earlier than the start time, Shiftly treats the end as the next local date. For example, `10:00 PM` to `3:00 AM` is a five-hour overnight shift that remains attributed to its original work date.

Shift times are entered in the organization timezone and stored as timezone-aware UTC timestamps.

### Manage shifts

Open `/schedules/` to filter by date, employee, and status. A shift can be opened at `/schedules/<id>/`.

- Scheduled shifts can be edited before attendance starts.
- Scheduled shifts can be cancelled before attendance starts.
- Cancelled shifts cannot be clocked into.
- Once attendance has begun, the employee, times, and break allowance cannot be changed.
- Each employee can have at most one shift on a local work date, and overlapping shifts are rejected.

Employees see their own upcoming shifts at `/schedules/my/`.

## 8. Daily attendance

### Employer attendance

Open `/attendance/`.

Use the work-date, employee, search, and status filters to monitor the team. The page shows assigned shifts, current state, last activity, exceptions, and follow-up items. Supported states include:

- Scheduled
- Late
- Absent
- Working
- On break
- Completed
- Cancelled
- Open clock-outs / needs follow-up

Open a row to inspect the shift and attendance details. Attendance actions are server-controlled; employers do not edit raw clock events from the page.

### Employee clock workflow

Employees use `/attendance/my/` or the action card on the home page.

1. **Clock in** during the allowed window. The window opens 30 minutes before scheduled start and closes strictly before scheduled end.
2. **Start break** when working.
3. **End break** before resuming work. Multiple non-overlapping breaks are supported.
4. **Clock out** when finished. An open break must be ended first.

The employee can have only one open attendance session. A second shift cannot be clocked into while another session remains open. Clock-in, break, and clock-out buttons require confirmation to reduce accidental actions.

If an employee has not clocked in by scheduled end, the shift becomes absent and cannot be clocked into later. If an employee forgets to clock out, the session remains visibly open for employer follow-up; Shiftly does not invent a clock-out time.

Timers shown in the browser are display-only. Django timestamps and validates every attendance action.

## 9. Timesheets

### How timesheets are created

A completed clock-out creates one timesheet for the shift. Shiftly calculates:

- scheduled minutes;
- worked minutes;
- unpaid break minutes;
- payable minutes (a duration, not a money amount);
- late minutes;
- undertime minutes.

An absent shift has no timesheet. An incomplete session cannot be approved. A calculation inconsistency creates a **Needs Review** record.

### Employer review

Open `/timesheets/`.

Filter by date range, employee, and status. Open a timesheet at `/timesheets/<id>/` to review the scheduled shift, clock events, breaks, totals, variance, and review history.

- **Pending** records can be approved or rejected.
- Rejection requires a comment.
- **Approved** and **Rejected** are terminal decisions in the current release.
- **Needs Review** records cannot be approved until their issue is resolved or explicitly rejected.

Only approved records are payroll-ready. The list supports pagination and quick status filters. The report area also provides CSV export.

### Employee timesheets

Employees use `/timesheets/my/` to view their own history. They can filter by date and status, see monthly worked time and pending count, open a detail page, and review the employer decision. Employees cannot approve, reject, or edit records.

## 10. Reports

Open `/reports/` as the employer. The report area has four views:

### Attendance

Select an organization-local work date, employee, and status. Review assigned, present, late, and absent counts, last activity, overnight indicators, and exceptions.

### Employee hours

Select the date representing a week. Shiftly uses the ISO week from Monday through Sunday and summarizes worked time and completed shifts by employee.

### Timesheets

Filter by inclusive date range, employee, and timesheet status. Review scheduled time, worked time, variance, and status summaries. Use **Export CSV** to download the same filtered timesheet data.

### Activity log

Review organization-scoped audit events such as employee changes, schedule changes, attendance-related events, timesheet decisions, payroll actions, exports, and statement access.

Reports are organization-scoped, paginated, and use the organization timezone for date boundaries and displayed timestamps.

## 11. Payroll foundation

Payroll is available under `/payroll/` for employers and `/payroll/my/` for employees. The current release is a Philippine/PHP hourly-pay foundation. It is not a complete statutory payroll product and does not transfer money.

### Payroll setup order

Complete the readiness checklist on `/payroll/` in this order:

1. **Payroll settings** at `/payroll/setup/`
   - choose weekly, semi-monthly, or monthly frequency;
   - create effective-dated pay rules;
   - configure regular workday minutes, overtime multiplier, rest-day multipliers, night window, and night differential rate;
   - record official source references and reviewer details.
2. **Employee pay profiles** at `/payroll/employees/`
   - configure work location and payroll region;
   - set the employee work timezone or use the organization timezone;
   - record the wage-order reference;
   - confirm the rate was checked, night-differential eligibility, and rank-and-file classification;
   - choose whether the employee participates in payroll;
   - add effective-dated hourly rates at `/payroll/employees/<id>/rates/new/`.
3. **Holiday calendar** at `/payroll/holidays/`
   - add regular or special holidays;
   - enter worked and overtime multipliers;
   - provide the source reference and reviewer;
   - review each holiday before relying on it for finalization.

The readiness checklist requires reviewed payroll settings, configured participating employee profiles/rates, and a configured reviewed holiday calendar before a run can be created.

### Create and review a run

1. Open **Create payroll run** from `/payroll/`.
2. Choose regular or off-cycle, period start, period end, pay date, and (for off-cycle) the finalized parent run.
3. Create the draft.
4. Open the draft run detail page.
5. Recalculate after late timesheet approvals or rule/profile changes.
6. Review employee statements, source timesheets, calculated lines, totals, and exceptions.
7. Resolve exceptions with evidence or add a controlled manual earning, deduction, employer contribution, allowance, reimbursement, or correction line.
8. Submit the run for review.
9. Provide finalization review evidence and finalize it after all blockers are resolved.

Run statuses are **Draft**, **In review**, **Finalized**, and **Voided**. Drafts can be recalculated and adjusted. Finalized and voided runs are immutable. Use a linked off-cycle run for corrections after finalization. Finalization and voiding use confirmation dialogs and retain the actor, timestamp, reason, and audit history.

Only finalized payroll can be exported from `/payroll/runs/<id>/export.csv`.

### Payroll calculations and timezone behavior

The current foundation calculates hourly base pay, configured daily overtime premiums, ordinary-day night differential, and reviewed rest-day/holiday premiums from approved timesheets. Overnight time is split at the employee's local midnight and configured night-window boundaries. Effective rates and rules use the employee-local work date.

For a `10:00 PM` to `3:00 AM` shift, the system keeps the shift on its original local work date while calculating the correct next-day end instant and night-window minutes. An employee's payroll timezone is locked after the first finalized statement to protect historical payroll.

### Employee payroll view

After a run is finalized, the employee can open `/payroll/my/` to see finalized statements, pay dates, gross pay, deductions, net pay, and a payslip link. `/payroll/my/<id>/` shows work time, night-window time, overtime, rate snapshots, itemized lines, employer contributions, and a printable HTML payslip.

### Payroll boundary

The application does **not** currently automate Philippine withholding tax, SSS, PhilHealth, Pag-IBIG, statutory filings, legal/accounting approval, bank files, payment transfers, or direct disbursement. Reviewer names and source references are application review evidence, not legal or accounting sign-off. Validate payroll output with a qualified reviewer before paying employees.

## 12. Timezones and dates

- Organization timezones must be valid IANA names.
- Stored timestamps are timezone-aware UTC instants.
- Schedule work dates are local calendar dates in the organization timezone.
- Reports use inclusive organization-local date boundaries.
- Overnight shifts are attributed to their starting local work date.
- Payroll uses the employee's configured work timezone for local payroll dates; if none is set, it falls back to the organization timezone.
- The employee's preferred timezone controls their local display clock and does not change the organization's schedule timezone.

When an employer and employee are in different regions, configure the employee's payroll work timezone in the employee pay profile. This ensures a shift, overnight split, night differential, and effective rate are evaluated against the employee's actual work location.

## 13. Common issues

### The server says `SECRET_KEY must be set`

Create a project-root `.env`, set `DEBUG=true` for local development, and add a `SECRET_KEY`. The settings loader reads `.env` automatically.

### The server says `DATABASE_URL must be set`

The application is running with `DEBUG=false`. Either use the local development `.env` with `DEBUG=true`, or provide a PostgreSQL `DATABASE_URL` for production.

### An employee cannot see a clock-in button

Check that:

- the employee account is active;
- the employee has an assigned non-cancelled shift;
- the current time is within 30 minutes before start and before scheduled end;
- the employee does not already have an open attendance session;
- the shift has not become absent.

### An employee invitation does not arrive

In local development, read the activation URL in the server terminal. In production, configure the SMTP variables in `.env` and resend the invitation from the employee profile.

### Payroll cannot be finalized

Open the run's exceptions and readiness checklist. Common blockers are missing employee rates or work details, unreviewed rules or holidays, unconfirmed night eligibility, pending or incomplete timesheets, and unresolved premium combinations.

## 14. Route reference

| Area | Employer route | Employee route |
|---|---|---|
| Home | `/home/` | `/home/` |
| Settings/profile | `/settings/` | `/profile/` |
| Employees | `/employees/` | — |
| Schedules | `/schedules/` | `/schedules/my/` |
| Attendance | `/attendance/` | `/attendance/my/` |
| Timesheets | `/timesheets/` | `/timesheets/my/` |
| Reports | `/reports/` and `/reports/timesheets.csv` | — |
| Payroll overview | `/payroll/` | `/payroll/my/` |
| Payroll setup | `/payroll/setup/` | — |
| Pay profiles | `/payroll/employees/` | — |
| Holidays | `/payroll/holidays/` | — |
| Login | `/login/` | `/login/` |
| Signup | `/signup/` | — |
| Password reset | `/password-reset/` | `/password-reset/` |

## 15. Recommended daily operating sequence

### Employer

1. Check the home dashboard and `/attendance/` for late, absent, working, on-break, and missing-clock-out records.
2. Correct future scheduling issues before attendance begins.
3. Open `/timesheets/` and review completed records.
4. Approve valid records and reject invalid records with a comment.
5. Use `/reports/` for weekly hours, status summaries, activity history, and CSV exports.
6. If payroll is enabled, complete readiness checks before creating a run.

### Employee

1. Open Home or `/schedules/my/` and confirm today's shift.
2. Clock in only when the clock-in window is open.
3. Start and end breaks from the attendance action card.
4. Clock out when the shift is complete.
5. Review `/timesheets/my/` for the generated record and employer decision.
6. Review `/payroll/my/` after the employer finalizes a payroll run.

## 16. Current product limits

The current release intentionally does not include recurring schedules, leave management, automatic clock correction, timesheet resubmission, multiple organization owners, employee self-enrollment, full HR records, automated statutory payroll, bank transfers, or complete legal/accounting payroll compliance. These should be treated as future product work rather than current workflows.
