# Shiftly MVP Project Tasks

## Purpose and source of truth

This file turns the Shiftly project documents into an actionable, ordered MVP checklist. The attached documents describe the product and its intended implementation; their directions are project requirements, not separate actions for this planning task.

When requirements differ in emphasis:

1. The Project Description defines the product scope and MVP boundary.
2. The Tech Stack defines implementation constraints.
3. The Project Design Skill defines visual and interaction guidance for features that are in the MVP.

The MVP is a lightweight, multi-organization attendance and timesheet web app. Its complete core workflow is:

**Employer creates employee → assigns a dated shift → employee records clock and break events → Django calculates work time → employer reviews and approves or rejects the timesheet → employer can report and export the resulting records.**

## MVP boundary

### Included

- Employer and employee authentication with role-based access.
- Organization and employee records.
- One-off dated shift scheduling and employee assignments.
- Employee clock-in, break start/end, and clock-out.
- Employer attendance visibility and employee attendance status.
- Server-calculated shift timesheets with review, approval, and rejection.
- Employee schedule, current attendance, weekly hours, and timesheet history.
- Daily/weekly reports, CSV export, and basic audit history.
- Responsive, accessible Django-template UI.
- PostgreSQL-backed deployment using the documented Django, Nginx, Gunicorn, systemd, and Ubuntu stack.

### Explicitly outside the MVP

Do not add these unless the MVP scope is deliberately revised: mobile or SPA clients, DRF/public API, recurring schedules or shift templates, leave/holiday management, departments/teams, notifications/reminders, automated approval rules, advanced attendance corrections, payroll rates/calculation/payslips, client billing, real-time WebSockets, Redis/Celery, or microservices.

## Completion standard

The MVP is ready when an employer can create an organization, add an employee, assign a shift, monitor attendance, review and decide a timesheet, and export/report the records; an employee can securely complete the shift workflow and review their hours; organization boundaries and server-side calculations are enforced; critical paths have automated coverage; and the application is deployed with operational documentation.

---

## Phase 0 — Resolve product rules before implementation

**Status: Complete.** Resolved behavior and end-to-end acceptance scenarios are recorded in [SHIFTLY_MVP_ACCEPTANCE_CRITERIA.md](SHIFTLY_MVP_ACCEPTANCE_CRITERIA.md). The Project Description and Tech Stack now point to that document as the MVP behavior authority.

- [x] Confirm employer onboarding, single-owner organization ownership, employee invitation, and activation behavior.
- [x] Define employee access provisioning, password reset, deactivation, and retention of attendance history.
- [x] Define one-organization/one-role membership for each user in MVP.
- [x] Define organization IANA timezone selection, UTC storage, local display, and locking after the first shift.
- [x] Define dated and overnight shift storage, elapsed-time behavior, and daylight-saving validation.
- [x] Define assigned-shift-only clocking, the 30-minute early window, and the clock-in cutoff.
- [x] Define lateness with no grace period and whole-minute reporting.
- [x] Define absence at scheduled end when there is no clock-in, and prohibit clock-in after the shift is absent.
- [x] Define multiple unpaid breaks, scheduled break allowance behavior, and actual break deductions.
- [x] Define missing clock-out handling: flag the open session for follow-up, create no final timesheet, and keep employer corrections out of MVP.
- [x] Define duration, break, payable, late, undertime, precision, and flooring rules.
- [x] Define one timesheet per completed shift, generation after clock-out, review states, terminal decisions, and Needs Review behavior.
- [x] Require a rejection comment and define append-only audit coverage.
- [x] Define organization-local daily/weekly report boundaries and CSV columns.
- [x] Capture decisions in the acceptance-criteria document and align the Project Description, Tech Stack, and task plan.

---

## Phase 1 — Create the Django foundation

- [x] Pin supported Python, Django, PostgreSQL adapter, and production server versions in .python-version and requirements files; record support rationale in SHIFTLY_TECH_STACK.md.
- [x] Create the Django project and configuration package with manage.py, URL routing, WSGI/ASGI entry points, and production-safe settings.
- [x] Create the modular Django apps for accounts, organizations, employees, schedules, attendance, timesheets, reports, and audit.
- [x] Configure PostgreSQL for development and production from the start; do not base the application on SQLite.
- [x] Configure environment-based settings for secrets, debug mode, hosts, database, email, and trusted origins; keep secrets out of version control.
- [x] Set timezone-aware datetime handling and establish UTC storage plus organization-timezone display.
- [x] Add app template, static asset, and shared component directories using Django templates, vanilla CSS, and vanilla JavaScript.
- [ ] Add dependency and environment setup instructions so a developer can run migrations and start the app locally.
- [x] Add a shared base template, semantic page structure, navigation slots, messages, and reusable template components.
- [ ] Add custom 403, 404, and 500 pages consistent with the product UI.
- [ ] Document the local setup and the rule that views stay thin and business logic lives in services.

