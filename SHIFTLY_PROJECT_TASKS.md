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

Payroll is now an approved Shiftly feature. Phase 11 expands the earlier attendance-only scope and supersedes the previous exclusion of payroll rates, calculations, and payslips. The PH payroll foundation has been implemented in the application. Jurisdictional legal/accounting validation, statutory contribution calculations, tests, shadow payroll, and pilot sign-off remain open; Phase 11 shows the exact boundary.

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
- Philippines/PHP hourly payroll runs, employer review/finalization, itemized employee statements, and CSV export using employer-configured effective-dated rules (implemented foundation; legal validation remains open; see Phase 11).

### Explicitly outside the MVP

Do not add these unless the product scope is deliberately revised: mobile or SPA clients, DRF/public API, recurring schedules or shift templates, leave management, departments/teams, notifications/reminders, automated approval rules, advanced attendance corrections, client billing, direct bank transfers or payment initiation, real-time WebSockets, Redis/Celery, or microservices. The initial payroll foundation, payslips, and CSV exports are implemented in Phase 11; statutory automation and movement of funds remain outside the current release.

## Completion standard

The attendance MVP is ready when an employer can create an organization, add an employee, assign a shift, monitor attendance, review and decide a timesheet, and export/report the records; an employee can securely complete the shift workflow and review their hours; organization boundaries and server-side calculations are enforced; critical paths have automated coverage; and the application is deployed with operational documentation. The product is ready with payroll when the additional Phase 11 acceptance criteria are met, including jurisdiction-reviewed calculations, employer-approved and reproducible pay runs, employee payslips, and scoped exports.

---

## Phase 0 — Resolve product rules before implementation

**Status: Complete for attendance and timesheets.** Their resolved behavior and end-to-end acceptance scenarios are recorded in [SHIFTLY_MVP_ACCEPTANCE_CRITERIA.md](SHIFTLY_MVP_ACCEPTANCE_CRITERIA.md). Payroll implementation exists; legal and accounting decisions still open are tracked in Phase 11.

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

## Phase 11 - Payroll feature (approved scope)

**Implementation status: payroll foundation implemented; not cleared for live payroll.** The current release supports one Philippine organization currency (PHP), hourly pay, employer-entered effective-dated rules, approved timesheets, reviewable runs, manual line items, final statements, and CSV export. It does not calculate Philippine tax withholding, SSS, PhilHealth, Pag-IBIG, or transfer money. Reviewer fields capture an application attestation, not legal/accounting sign-off.

### 11.1 Scope and business rules

- [x] Set the initial jurisdiction to the Philippines and currency to PHP; keep the first implementation to hourly employees and one payroll currency per organization.
- [x] Add weekly, semi-monthly, and monthly calendar pay periods; retain the selected frequency on each run.
- [x] Use inclusive calendar dates for payroll periods. Split worked intervals in each employee's configured work-location timezone and select effective rates/rules by that local work date. New profiles start with the employee's preferred timezone when available; otherwise they use the organization timezone.
- [x] Make daily regular minutes, overtime/rest-day multipliers, night window, and night differential rate configurable and effective-dated. Require source references and reviewer details before a rule version can be used for finalization.
- [x] Require an employer-entered work location, region, wage-order reference, and minimum-wage check before calculating an employee's time. Require an explicit night-differential eligibility confirmation before valuing night work.
- [x] Define zero-pay as reviewable only after an explicit exception decision; block negative net pay and deductions greater than gross pay.
- [x] Keep direct payment/disbursement outside the product; the current export is for employer reconciliation.
- [x] Retain finalized runs and correct later changes through a linked off-cycle run rather than editing the finalized run.
- [ ] Research and maintain the current official labor, tax, contribution, record-retention, and payslip rules with effective dates and a qualified owner.
- [ ] Resolve jurisdiction-specific employee classifications, regional wage-order data, statutory pay bases, taxability, contribution caps, and mandatory filing requirements with a qualified Philippine payroll/accounting reviewer.
- [x] Recalculate draft runs when late-approved timesheets become eligible; use a linked off-cycle run after finalization. Require unresolved pending timesheets to be decided before review.
- [ ] Have a qualified reviewer confirm that per-employee local calendar dates are appropriate for payroll period boundaries when the organization and employee work timezones differ.
- [ ] Obtain documented legal/accounting approval of the rule set before live payroll use.

### 11.2 Payroll data and calculation foundation

