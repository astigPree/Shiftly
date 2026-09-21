# Shiftly Project Tasks

## Purpose and source of truth

This file turns the Shiftly project documents into an actionable, ordered checklist for the attendance MVP and the newly approved payroll feature. The attached documents describe the product and its intended implementation; their directions are project requirements, not separate actions for this planning task.

The original project documents describe the attendance MVP. This task plan records the later approved payroll scope; that approval supersedes older statements that exclude payroll, and the relevant project documents must be synchronized before implementation.

When requirements differ in emphasis:

1. This task plan records the latest approved scope changes; update the Project Description to match them.
2. The Tech Stack defines implementation constraints.
3. The Project Design Skill defines visual and interaction guidance for product interfaces.

The attendance MVP is a lightweight, multi-organization attendance and timesheet web app. Its core workflow is:

**Employer creates employee → assigns a dated shift → employee records clock and break events → Django calculates work time → employer reviews and approves or rejects the timesheet → employer can report and export the resulting records.**

## Product scope

Payroll is now an approved Shiftly feature. Phase 11 expands the earlier attendance-only scope and supersedes the previous exclusion of payroll rates, calculations, and payslips. Payroll rules and calculations are not implemented yet; every Phase 11 task is still open.

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
- Payroll runs, employer review and approval, itemized employee payslips, and payroll exports using rules validated for each supported jurisdiction (planned; see Phase 11).

### Explicitly outside the MVP

Do not add these unless the product scope is deliberately revised: mobile or SPA clients, DRF/public API, recurring schedules or shift templates, leave management, departments/teams, notifications/reminders, automated approval rules, advanced attendance corrections, client billing, direct bank transfers or payment initiation, real-time WebSockets, Redis/Celery, or microservices. Payroll calculations, payslips, and payroll exports are now planned in Phase 11; direct movement of funds remains a separate scope decision.

## Completion standard

The attendance MVP is ready when an employer can create an organization, add an employee, assign a shift, monitor attendance, review and decide a timesheet, and export/report the records; an employee can securely complete the shift workflow and review their hours; organization boundaries and server-side calculations are enforced; critical paths have automated coverage; and the application is deployed with operational documentation. The product is ready with payroll when the additional Phase 11 acceptance criteria are met, including jurisdiction-reviewed calculations, employer-approved and reproducible pay runs, employee payslips, and scoped exports.

---

## Phase 0 — Resolve product rules before implementation

**Status: Complete for attendance and timesheets.** Their resolved behavior and end-to-end acceptance scenarios are recorded in [SHIFTLY_MVP_ACCEPTANCE_CRITERIA.md](SHIFTLY_MVP_ACCEPTANCE_CRITERIA.md). Payroll rules are not covered by that decision set yet and must be defined in Phase 11 before payroll implementation.

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
- [x] Define duration, break, payable-time minutes, late, undertime, precision, and flooring rules; these are time quantities, not monetary payroll calculations.
- [x] Define one timesheet per completed shift, generation after clock-out, review states, terminal decisions, and Needs Review behavior.
- [x] Require a rejection comment and define append-only audit coverage.
- [x] Define organization-local daily/weekly report boundaries and CSV columns.
- [x] Capture decisions in the acceptance-criteria document and align the Project Description, Tech Stack, and task plan.

---

## Phase 1 — Create the Django foundation

- [x] Pin supported Python, Django, PostgreSQL adapter, and production server versions in .python-version and requirements files; record support rationale in SHIFTLY_TECH_STACK.md.
- [x] Create the Django project and configuration package with manage.py, URL routing, WSGI/ASGI entry points, and production-safe settings.
- [x] Create the modular Django apps for accounts, organizations, employees, schedules, attendance, timesheets, reports, and audit.
- [x] Use SQLite for local development and PostgreSQL for production; keep application models and migrations compatible with both.
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