## Phase 2 — Identity, organizations, and access control

- [x] Implement the custom Django User model before the first migration, using normalized unique email authentication and the agreed role fields.
- [x] Implement employer and employee roles using Django authentication and password hashing.
- [x] Implement Organization with name, timezone, timestamps, and the agreed owner or membership relationship.
- [x] Implement the agreed employee-to-user and user-to-organization relationships without allowing cross-organization ambiguity.
- [x] Build employer registration/onboarding to create the initial organization and employer account according to Phase 0 decisions.
- [x] Build the agreed secure employee account activation/invitation flow and password reset flow.
- [x] Add login, logout, inactive-account handling, and role-aware post-login routing.
- [x] Create reusable login-required, employer-only, employee-only, and organization-ownership checks.
- [x] Scope every organization-owned list, detail, update, and action query by the authenticated user's organization.
- [x] Ensure employees can access only their own profile, schedules, attendance, and timesheets.
- [x] Add database constraints and indexes for organization ownership and frequently filtered identifiers.
- [ ] Add tests proving role restrictions and cross-organization object access are denied.

## Phase 3 — Employee management

- [x] Implement the Employee profile with organization, optional linked user, unique organization-scoped employee code, employment status, and timestamps.
- [x] Implement employee creation with validated profile fields and the agreed account provisioning behavior.
- [x] Implement employee list, search, status filtering, pagination, detail, and edit pages.
- [x] Implement deactivation rather than destructive deletion for employees with work history.
- [x] Prevent duplicate employee codes within an organization and handle duplicate account emails clearly.
- [x] Show employee role/team title or other profile details only where defined for MVP.
- [ ] Add tests for employee validation, organization scoping, deactivation, and form permissions.

## Phase 4 — Dated shift and schedule management

- [ ] Implement a Shift model linked to an organization and employee, with local work date, scheduled start/end, break allowance, status, and timestamps.
- [ ] Store shift datetimes consistently and support overnight shifts whose end falls on the next local date.
- [ ] Implement schedule creation, assignment, editing, cancellation, list, detail, and filtering by date and employee.
- [ ] Validate start/end ordering, scheduled break allowance bounds, employee organization membership, same-date assignments, cross-date overlaps, and edits after attendance has started.
- [ ] Prevent schedule changes from silently rewriting completed attendance or approved timesheets.
- [ ] Display shifts in the organization timezone and make cancelled shifts visible as cancelled.
- [ ] Provide accessible empty states and form validation for employees without schedules and schedules without matches.
- [ ] Add tests for timezone boundaries, overnight shifts, invalid assignments, conflicts, and organization isolation.
- [ ] Keep recurring schedules, templates, and bulk schedule generation out of MVP.

## Phase 5 — Attendance records and clock workflow

- [ ] Implement AttendanceSession and BreakSession models, organization/employee/shift relationships, timestamps, and valid status choices.
- [ ] Choose and document whether individual attendance events are stored as immutable records in addition to session summaries; preserve the original timestamps needed for auditability.
- [ ] Implement attendance services for clock-in, start-break, end-break, and clock-out; keep state-transition logic out of templates and views.
- [ ] Use server-generated timezone-aware timestamps as the authoritative record; never accept browser-calculated work duration as authoritative.
- [ ] Enforce valid transitions: not started → working → on break → working → completed.
- [ ] Enforce at most one active attendance session per employee/shift, one open break per session, and no duplicate clock action.
- [ ] Make clock actions transaction-safe and safe against double clicks, retries, refreshes, and concurrent requests.
- [ ] Validate that the authenticated employee owns the shift/session and cannot act on another employee's or organization's record.
- [ ] Enforce the Phase 0 rules for unscheduled, early, late, absent, cancelled, and incomplete shifts.
- [ ] Derive employer attendance states such as scheduled, not clocked in, working, on break, late, absent, and completed from server-side records and agreed rules.
- [ ] Handle a missing clock-out using the agreed MVP behavior and ensure it cannot silently become an approved complete timesheet.
- [ ] Add tests for every valid and invalid transition, duplicate/concurrent action, timestamp, status, and organization boundary.
- [ ] Add clear success and failure messages; report success to the browser only after the server commits the action.