- [x] Add organization payroll settings, employee work/pay profiles, employee timezone, work-location fields, effective hourly-rate history, holidays, payroll runs, employee statements, itemized lines, time entries, exceptions, and immutable calculation snapshots.
- [x] Use Decimal arithmetic and explicit PHP cent rounding on the server. The browser is not authoritative for money.
- [x] Calculate base hourly pay, configured daily overtime premium, ordinary-day night differential, and reviewed non-stacking rest-day/holiday premiums from approved timesheets.
- [x] Split overnight time by employee-local midnight and configured night-window boundaries. Apply rate/rule versions by employee-local work date and preserve the included UTC segments in calculation snapshots.
- [x] Block finalization for missing profiles/rates/rules, unconfirmed night eligibility, incomplete or missing attendance/timesheets, pending timesheets, unresolved premium combinations, and other unreviewed exceptions. Rejected timesheets stay excluded and require an explicit recorded exclusion decision.
- [x] Prevent duplicate regular periods and duplicate form submissions; recalculate drafts transactionally while preserving manual lines and prior preview history.
- [x] Freeze finalized runs and their statements/lines/time entries. Prevent new effective rates or rule versions from changing dates already covered by finalized payroll.
- [x] Lock an employee's payroll timezone after the first finalized statement so later timezone changes cannot remap already-paid time.
- [ ] Add effective-dated work-location/timezone history so employee moves can be represented without permanently locking their payroll timezone.
- [x] Provide a linked off-cycle adjustment run for post-finalization corrections.
- [x] Add database constraints and indexes for payroll ownership, periods, statements, effective rates, rules, and idempotency.
- [ ] Add reviewed reference calculations for ordinary hours, overtime, rest day, holiday, night differential, breaks, rate changes, and corrections.
- [ ] Add overnight and boundary scenarios including a 10:00 PM-3:00 AM shift in the employee's work timezone, pay-period crossover, and applicable DST transitions.

### 11.2.1 Payroll rule profiles and employee assignment

**Problem to solve:** employees in one organization may share the same payroll rules, follow a different rule set because of location or agreement, or move between rule sets over time. Copying rule values onto every employee would create drift, make reviews difficult, and make historical payroll harder to reproduce.

**Recommended design:** keep rule values reusable in named, organization-scoped profiles. An employee receives one effective-dated assignment to a profile, while employees without an override inherit the organization's default profile. A profile owns its own non-overlapping effective-dated rule versions. Employee eligibility facts (work location, wage region, rest day, wage-order confirmation, and night-differential eligibility) remain on `EmployeePayProfile`; they do not silently choose a rule profile.

- [x] Add a reusable `PayrollRuleProfile` model with organization, unique code, name, description, active state, and an organization default flag; enforce at most one default profile per organization.
- [x] Associate `PayrollRuleSet` versions with a rule profile. Replace organization/date uniqueness and overlap checks with profile/date checks while retaining effective dates, reviewed source evidence, immutable reviewed versions, and tenant ownership.
- [x] Add an effective-dated `PayrollRuleAssignment` model with organization, employee, rule profile, inclusive effective-from/effective-until dates, assigned-by, reason, and audit timestamps. Prevent overlapping assignments for the same employee and require organization/employee/profile consistency.
- [x] Define deterministic resolution for an employee-local work date: matching employee assignment first, organization default profile second, then the matching rule version inside that profile. If no version exists, more than one candidate matches, or the default is missing, create a blocking payroll exception instead of guessing.
- [x] Keep assignment and rule-version dates inclusive and validate date ranges. Allow an assignment to span future versions, but require a matching reviewed version on every worked date included in a run; report gaps before finalization.
- [x] Snapshot the resolved profile, assignment, rule-version identifier, effective dates, inputs, and source/reviewer evidence on payroll time entries/statements. Later assignments or rule edits must not change a draft preview's finalized snapshot or a finalized run.
- [x] Prevent rule-profile/version changes that cover finalized payroll periods. Route corrections through a linked off-cycle run and preserve the prior assignment and rule evidence in the audit log.
- [x] Migrate existing organization-wide rule versions into an `Organization default` profile and let existing employees inherit it, preserving current payroll behavior. Provide a data check for organizations with no usable default profile.
- [ ] Add payroll readiness checks for missing default profiles, missing employee assignments where an override is required, assignment overlaps, rule-version gaps, unreviewed versions, and ambiguous matches. Show the affected employees and local work dates.
- [x] Add a Payroll settings **Rule profiles** area showing profile status, default/inherited state, version history, review state, and employee count. Add an employee pay-profile control showing the current inherited or assigned profile and its assignment history.
- [x] Add bulk assignment for selected employees with an effective date, optional end date, reason, and conflict validation before saving.
- [x] Show the resolved rule profile and version on run previews and statement detail so an employer can explain why two employees with the same shift received different treatment.
- [x] Add audit events for profile creation, version creation, assignment/bulk-assignment changes, inheritance changes, conflict resolution, and payroll resolution failures.
- [ ] Add tests for default inheritance, employee overrides, same-profile reuse, non-overlapping date boundaries, profile changes, overnight work/timezone resolution, missing and ambiguous matches, migration compatibility, tenant isolation, duplicate requests, and finalized-run immutability.
- [ ] Add reviewed reference scenarios for two employees sharing one profile, employees on different profiles, a dated transfer between profiles, an assignment ending at midnight, and a 10:00 PM-3:00 AM shift crossing the assignment or rule-version boundary.