- [x] Implement a Shift model linked to an organization and employee, with local work date, scheduled start/end, break allowance, status, and timestamps.
- [x] Store shift datetimes consistently and support overnight shifts whose end falls on the next local date.
- [x] Implement schedule creation, assignment, editing, cancellation, list, detail, and filtering by date and employee.
- [x] Validate start/end ordering, scheduled break allowance bounds, employee organization membership, same-date assignments, cross-date overlaps, and edits after attendance has started.
- [x] Prevent schedule changes from silently rewriting completed attendance or approved timesheets.
- [x] Display shifts in the organization timezone and make cancelled shifts visible as cancelled.
- [x] Provide accessible empty states and form validation for employees without schedules and schedules without matches.
- [ ] Add tests for timezone boundaries, overnight shifts, invalid assignments, conflicts, and organization isolation.
- [x] Keep recurring schedules, templates, and bulk schedule generation out of MVP.

## Phase 5 — Attendance records and clock workflow

- [x] Implement AttendanceSession and BreakSession models, organization/employee/shift relationships, timestamps, and valid status choices.
- [x] Store clock-in, clock-out, break start, and break end as immutable timestamp fields on the attendance and break session records; separate event rows are unnecessary for this MVP.
- [x] Implement attendance services for clock-in, start-break, end-break, and clock-out; keep state-transition logic out of templates and views.
- [x] Use server-generated timezone-aware timestamps as the authoritative record; never accept browser-calculated work duration as authoritative.
- [x] Enforce valid transitions: not started → working → on break → working → completed.
- [x] Enforce at most one active attendance session per employee/shift, one open break per session, and no duplicate clock action.
- [x] Make clock actions transaction-safe and safe against double clicks, retries, refreshes, and concurrent requests.
- [x] Validate that the authenticated employee owns the shift/session and cannot act on another employee's or organization's record.
- [x] Enforce the Phase 0 rules for unscheduled, early, late, absent, cancelled, and incomplete shifts.
- [x] Derive employer attendance states such as scheduled, not clocked in, working, on break, late, absent, and completed from server-side records and agreed rules.
- [x] Handle a missing clock-out using the agreed MVP behavior and ensure it cannot silently become an approved complete timesheet.
- [ ] Add tests for every valid and invalid transition, duplicate/concurrent action, timestamp, status, and organization boundary.
- [x] Add clear success and failure messages; report success to the browser only after the server commits the action.

## Phase 6 — Timesheet calculation and review

- [x] Implement Timesheet records linked to organization, employee, shift, and attendance data.
- [x] Implement a pure, server-side calculator for scheduled minutes, worked minutes, break minutes, payable minutes, late minutes, and undertime minutes using the Phase 0 rules.
- [x] Use integer minute fields (or another explicitly documented precision) consistently and avoid browser-side payroll-relevant arithmetic.
- [x] Generate or update a timesheet at the defined point in the attendance lifecycle without creating duplicate records.
- [x] Implement Pending, Approved, Rejected, and Needs Review states with validated transitions.
- [x] Implement TimesheetApproval history with reviewer, action, comment, and reviewed timestamp.
- [x] Implement employer timesheet list, filters, detail, and employee timesheet history/detail pages.
- [x] Show enough evidence to review a timesheet: scheduled shift, clock events, breaks, calculated totals, late/undertime values, and review history.
- [x] Implement approve and reject actions with server-side employer authorization and the agreed rejection-comment rule.
- [x] Prevent an employee from changing attendance through timesheet pages and prevent uncontrolled modification of an approved timesheet.
- [x] Ensure rejected/incomplete records follow the documented lifecycle and are not treated as approved payroll-ready records.
- [ ] Add tests for calculation edge cases, lifecycle transitions, duplicate generation, rejection, approval, and permissions.

- [x] Build the employer app shell with sidebar, top bar, organization context, account menu, active navigation, and responsive behavior.
- [x] Implement navigation for Overview, Employees, Schedules, Attendance, Timesheets, Reports, and Settings.
- [x] Build the dashboard greeting/date and the core KPI cards for employee count, working, late, and absent.
- [x] Build today's attendance table with employee, shift, status, last activity, and links/actions to relevant records.
- [x] Provide a clear link from dashboard cards and table rows to the filtered underlying records.
- [x] Implement the attendance page with organization-local date/status filters and manual refresh or modest polling; no WebSockets.
- [x] Implement organization settings needed for the MVP, including organization name and timezone, plus account profile settings if required by onboarding.
- [x] Use shared badges, cards, tables, forms, pagination, confirmations, and empty/error states from the design system.
- [x] Ensure UI status badges always include readable text, not color alone.
- [ ] Add tests for dashboard counts, filtered attendance visibility, and employer page access.