## Phase 6 — Timesheet calculation and review

- [ ] Implement Timesheet records linked to organization, employee, shift, and attendance data.
- [ ] Implement a pure, server-side calculator for scheduled minutes, worked minutes, break minutes, payable minutes, late minutes, and undertime minutes using the Phase 0 rules.
- [ ] Use integer minute fields (or another explicitly documented precision) consistently and avoid browser-side payroll-relevant arithmetic.
- [ ] Generate or update a timesheet at the defined point in the attendance lifecycle without creating duplicate records.
- [ ] Implement Pending, Approved, Rejected, and Needs Review states with validated transitions.
- [ ] Implement TimesheetApproval history with reviewer, action, comment, and reviewed timestamp.
- [ ] Implement employer timesheet list, filters, detail, and employee timesheet history/detail pages.
- [ ] Show enough evidence to review a timesheet: scheduled shift, clock events, breaks, calculated totals, late/undertime values, and review history.
- [ ] Implement approve and reject actions with server-side employer authorization and the agreed rejection-comment rule.
- [ ] Prevent an employee from changing attendance through timesheet pages and prevent uncontrolled modification of an approved timesheet.
- [ ] Ensure rejected/incomplete records follow the documented lifecycle and are not treated as approved payroll-ready records.
- [ ] Add tests for calculation edge cases, lifecycle transitions, duplicate generation, rejection, approval, and permissions.

## Phase 7 — Employer workspace and dashboard

- [ ] Build the employer app shell with sidebar, top bar, organization context, account menu, active navigation, and responsive behavior.
- [ ] Implement navigation for Overview, Employees, Schedules, Attendance, Timesheets, Reports, and Settings.
- [ ] Build the dashboard greeting/date and the core KPI cards for employee count, working, late, and absent.
- [ ] Build today's attendance table with employee, shift, status, last activity, and links/actions to relevant records.
- [ ] Provide a clear link from dashboard cards and table rows to the filtered underlying records.
- [ ] Implement the attendance page with organization-local date/status filters and manual refresh or modest polling; no WebSockets.
- [ ] Implement organization settings needed for the MVP, including organization name and timezone, plus account profile settings if required by onboarding.
- [ ] Use shared badges, cards, tables, forms, pagination, confirmations, and empty/error states from the design system.
- [ ] Ensure UI status badges always include readable text, not color alone.
- [ ] Add tests for dashboard counts, filtered attendance visibility, and employer page access.

## Phase 8 — Employee workspace and attendance UI

- [ ] Build a simpler employee app shell and mobile-friendly navigation for Home, Schedule, Timesheets, and Profile.
- [ ] Build the employee dashboard with today's assigned shift, current status, attendance action, live elapsed timer, weekly hours, and recent timesheets.
- [ ] Implement clock-in, start-break, end-break, and clock-out controls that call the server-side attendance workflow.
- [ ] Disable or replace actions according to the server-confirmed attendance state and display useful validation errors.
- [ ] Implement the live timer as display-only JavaScript derived from a server timestamp; refresh/reconcile it after navigation.
- [ ] Show a completed shift summary and clearly distinguish work time from break time.
- [ ] Implement today's/upcoming schedule view and the employee's weekly work-hour summary.
- [ ] Implement employee timesheet list/detail with status, shift date, hours, and employer decision.
- [ ] Ensure employees cannot view other employees' records, even by changing a URL or submitted identifier.
- [ ] Add tests for employee pages, action visibility, weekly totals, and ownership restrictions.

## Phase 9 — Reports, CSV export, and audit history

- [ ] Implement an organization-scoped daily attendance report with date and relevant status/employee filters.
- [ ] Implement weekly employee work-hour summaries and timesheet status summaries.
- [ ] Apply the organization timezone consistently to report boundaries, displayed timestamps, and date filters.
- [ ] Implement CSV export using Python's standard csv module with documented headers, safe encoding, and the same filters/authorization as the report.
- [ ] Prevent CSV formula injection for untrusted text values and ensure export output does not expose other organizations' data.
- [ ] Implement AuditEvent with organization, actor, action, target type/ID, metadata, and timestamp.
- [ ] Record the agreed sensitive MVP actions, including employee/schedule changes, attendance exceptions or corrections if supported, and timesheet approval/rejection.
- [ ] Keep audit records append-only through the application and avoid recording passwords, tokens, or unnecessary personal data.
- [ ] Provide employer-visible history where needed to explain timesheet decisions and recorded administrative changes.
- [ ] Add tests for report totals, date boundaries, CSV content/scope, and audit creation.