**Resolution precedence to document in the employer UI:** employee assignment → organization default profile → blocking exception when no reviewed rule version can be resolved. Work location or payroll region may be added as a future assignment scope after the employee-level model is stable; it should not silently override an explicit employee assignment.

### 11.3 Employer workflow

- [x] Add employer Payroll navigation, a filtered/paginated payroll run list, setup, employee pay profiles/rates, holiday calendar, run creation, run detail, review, finalization, void, and finalized CSV export.
- [x] Show run totals, itemized employee lines, source timesheets, exceptions, prior previews, and review/finalization evidence.
- [x] Add controlled manual earnings, deductions, employer contributions, allowances, reimbursements, and corrections with amount, effective date, and source/reason.
- [x] Require exceptions to be corrected/recalculated or explicitly resolved with evidence before review; link manual premium lines to the exception they address.
- [x] Use confirmation dialogs for finalization and voiding; retain actor, timestamp, reason, and audit history.
- [x] Scope payroll pages and actions to the employer's organization. Pagination and filters are available for payroll runs and employee profiles.
- [x] Show a live payroll-readiness checklist for reviewed rules, employee profiles/rates, and the current-year holiday calendar; add pay-frequency-aware period shortcuts, filtered run summaries, explicit exception links, and setup-aware empty states.
- [ ] Add a pre-creation eligibility/cutoff preview and a more explicit payroll review step that supports separate preparer and reviewer accounts when the product's account model permits them.
- [ ] Add automated tests for permissions, tenant boundaries, duplicate requests, concurrent run creation, reconciliation, and immutable finalized records.

### 11.4 Employee statements, exports, and reporting

- [x] Add employee-only finalized payroll history and payslip detail. Employees can access only their own finalized statements.
- [x] Show pay dates, periods, work time, rates, itemized earnings/deductions, employer contributions, gross, and net amounts.
- [x] Provide a printable HTML payslip that can be printed or saved as PDF from the browser.
- [x] Provide a finalized-run CSV export with payroll frequency, itemized totals, formula-injection protection, and organization-scoped access.
- [x] Reconcile each statement's gross, deductions, employer contributions, and net totals against its itemized lines before review/finalization.
- [ ] Implement jurisdiction-required payslip layout, periodic/year-end summaries, and filing exports after legal/accounting requirements are validated.
- [ ] Define and implement approved accounting exports. No bank file, banking identifiers, or payment-provider workflow is included.

### 11.5 Security, audit, and rollout

- [x] Scope employer data by organization and employee statements by the signed-in employee.
- [x] Audit payroll rule/profile changes, rates, run creation/recalculation/review/finalization/voiding, adjustments, exceptions, exports, and employee statement access.
- [x] Keep payroll identifiers minimal; the current implementation does not collect tax IDs or banking details.
- [ ] Document retention, correction, export, backup/restore, and payroll operator procedures for the Philippines.
- [ ] Run automated payroll tests and independently reconcile reference scenarios with a qualified reviewer.
- [ ] Run at least two shadow payroll cycles against the current payroll process, address differences, and obtain written legal/accounting sign-off before paying through these outputs.
- [ ] Pilot with a limited organization, rollback/correction plan, and employer/employee training.
- [x] Document the current limits: hourly PH/PHP foundation only, reviewer-configured rules, manual statutory items, printable HTML slips, CSV export, and no fund movement.

Payroll is not ready to be treated as a legally compliant payroll product until the open research, validation, automated coverage, shadow reconciliation, and sign-off tasks above are complete.

---

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
- [ ] Employee pay profiles, reusable payroll rule profiles, and employee assignments are effective-dated, jurisdiction-approved, and changes cannot rewrite finalized payroll.
- [ ] Employees can inherit the organization default rule profile or use a non-overlapping dated override; payroll explains and snapshots the resolved profile and rule version for every statement.
- [ ] Payroll runs include only eligible approved timesheets and show itemized regular pay, applicable premiums, deductions, gross, net, and exceptions.
- [ ] Overnight work is split and valued using the approved local payroll rules, including night differential only where configured and legally validated.
- [ ] Employers can review, approve, finalize, and audit reproducible payroll runs; corrections use an adjustment/off-cycle process.
- [ ] Employees can securely view their own finalized payslips, and authorized employers can export reconciled payroll totals.
- [ ] Payroll calculations pass reviewed reference scenarios, security/tenant-isolation tests, and a successful two-cycle shadow reconciliation.
- [ ] The release's direct-payment boundary is documented; no funds are transferred unless a separately approved payment integration is implemented.
- [ ] The desktop employer workflow and mobile employee workflow are accessible and usable.
- [ ] The deployed app has HTTPS, secure production settings, database backups, and an operator runbook.