- [x] Build a simpler employee app shell and mobile-friendly navigation for Home, Schedule, Timesheets, and Profile.
- [x] Build the employee dashboard with today's assigned shift, current status, attendance action, live elapsed timer, weekly hours, and recent timesheets.
- [x] Implement clock-in, start-break, end-break, and clock-out controls that call the server-side attendance workflow.
- [x] Disable or replace actions according to the server-confirmed attendance state and display useful validation errors.
- [x] Implement the live timer as display-only JavaScript derived from a server timestamp; refresh/reconcile it after navigation.
- [x] Show a completed shift summary and clearly distinguish work time from break time.
- [x] Implement today's/upcoming schedule view and the employee's weekly work-hour summary.
- [x] Implement employee timesheet list/detail with status, shift date, hours, and employer decision.
- [x] Ensure employees cannot view other employees' records, even by changing a URL or submitted identifier.
- [ ] Add tests for employee pages, action visibility, weekly totals, and ownership restrictions.

- [x] Implement an organization-scoped daily attendance report with date and relevant status/employee filters.
- [x] Implement weekly employee work-hour summaries and timesheet status summaries.
- [x] Apply the organization timezone consistently to report boundaries, displayed timestamps, and date filters.
- [x] Implement CSV export using Python's standard csv module with documented headers, safe encoding, and the same filters/authorization as the report.
- [x] Prevent CSV formula injection for untrusted text values and ensure export output does not expose other organizations' data.
- [x] Implement AuditEvent with organization, actor, action, target type/ID, metadata, and timestamp.
- [x] Record the agreed sensitive MVP actions, including employee/schedule changes, attendance exceptions or corrections if supported, and timesheet approval/rejection.
- [x] Keep audit records append-only through the application and avoid recording passwords, tokens, or unnecessary personal data.
- [x] Provide employer-visible history where needed to explain timesheet decisions and recorded administrative changes.
- [ ] Add tests for report totals, date boundaries, CSV content/scope, and audit creation.

## Phase 10 — Shared design, accessibility, security, and quality

- [x] Implement the documented blue/neutral/status color tokens, typography, spacing, borders, and restrained shadows in organized vanilla CSS.
- [ ] Build layouts for the target desktop widths and verify employee workflows on mobile-sized screens.
- [x] Make forms, tables, navigation, dialogs, and attendance controls keyboard usable with visible focus.
- [x] Use semantic HTML, associated labels, correct headings, accessible validation/error messages, and table headers.
- [x] Meet the documented minimum touch target for mobile interactions and avoid dense mobile tables.
- [x] Use Django CSRF protection on all state-changing forms/requests and validate HTTP methods.
- [x] Configure secure session/CSRF cookie settings, HTTPS-aware proxy settings, allowed hosts, trusted origins, and production DEBUG=False.
- [x] Review authentication, password reset, role checks, organization scoping, and object-level authorization for every view/action.
- [x] Review database constraints, query indexes, error handling, and transaction behavior for attendance and approval actions.
- [x] Configure application logging for errors and operational events without secrets or passwords.
- [ ] Add automated model, service, permission, and view tests required by the Tech Stack document.
- [ ] Cover the end-to-end scenarios: new organization, employee setup, scheduled overnight shift, clock/break/clock-out, timesheet calculation, approval/rejection, reporting, and CSV export. Payroll scenarios are covered by Phase 11.
- [ ] Add edge-case coverage for timezone/date boundaries, invalid transitions, missing events, concurrent requests, inactive accounts, and cross-tenant identifiers.
- [ ] Run the automated suite and resolve failures before release.
- [ ] Perform a manual browser review of employer and employee workflows at desktop, tablet, and mobile widths.
- [ ] Review the finished screens against the Project Design Skill: clarity, status communication, empty/loading/error states, and restrained operational layout.