## Phase 10 — Shared design, accessibility, security, and quality

- [ ] Implement the documented blue/neutral/status color tokens, typography, spacing, borders, and restrained shadows in organized vanilla CSS.
- [ ] Build layouts for the target desktop widths and verify employee workflows on mobile-sized screens.
- [ ] Make forms, tables, navigation, dialogs, and attendance controls keyboard usable with visible focus.
- [ ] Use semantic HTML, associated labels, correct headings, accessible validation/error messages, and table headers.
- [ ] Meet the documented minimum touch target for mobile interactions and avoid dense mobile tables.
- [ ] Use Django CSRF protection on all state-changing forms/requests and validate HTTP methods.
- [ ] Configure secure session/CSRF cookie settings, HTTPS-aware proxy settings, allowed hosts, trusted origins, and production DEBUG=False.
- [ ] Review authentication, password reset, role checks, organization scoping, and object-level authorization for every view/action.
- [ ] Review database constraints, query indexes, error handling, and transaction behavior for attendance and approval actions.
- [ ] Configure application logging for errors and operational events without secrets or passwords.
- [ ] Add automated model, service, permission, and view tests required by the Tech Stack document.
- [ ] Cover the end-to-end scenarios: new organization, employee setup, scheduled overnight shift, clock/break/clock-out, calculation, approval/rejection, reporting, and CSV export.
- [ ] Add edge-case coverage for timezone/date boundaries, invalid transitions, missing events, concurrent requests, inactive accounts, and cross-tenant identifiers.
- [ ] Run the automated suite and resolve failures before release.
- [ ] Perform a manual browser review of employer and employee workflows at desktop, tablet, and mobile widths.
- [ ] Review the finished screens against the Project Design Skill: clarity, status communication, empty/loading/error states, and restrained operational layout.

## Phase 11 — Production deployment and MVP release

- [ ] Select and provision an Ubuntu LTS production host, PostgreSQL database, production domain, and HTTPS certificate.
- [ ] Configure Nginx as the public reverse proxy and serve collected static files.
- [ ] Configure Gunicorn and systemd for reliable Django process startup, restart, and logs.
- [ ] Configure production environment variables and secret handling outside the repository.
- [ ] Configure production email delivery for the agreed account activation and password-reset flows.
- [ ] Set production security settings, HTTPS redirects, secure cookies, allowed hosts, CSRF trusted origins, and HSTS after HTTPS is verified.
- [ ] Define and document database backup retention and perform a restore rehearsal before launch.
- [ ] Document deployment, migrations, static collection, admin account creation, rollback, backup restoration, and common operational checks.
- [ ] Deploy to a staging environment and walk through the full employer and employee acceptance workflow using non-production data.
- [ ] Verify production health, database connectivity, static assets, HTTPS, logs, and a recovery path.
- [ ] Create the MVP release/tag and record known limitations, including deferred roadmap items.

---

## MVP acceptance checklist

- [ ] Employer signup creates a usable organization with its configured timezone.
- [ ] An employer can create, edit, deactivate, search, and view employees within their organization.
- [ ] An employer can create, assign, edit, cancel, and inspect dated shifts, including overnight shifts.
- [ ] An employee can view only their own schedule and attendance history.
- [ ] Clock and break actions enforce valid transitions and persist server timestamps exactly once.
- [ ] Attendance and timesheet calculations follow the written business rules and cannot be altered by browser code.
- [ ] Missing or invalid attendance is visibly handled and cannot silently be approved as complete.
- [ ] Employers can see daily attendance and identify scheduled, working, on-break, late, absent, and completed employees according to the agreed rules.
- [ ] Employers can inspect, approve, or reject timesheets and see who reviewed them and when.
- [ ] Employees can see their current shift/status, display-only live timer, weekly hours, and timesheet history.
- [ ] Reports and CSV exports match the selected filters and contain only the current organization's records.
- [ ] Sensitive administrative and timesheet review actions have useful audit history.
- [ ] Role and tenant isolation tests pass, as do attendance-service and calculation tests.
- [ ] The desktop employer workflow and mobile employee workflow are accessible and usable.
- [ ] The deployed app has HTTPS, secure production settings, database backups, and an operator runbook.