### Explicit night shift scenario — cross-midnight timekeeping only

- [ ] Verify an employer can schedule a shift from 10:00 PM on its local work date to 3:00 AM on the next local date, and that the UI identifies it as overnight.
- [ ] Verify one employee attendance session can clock in at 10:00 PM, record a break from 11:50 PM to 12:10 AM, and clock out at 3:00 AM across local midnight.
- [ ] Verify clock-out creates one timesheet attached to the shift's original local work date, with 280 worked minutes after the 20-minute break; the next date must not get a duplicate shift or timesheet.
- [ ] Verify schedule, attendance, employee weekly hours, employer reports, and timesheet details display the overnight shift in the organization timezone and attribute it to the original work date.
- [ ] Keep the attendance portion of this scenario focused on timestamps, state, and worked duration. Any night-differential amount or other pay treatment must follow the jurisdiction-approved rules defined and tested in Phase 11.

## Phase 11 — Payroll feature (new approved scope)

Payroll is a separate feature layer that consumes approved timesheets. The existing `payable_minutes` value is a time quantity; it is not a money amount. All monetary calculations must be server-side, reproducible from recorded inputs, and reviewed against the supported jurisdiction's current rules before use. No task below assumes that Shiftly will transfer funds directly.

### 11.1 Define payroll scope and business rules

- [ ] Confirm the first supported payroll jurisdiction(s), legal employer setup, employee work location rules, and who is qualified to approve the payroll rules.
- [ ] Research the current official labor, tax, social contribution, record-retention, and payslip requirements for each supported jurisdiction; record source links, effective dates, and an owner for updates.
- [ ] Decide whether organizations can run payroll in multiple jurisdictions and currencies, or whether the first release supports one payroll jurisdiction and currency per organization.
- [ ] Define pay frequency, payroll period boundaries, cutoff date, pay date, timezone rules, and treatment of late-approved timesheets.
- [ ] Decide which worker classifications and pay bases are supported in the first release (for example hourly and salaried employees); explicitly defer unsupported classifications.
- [ ] Define how approved timesheets map to regular payable hours, including rounding precision, minute-to-money conversion, unpaid breaks, and the employee's effective pay rate on the work date.
- [ ] Define overtime eligibility, thresholds, rate multipliers, daily/weekly boundaries, rest-day and holiday rules, premium stacking order, and rounding behavior for each jurisdiction.
- [ ] Define the authoritative holiday/rest-day calendar source and how jurisdiction, region, and employer-specific holidays are maintained for each payroll year.
- [ ] Define night-differential eligibility, the local qualifying time window, premium rate, treatment of breaks, and how overnight work and daylight-saving changes are split across eligible time segments.
- [ ] Define gross pay components, including base pay, overtime, night differential, holiday/rest-day premiums, allowances, reimbursements, bonuses, and retroactive adjustments; identify which components are taxable or pensionable by jurisdiction.
- [ ] Define employee deductions and employer contributions, including statutory withholding/contributions and any supported voluntary deductions, advances, or loans, with effective dates, caps, and calculation order.
- [ ] Define net-pay behavior for zero pay, negative deductions, over-deductions, corrections, and employees with no eligible approved timesheets.
- [ ] Decide whether payroll is calculation-and-export only for the first release or includes a payment-provider/bank disbursement integration; require separate security, reconciliation, and authorization design before any direct fund movement.
- [ ] Define who may prepare, review, approve, and finalize a payroll run, including whether the same person may prepare and approve it.
- [ ] Define whether finalized payroll can be reopened; prefer correcting finalized runs through an auditable adjustment or off-cycle run rather than silently rewriting history.
- [ ] Record all decisions in payroll acceptance criteria and update the Project Description, Tech Stack, data-flow/security documentation, and this task plan so they no longer describe payroll as excluded.

### 11.2 Payroll data, rates, and calculation engine

- [ ] Add an organization-scoped employee pay profile with payroll jurisdiction, currency, pay basis, pay frequency, and only the personal/payroll identifiers required for the supported rules.
- [ ] Build employer forms for organization payroll settings and employee pay profiles, with role restrictions, clear effective dates, and change summaries.
- [ ] Add effective-dated pay-rate history so a rate change applies to the correct work dates and never changes a finalized payroll run.
- [ ] Model jurisdictional tax, contribution, overtime, holiday, rest-day, night-differential, and deduction rules as versioned, effective-dated configuration rather than scattered constants.
- [ ] Add payroll periods and payroll runs with explicit Draft, Review, Approved/Finalized, and Voided states, creator/reviewer timestamps, currency, and period boundaries.
- [ ] Add per-employee payroll statements and itemized earning, premium, allowance, reimbursement, deduction, employer-contribution, gross, and net line items.
- [ ] Snapshot the approved timesheets, effective pay profiles, rule versions, and calculation inputs used by each finalized run so its results can be reproduced later.
- [ ] Use `Decimal` and explicit currency minor-unit rounding for all money; never use floating-point or browser-side arithmetic as the authoritative calculation.
- [ ] Implement a pure server-side calculator with separately reviewable functions for base earnings, overtime, night differential, holiday/rest-day premiums, allowances, deductions, contributions, gross totals, and net totals.
- [ ] Generate payroll only from eligible approved timesheets and surface pending, rejected, incomplete, or missing-clock records as exceptions instead of silently paying or omitting them.
- [ ] Split overnight attendance intervals at local payroll-rule boundaries, including midnight, pay-period boundaries, night-differential windows, and daylight-saving transitions where applicable.
- [ ] Define and implement idempotent run generation, duplicate-run prevention, transaction handling, and safe behavior when timesheets or pay profiles change during a draft run.
- [ ] Prevent finalized runs and statements from changing when source timesheets, employee rates, or rule configuration are edited later.
- [ ] Implement a correction path for post-finalization changes using linked adjustment lines and off-cycle/next-run treatment with a complete audit trail.
- [ ] Add database constraints and indexes for unique employee/run statements, organization isolation, effective-dated rates, and payroll period queries.

### 11.3 Employer payroll workflow

- [ ] Build employer payroll navigation and an organization-scoped payroll run list with period, pay date, status, employee count, currency totals, and exceptions.
- [ ] Apply the Project Design Skill to payroll workflows; provide responsive, accessible forms, review screens, status/exception states, and clear empty/loading/error feedback.
- [ ] Build payroll period creation with clear cutoff/pay-date context, duplicate-period checks, and a preview of eligible timesheets and employees.
- [ ] Build controlled draft earning/deduction adjustments for bonuses, allowances, reimbursements, advances, and corrections, requiring a category, amount, effective date, and reason.
- [ ] Build a draft run preview with per-employee and organization totals, itemized earnings/deductions, source timesheet links, and visible calculation exceptions.
- [ ] Let authorized employers resolve draft exceptions and recalculate before approval while preserving a trace of changes and prior previews.
- [ ] Add a review/approval step showing the pay period, employees, gross, deductions, net, premiums, exceptions, and exports before finalization.
- [ ] Enforce the approved employer role and organization ownership for creating, reviewing, approving, finalizing, voiding, and exporting payroll.
- [ ] Require an explicit confirmation modal for finalizing or voiding a payroll run; make actions idempotent and show success only after the server commits.
- [ ] If direct disbursement is approved, integrate only an approved provider; require explicit authorization, idempotency, secure beneficiary handling, payment-status reconciliation, and audited failure/retry/return handling.
- [ ] Build a finalized payroll run detail page with immutable totals, source/rule snapshot details, approval history, and any later adjustment runs.
- [ ] Provide an auditable correction/off-cycle workflow for late timesheets, rate changes, and payroll errors without altering finalized records.
- [ ] Provide payroll history and filters by period, employee, status, and jurisdiction, with pagination for growing data.

### 11.4 Employee payslips, exports, and reporting

- [ ] Build an employee payroll history and payslip detail page that exposes only that employee's own statements.
- [ ] Show pay period, pay date, currency, rate basis, hours, each earning/premium, allowances, deductions, contributions where required, gross pay, and net pay with clear labels.
- [ ] Generate a printable/downloadable payslip in the format required for each supported jurisdiction and preserve the finalized version.
- [ ] Generate jurisdiction-required periodic and year-end payroll summaries or filing exports when those are part of the supported release scope.
- [ ] Add employer payroll summaries and CSV exports with documented columns, currency totals, the same filters/authorization as the page, and formula-injection protection.
- [ ] Decide and document any accounting or bank-file export formats before implementing them; do not expose unnecessary employee banking or tax identifiers.
- [ ] Reconcile employee statement totals against run totals and show any difference as a blocking validation error.

### 11.5 Security, audit, testing, and rollout

- [ ] Restrict pay profiles and payroll statements to authorized employers and the employee's own account; add cross-organization and cross-employee access checks.
- [ ] Protect payroll identifiers and any optional banking data through data minimization, appropriate encryption, access controls, and secret-safe logging.
- [ ] Audit pay-rate/rule changes, run creation and recalculation, approval/finalization, voiding, adjustments, and sensitive statement/export access.
- [ ] Define payroll record retention, correction, export, backup, restore, and employee data access procedures for each supported jurisdiction.
- [ ] Add calculator tests for base pay, effective-dated rates, currency rounding, unpaid breaks, overtime, night differential, holiday/rest-day premiums, deductions, caps, zero hours, and correction cases.
- [ ] Create reviewed reference scenarios and independently reconcile expected totals with a qualified payroll/accounting reviewer before treating them as calculation truth.
- [ ] Add end-to-end tests for a pay period, approved and excluded timesheets, employee payslip access, role restrictions, organization isolation, duplicate requests, concurrent run generation, and immutable finalized results.
- [ ] Add overnight payroll tests for a 10:00 PM–3:00 AM shift, including the correct original work date, break deduction, local pay-period split, and configured night-differential window where applicable.
- [ ] Add test coverage for daylight-saving transitions, period boundaries, pay-rate changes during a period, late approvals, rejected/incomplete timesheets, off-cycle runs, and exports.
- [ ] Run a shadow payroll using copied/non-production data and compare every employee statement and total with the existing payroll process for at least two complete pay cycles.
- [ ] Obtain documented legal/accounting sign-off for each jurisdiction and resolve all reconciliation differences before payroll is used to pay employees.
- [ ] Pilot with a limited organization and an agreed rollback/correction plan; train employers and employees on payslips, review, and correction workflows.
- [ ] Record payroll limitations, supported jurisdictions, effective rule dates, operator steps, and the boundary between calculation/export and actual money movement.

## Phase 12 — Production deployment and release

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
- [ ] Create the release/tag for the approved release scope and record known limitations, including deferred roadmap items.

---

## Product release acceptance checklist

- [ ] Employer signup creates a usable organization with its configured timezone.
- [ ] An employer can create, edit, deactivate, search, and view employees within their organization.
- [ ] An employer can create, assign, edit, cancel, and inspect dated shifts, including overnight shifts.
- [ ] The 10:00 PM–3:00 AM night shift completes across local midnight as one attendance session and one timesheet on the original work date, with its recorded break deducted from elapsed work time.
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
- [ ] Employee pay profiles and payroll rules are effective-dated, jurisdiction-approved, and changes cannot rewrite finalized payroll.
- [ ] Payroll runs include only eligible approved timesheets and show itemized regular pay, applicable premiums, deductions, gross, net, and exceptions.
- [ ] Overnight work is split and valued using the approved local payroll rules, including night differential only where configured and legally validated.
- [ ] Employers can review, approve, finalize, and audit reproducible payroll runs; corrections use an adjustment/off-cycle process.
- [ ] Employees can securely view their own finalized payslips, and authorized employers can export reconciled payroll totals.
- [ ] Payroll calculations pass reviewed reference scenarios, security/tenant-isolation tests, and a successful two-cycle shadow reconciliation.
- [ ] The release's direct-payment boundary is documented; no funds are transferred unless a separately approved payment integration is implemented.
- [ ] The desktop employer workflow and mobile employee workflow are accessible and usable.
- [ ] The deployed app has HTTPS, secure production settings, database backups, and an operator runbook.
