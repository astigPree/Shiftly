# Shiftly: complete project context and progress

**Snapshot date:** October 8, 2026, Asia/Manila  
**Purpose:** A standalone handoff for ChatGPT or another collaborator who has not seen the repository or development conversation.  
**Repository inspected:** C:\Users\63948\Desktop\SAAS\Shiftly  
**Current stage:** Attendance and timesheet application with an expanded payroll foundation and a biometric attendance pilot.

This document describes the project, decisions, implementation, and remaining work. It is context for discussion; uploading it does not authorize changes to an application, database, hardware device, or production environment.

The source code, route definitions, dependency manifests, implementation plans, and existing verification records were inspected for this snapshot. Test results below are dated records from earlier work. A new application test suite and real-device pilot were not run while preparing this document. No credentials, government identifiers, fingerprint templates, production employee records, or account passwords are included.

## 1. Start here: what Shiftly is and where we are

Shiftly is a web application for employers to manage employees, assign schedules, monitor attendance, review timesheets, prepare payroll, and export results. Employees can view their schedules, record attendance where web clocking is permitted, review their timesheets, and see finalized payroll statements.

The product began as an attendance and timesheet MVP and has expanded into:

- Philippine/PHP payroll with dated compensation, reusable components, rule profiles, reviewed period inputs, exceptions, statements, and finalization.
- A run-level statutory assessment workspace that reduces repeated employee-by-employee review.
- Excel payroll workbooks grouped by Regular, Probation, Part-time, and Other.
- ZKTeco F7 fingerprint attendance on the office network.
- Provisional biometric activity so a first imported scan can appear immediately on employee and employer attendance screens.

The project is an implemented application, not only a specification. However, implementation does not mean that every proposed phase is finished or that production release has been approved.

The latest completed feature work in this conversation is provisional biometric attendance. The current focus is manual confirmation of the real terminal workflow, followed by remaining reliability and payroll work.

The main unresolved areas are:

1. A known statutory review validation failure in the older individual-review path.
2. Biometric hardening beyond the normal first-scan and reviewed-application path.
3. Real F7, multiple-terminal, scheduler, and deployment acceptance evidence.
4. Later statutory automation, batch import, coverage setup, and obligation posting.
5. Alignment of older documentation with the current code and runtime.

There is no reliable overall completion percentage. The product scope grew during development, and many older checklists contain both implemented and still-open items. The feature matrix below is more useful than a percentage.

## 2. Product goals and user decisions

### 2.1 Business problem

The intended workflow replaces scattered spreadsheets, manual logs, and repeated data entry with a traceable chain:

~~~text
Employee setup
  -> Schedule
  -> Attendance evidence
  -> Completed attendance
  -> Timesheet review
  -> Approved payroll inputs
  -> Payroll draft and review
  -> Finalized statements and exports
~~~

The initial target is a small or growing organization, approximately 5-200 employees. This is a target market and design goal; a measured 200-employee acceptance result has not been established.

### 2.2 Roles and tenancy

- There are two application roles: EMPLOYER and EMPLOYEE.
- Each organization has one employer owner in the current account model.
- The owner manages the organization's employees and records.
- An employee may have a profile before activating a user account.
- Employee access is provisioned through employer invitation and activation.
- Employees access their own work and finalized statements.
- Business queries and actions are scoped to the organization.

Multiple employer reviewers, supervisor permissions, cross-organization membership, and a complete HRIS are not current completed features.

### 2.3 Explicit biometric requirements

The user confirmed these requirements:

| Decision | Agreed behavior |
| --- | --- |
| Device | ZKTeco F7 using fingerprint scans |
| Network | Shiftly and the devices run on the same office network |
| Event meaning | The terminal supplies timestamps, without reliable clock-in, break, or clock-out labels |
| Breaks | Flexible breaks; employees scan when leaving and returning |
| Multiple terminals | One employee can have different terminal user IDs on several terminals |
| Enforcement | Biometric attendance applies when the employee has at least one current eligible terminal assignment and organization biometric settings are enabled |
| Employee fallback | Biometric-required employees do not use employee web clock controls; the employer handles missed attendance |
| Sync interval | Configurable, default 120 seconds |
| First scan | Show provisional working activity immediately after successful import and matching |
| Attendance application | The employer reviews a complete projection before applying it to attendance |

Employee login is useful for viewing the employee screen. It is not needed for the employee's fingerprint scan to be imported and matched.

### 2.4 Payroll decisions

- Payroll uses PHP amounts and Philippine employer-reviewed rules.
- Payroll run type and employee classification are separate concepts.
- A Regular run is a scheduled payroll run. An Off-cycle run is a linked correction or adjustment.
- Employee export classifications are REGULAR, PROBATION, PART_TIME, and OTHER.
- The current profile field permits one classification value at a time. It does not independently represent both part-time work arrangement and probationary tenure.
- Classification does not establish statutory coverage or infer legal amounts.
- Hourly calculations and a reviewed daily-register workflow exist.
- Monthly and mixed pay-basis metadata exist, but arbitrary monthly conversion formulas are not automatically inferred.
- Employer contributions are separate from employee deductions and do not reduce employee net pay.
- Finalized data is preserved; later changes use reviewed correction workflows.
- The Excel export grew from four sheets to eight sheets to include Part-time and Other.

## 3. Implementation status matrix

**Implemented** means code and normal application surfaces exist. **Partial** means only some of the plan exists. **Schema only** means a model is present but the complete business workflow is missing. **Verification pending** means the feature needs further proof before release.

| Area | Current status | What exists / what remains |
| --- | --- | --- |
| Authentication and invitations | Implemented | Email login, employer signup, roles, employee activation, password reset |
| Organization settings | Implemented | Name, timezone, owner relationship, profile preferences |
| Employee management | Implemented | Create, search, filter, edit, deactivate/reactivate, profile, invitation handling |
| Scheduling | Implemented | Dated shifts, overnight support, validation, editing, cancellation, batch creation |
| Employee web attendance | Implemented | Clock in, flexible breaks, clock out, live display, server validation |
| Employer attendance entry/correction | Implemented | Reasoned manual entry and separate correction history; finalized payroll locking |
| Timesheets | Implemented | Calculation, generation, pending/review states, approval/rejection, own-record visibility |
| Reports | Implemented | Attendance, employee hours, timesheets, activity log, timesheet CSV |
| Payroll foundation | Implemented with release gates | Draft/review/finalized lifecycle, effective inputs, exceptions, snapshots, off-cycle workflow |
| Hourly/daily compensation and components | Implemented | Dated compensation, daily reviewed inputs, dated employee component assignments |
| Monthly payroll conversion | Partial | Metadata exists; approved conversion rules and full calculation behavior remain |
| Statutory bulk review | Partial plan delivery | Phase 0/1 assessment generation and bulk review exist; import and automatic calculations remain |
| Individual statutory review compatibility | Known defect | Creating a REVIEWED assessment before reviewer/fingerprint fields are populated can fail |
| Employee statutory coverage/payment/obligations | Schema foundations | Models exist; full coverage setup, payment workflows, and repayment posting are incomplete |
| Payroll CSV/XLSX | Implemented | Finalized exports; XLSX includes all four classification groups and their payslips |
| Biometric device administration | Implemented | Terminal setup/edit, tests, user sync, punch sync, mapping, issues, sync history |
| Biometric provisional attendance | Implemented normal path | First-scan state, collecting state, time-based closure, review page, explicit application |
| Biometric advanced recovery and scale | Partial / verification pending | Ambiguity, stale reviews, policy changes, mapping closure, audit completeness, hardware and load checks remain |
| UI consistency work | Implemented changes; ongoing review | Shared navigation style, contextual hierarchy, modal forms, readable actions and validation |
| Deployment | Configuration exists; acceptance pending | Docker, PostgreSQL, Gunicorn, Nginx, health checks, TLS configuration; operating proof and restore rehearsal incomplete |
| Statutory legal sign-off and payment transfer | Not implemented/approved | No automatic filing, remittance, banking transfer, or legal approval claim |

## 4. Technical architecture

### 4.1 Stack

Shiftly is a modular Django monolith with server-rendered templates, vanilla CSS, and vanilla JavaScript.

| Component | Current repository evidence |
| --- | --- |
| Python target | 3.12 in .python-version and Dockerfile |
| Existing local virtual environment | Python 3.11.9, read on October 8 |
| Django | 5.2.17 in requirements/base.txt and the existing virtual environment |
| Database | SQLite when DEBUG is true; PostgreSQL when DEBUG is false |
| Frontend | Django templates, CSS, JavaScript, shared components |
| Excel generation | openpyxl 3.1.5 |
| Credential encryption | cryptography 44.0.2 |
| ZKTeco adapter | pyzk 0.9 |
| PostgreSQL adapter | psycopg[binary] 3.3.6 in production requirements |
| WSGI server | Gunicorn 26.2.0 in production requirements |
| Test tooling | Django tests; coverage and optional Playwright browser tests |

These are local manifest/runtime observations, not a fresh external support or security audit. Older README/tech-stack prose still describes Python 3.9 and Django 4.2. That prose is stale relative to the current manifests. The local virtual environment also differs from the Python 3.12 deployment target.

The application does not currently use React, Vue, Django REST Framework, HTMX, Celery, Redis, or WebSockets. ASGI configuration exists as a Django entry point; it does not establish a live push-update feature.

### 4.2 Request flow

~~~text
Browser form or action
  -> Django URL
  -> Authorized/scoped view
  -> Validation form and service
  -> Models and transaction
  -> Audit/state update where implemented
  -> Rendered page, redirect, download, or small JSON response
~~~

Views handle request and display concerns. Services own important transitions, calculations, effective-date resolution, imports, and review operations. Django is the authority for attendance and payroll values. Browser timers are display helpers.

### 4.3 Repository layout

~~~text
config/             Settings, routes, WSGI/ASGI, health endpoint, test settings
accounts/           User identity, authentication, dashboards, settings
organizations/      Organization ownership and timezone rules
employees/          Employee profiles and invitation lifecycle
schedules/          Dated shifts and scheduling services
attendance/         Sessions, breaks, corrections, dashboards, clock actions
timesheets/         Calculations, generation, review decisions
payroll/            Compensation, rules, runs, statutory review, exports
biometrics/         F7 integration, identities, sync, evidence, projections, issues
reports/            Workforce reports and timesheet CSV
audit/              Append-only audit model and record_event service
templates/          Employer/employee layouts, pages, shared components
static/css/         Shared and page styles
static/js/          Dialogs, overflow menus, timers, previews, review UI
docs/               Plans, scenarios, audits, verification, this handoff
tests/              Model, service, view, scenario, and optional browser tests
deploy/             Initialization, health check, Nginx/Gunicorn configuration
scripts/            Development seeding and Docker secret setup helpers
~~~

### 4.4 Data relationships

~~~text
User (employer) -> Organization
Organization -> Employee -> optional User (employee)
Employee -> Shift
Shift -> AttendanceSession -> BreakSession
AttendanceSession -> AttendanceCorrection history
Shift/AttendanceSession -> Timesheet -> TimesheetApproval

Organization -> PayrollSettings and PayrollRuleProfile
PayrollRuleProfile -> PayrollRuleSet versions
Employee -> EmployeePayProfile and dated compensation/component/rule assignments
PayrollRun -> PayrollRunEmployee scope -> PayrollStatement
PayrollStatement -> PayrollLine, PayrollTimeEntry, PayrollStatutoryAssessment
PayrollRun -> PayrollException and PayrollCalculationSnapshot

Organization -> AttendanceDevice -> DeviceIdentity
DeviceIdentity -> dated DeviceIdentityAssignment -> Employee
AttendanceDevice -> DeviceSyncRun -> BiometricPunch
Shift -> BiometricAttendanceProjection <- matched BiometricPunch associations
BiometricAttendanceProjection -> optional materialized AttendanceSession
BiometricPunchIssue -> device, punch, employee, and/or projection context
~~~

Many business relationships use PROTECT to retain work and financial history. AuditEvent blocks updates/deletes through its model/queryset API. Raw biometric timestamp evidence is preserved by the implemented workflows, while assignment and projection associations can be populated or updated. This is not a claim that every table has database-enforced append-only protection.

## 5. Accounts, employees, scheduling, and attendance

### 5.1 Account and employee lifecycle

The employer signs up and creates an organization, then adds employees. Employee codes are unique inside the organization. Email normalization and case-insensitive uniqueness are implemented in the account/employee models.

Invitation records support employer-created activation. The employee establishes their password through the invitation process. Employees with history are deactivated rather than destructively deleted.

The ordinary employee profile at /employees/<id>/ focuses on workforce information, schedules, attendance, and timesheets. Payroll configuration is a separate page at /payroll/employees/<id>/. Earlier scenario instructions confused these two surfaces; this distinction matters when giving users navigation instructions.

### 5.2 Timezones and schedules

- Datetimes are timezone-aware, with UTC as the application storage baseline.
- Organization-local dates control many attendance and weekly report boundaries.
- Payroll uses employee work timezone when configured, otherwise organization timezone.
- Users may have preferred display timezone settings.
- Organization timezone changes are restricted after the first shift.
- Employee payroll timezone is restricted when finalized payroll history exists.
- Shifts contain a local work date, scheduled start/end instants, a break allowance, and Scheduled/Cancelled status.
- Overnight shifts can end on the following local date.
- Creation/edit services check employee ownership, overlap, ordering, and existing attendance.
- Scheduling changes trigger biometric rematching of affected scans.

The scheduled break allowance is not a fixed lunch timetable. Actual recorded breaks determine time deducted.

### 5.3 Web attendance

For employees permitted to use web clocking:

1. View the assigned shift.
2. Clock in within the permitted window.
3. Start and end one or more unpaid breaks.
4. Clock out.
5. Review the generated timesheet.

The standard early web clock-in allowance is 30 minutes. The server validates ownership, shift state, active employee status, open-session transitions, and biometric restrictions.

An open session after scheduled end is flagged as missing clock-out. It does not become a completed timesheet simply because the scheduled end passes.

### 5.4 Employer entry and corrections

Employers can record a complete missed attendance record with clock-in, clock-out, breaks, and a reason. The source identifies employer manual entry.

Corrections are separate AttendanceCorrection records. The effective-attendance service reads the original data plus the latest correction instead of overwriting the original evidence. Timesheet quantities can be recalculated and return to review. Attendance already included in finalized payroll is protected.

This correction capability was added after the original MVP. Older documents saying that employer corrections do not exist are no longer an accurate description of the code.

### 5.5 Timesheet calculation and review

The calculation service validates employee/organization consistency, completed clock-out, break ordering, break boundaries, and overlapping breaks.

Whole-minute values are derived from elapsed instants:

- Scheduled minutes: scheduled span less scheduled break allowance.
- Break minutes: actual completed break duration.
- Worked minutes: actual clocked span less actual completed breaks.
- Payable minutes: worked minutes in the current attendance calculation.
- Late minutes: positive clock-in delay relative to scheduled start.
- Undertime minutes: positive early departure relative to scheduled end.

Timesheet calculation floors whole-minute quantities. Some dashboard lateness display uses rounding up, so a short positive delay may display differently from floored timesheet minutes. Do not assume all visual and calculation labels use the same rounding.

Clock-out or reviewed biometric application creates one timesheet per shift. It is Pending unless a consistency problem requires Needs Review. Approval requires Pending. Rejection requires an explanation and is allowed for Pending or Needs Review.

Payroll time comes from approved eligible records, not from a live browser timer or provisional biometric duration.

## 6. Payroll foundation

### 6.1 Setup and effective inputs

Payroll setup includes country/currency/frequency, named rule profiles, dated rule versions, review evidence, and holidays.

An employee pay profile contains classification, primary pay basis, work location, wage region, work timezone, rest day, eligibility/reviewer confirmations, and inclusion in payroll.

Dated compensation resolves hourly/daily inputs while preserving compatibility with legacy hourly-rate records. Reusable component definitions support earning, deduction, and employer contribution kinds. Employee component assignments define amounts, effective dates, and a basis such as per payroll period, worked day, or payable hour.

PayrollPeriodInput supports reviewer-entered daily-register quantities and provenance. Monthly compensation metadata exists, with conversion deliberately unresolved until an approved rule is supplied.

Rule resolution follows:

~~~text
Effective employee rule assignment
  -> Organization default rule profile
  -> Effective reviewed rule version
  -> Blocking exception if usable rules cannot be resolved
~~~

### 6.2 Run lifecycle

~~~text
DRAFT -> IN_REVIEW -> FINALIZED
             |
             -> DRAFT for further changes

Eligible runs may be VOIDED with a reason.
Post-finalization correction uses a linked OFF_CYCLE run.
~~~

The run contains its employee scope, period, pay date, currency, timezone, frequency snapshot, review revision, and history. The creation interface supports all active eligible employees or selected employees.

Recalculation replaces generated lines while preserving manual adjustments and earlier calculation previews. Statements/time entries retain calculation context. Review revisions and fingerprints help reject stale statutory submissions.

Regular periods are frequency-validated:

| Frequency | Required period |
| --- | --- |
| Weekly | Monday through Sunday |
| Semi-monthly | First through 15th, or 16th through month end |
| Monthly | First through the actual last calendar day |

Pay date must be on or after period end. July 1-July 30 is not a valid monthly July period; July ends on the 31st.

### 6.3 Calculations and review gates

The implemented foundation calculates configured base pay, overtime premiums, ordinary night differential, reviewed day/rest/holiday premiums, and recurring components from approved inputs.

It uses decimal monetary values and explicit rounding, not browser arithmetic. Missing rates, unreviewed rules, ineligible inputs, missing review evidence, premium ambiguity, and stale statutory treatment can block review/finalization.

Manual adjustments support reviewed bonuses, allowances, reimbursements, withholding/deductions, employer contributions, and overrides. Their existence does not establish automatic statutory calculation.

Gross, deductions, net, and employer contributions must reconcile to statement lines:

~~~text
Employee net = gross - employee deductions
Employer contributions are separate employer costs
~~~

Finalization makes statements available to the employee and makes finalized CSV/XLSX export available. Finalization records an application review action, not payment transfer.

### 6.4 Statutory review at scale

The original workflow required repeated manual lines and four agency reviews per employee. For 200 employees this could require approximately 800 employee-agency reviews, plus employee and employer line entry.

The delivered bulk workflow includes:

- One durable PayrollStatutoryAssessment per employee statement and agency.
- Agencies: SSS, PhilHealth, Pag-IBIG, and withholding tax.
- Idempotent generation from existing unambiguous reviewed manual lines.
- Filtered/paginated queue by employee, agency, status, and source.
- Select visible or select all matching filters.
- Shared registration, treatment, calculation source, review note, and follow-up evidence.
- Ready line confirmation and explicit zero/other-cutoff/not-applicable treatments.
- Individual exception review.
- Revision and input fingerprint checks.

Assessment states include Proposed, Ready, Needs attention, Reviewed, and Review again/Superseded.

Selecting all matching does not calculate missing amounts or make exception rows Ready. A queue with zero Ready rows can only proceed after valid line/evidence setup or an explicit supported treatment. Missing registration is not an exemption.

The implementation plan has delivered the initial assessment/bulk-review phases. These later phases remain:

- Multi-row adjustment entry and CSV/XLSX import with preview/validation.
- Full employee statutory coverage setup and bulk coverage assignment.
- Approved agency rule-table management and automatic calculators.
- Further stale-review explanations, exception recovery, and scale evidence.

EmployeeStatutoryCoverage and StatutoryRuleVersion are foundations, not proof that the employee profile currently has a complete agency setup screen.

### 6.5 Payment and obligation models

EmployeePaymentMethod, EmployeeObligation, and EmployeeObligationTransaction exist in the schema. They establish a place for effective payment instructions and obligation history.

There is not yet a complete normal application workflow for bank payments, loan/cash-advance balance administration, prioritized repayment proposals, or exactly-once posting from finalized payroll. Do not describe these model names as completed financial features.

### 6.6 Known statutory compatibility defect

The previously observed error is:

~~~text
A reviewed assessment requires reviewer evidence and a current input fingerprint.
~~~

The current source still shows the underlying sequence in payroll/statutory.py:

1. The legacy individual review path calls get_or_create with status REVIEWED.
2. PayrollStatutoryAssessment.save calls full_clean.
3. The newly created row has not yet received reviewed_by, reviewed_at, and input_fingerprint.
4. Validation fails before the later assignments populate those fields.

This explains recorded failures in payroll scenario tests and one view test. The generated bulk-review path exists, but compatibility with a first individual review still requires correction.

The future fix should construct the assessment with all required evidence before saving it as Reviewed, or create it in a valid non-reviewed state and transition it atomically. New regression coverage should exercise a first review when no assessment row exists.

## 7. Finalized payroll exports

### 7.1 Excel workbook

The current XLSX builder is payroll/exports.py and uses openpyxl. It emits eight sheets:

| Payroll register | Payslip sheet |
| --- | --- |
| Regular | Payslip Regular |
| Probation | Payslip Probation |
| Part-time | Payslip Part-time |
| Other | Payslip Other |

Registers include employee identification, compensation/rule summaries, named earning categories, statutory and other deductions, gross/net, and employer contributions. Payslip sheets contain printable employee blocks. The builder adds formatting and print-oriented layout.

### 7.2 Historical snapshot rules

The export reads finalized statement snapshots and saved lines. It does not recalculate payroll or infer historical classification from today's profile.

Older finalized statements may lack the classification needed for XLSX grouping. Changing the current profile does not repair an old immutable statement. Newly calculated drafts capture the classification before review/finalization.

The original export supported only Regular and Probation; PART_TIME caused a grouping error. The implemented expansion now accepts all four configured classifications. Missing or unknown historical values remain a legitimate compatibility blocker.

CSV is also finalized-only and uses the finalized export data. Formula-like user text is escaped for spreadsheet safety.

### 7.3 Limits

- XLSX is an output workbook, not a workbook-import feature.
- No bank transfer, remittance, or accounting integration is triggered.
- The legacy reference .xls workbook was business-process evidence, not an authoritative legal formula source.
- Separate absence/undertime money columns in the current builder are zero placeholders; those reductions are reflected in the configured paid quantities rather than fabricated independent deductions.
- Print layout, large populations, classifications, line reconciliation, and historical compatibility need ongoing acceptance coverage.

## 8. Biometric attendance implementation

### 8.1 Hardware boundary and data

The adapter reads user identities and attendance timestamps from a ZKTeco F7, using the configured address/port/timezone and optional communication password. The application does not enroll fingerprints.

DTOs isolate the rest of Shiftly from the vendor library:

- DeviceInfo: firmware, serial, model.
- DeviceUser: terminal ID and display metadata.
- DevicePunch: terminal ID, timestamp, source timezone/context, optional record ID and payload.

The import path does not intentionally ingest fingerprint templates or images. Terminal credentials are encrypted. A production encryption key must be configured and preserved.

### 8.2 Main models

| Model | Responsibility |
| --- | --- |
| OrganizationBiometricSettings | Enabled state and sync/matching/duplicate policy |
| AttendanceDevice | Terminal configuration, health, last sync, encrypted credential, lock |
| DeviceIdentity | A terminal-scoped user ID |
| DeviceIdentityAssignment | Historical link from terminal identity to employee |
| DeviceSyncRun | Durable test/user/punch operation result and sanitized diagnostics |
| BiometricPunch | Imported timestamp evidence and mapping/projection associations |
| BiometricAttendanceProjection | Candidate evidence for one shift, live state, derived breaks, application result |
| BiometricPunchIssue | Unmapped, no-shift, ambiguity, incomplete, late, conflict, or operational issue |

One employee can hold multiple assignments, one for each relevant terminal identity. Assignments are effective-dated; historic scans retain their original association.

### 8.3 Sync and connection handling

The device page supports Add terminal and Sync settings dialogs, terminal editing, Test connection, Sync users, Sync scans, Map IDs, View scans, issue review, and recent operation history.

Terminal actions are grouped in a three-dot menu. Duplicate setup cards were removed after the header buttons began opening dialogs.

Typed errors identify configuration, credential, adapter, network reachability/timeout, authentication, protocol, payload, lock, database, and unexpected internal failures. Operations retain durable success/partial/failed/skipped history and release the per-device lock after completion/failure.

Connection and error-handling code is present. Actual firmware behavior, unavailable-device recovery, and production scheduler proof remain acceptance work.

### 8.4 Current default policy

| Setting | Default |
| --- | ---: |
| Sync interval | 120 seconds |
| Early candidate allowance | 30 minutes |
| Post-shift capture allowance | 240 minutes |
| Rapid duplicate window | 60 seconds |

These values are configurable. Device sync interval can override the organization default.

An employee is biometric-required when active, biometric settings are enabled, and at least one currently effective assignment belongs to an active terminal. Terminal health Offline does not itself restore employee web clocking.

### 8.5 Evidence matching and provisional states

~~~text
F7 timestamp
  -> Imported BiometricPunch
  -> Effective employee mapping
  -> Exactly one scheduled-shift candidate
  -> BiometricAttendanceProjection
  -> Employer review/application
  -> AttendanceSession + BreakSession + pending Timesheet
  -> Normal approval and payroll workflow
~~~

Candidate matching uses UTC start/end bounds, including early and post-shift allowances. It supports matching an overnight shift without relying only on the scan's calendar date. The initial resolver creates an issue if there is no candidate or more than one.

Projection status and presentation live state are separate:

| Condition | Lifecycle | Live/display state | Attendance effect |
| --- | --- | --- | --- |
| First effective matched scan before close | COLLECTING | WORKING / Working biometric provisional | No session or timesheet |
| Later scans before close | COLLECTING | AWAITING_NEXT_SCAN | No assumed break/clock-out |
| Valid even scan count after close | READY | READY_FOR_REVIEW | Employer application required |
| Incomplete sequence after close | NEEDS_REVIEW | NEEDS_REVIEW | Issue; no automatic attendance |
| Employer applies valid sequence | MATERIALIZED | MATERIALIZED | Attendance and timesheet generated |
| Existing attendance conflicts at application | CONFLICT | Conflict lifecycle | Existing session preserved |

The first scan becomes visible after a successful sync and page refresh. It is not a push notification or an update supplied by runserver in the background.

The employee screen shows provisional elapsed time, first/latest scan, terminal name, and guidance. The employer monitor keeps provisional activity separate from confirmed on-shift counts. The imported scan view links to an employer projection review page.

### 8.6 Pairing and closure

After the candidate window closes, a complete even-numbered sequence is interpreted as:

~~~text
First scan                -> Clock-in
Interior scan pairs       -> Flexible breaks
Last scan                 -> Clock-out
~~~

For example, 09:00, 12:05, 13:01, 18:02 means one completed attendance candidate with a 12:05-13:01 break.

With the default 240-minute capture allowance, an 18:00 shift closes at 22:00. A development pilot can configure a shorter reviewed capture window for testing.

Reconciliation preserves raw events and builds an effective list by excluding certain rapid scans on the same device and identity. That duplicate suppression is separate from import idempotency, which prevents the identical terminal record from being inserted again.

Refresh occurs after punch sync and from the management command. The projection detail also offers a manual Refresh projection action. Schedule creation/update and mapping backfill invoke rematching services.

### 8.7 Development scheduling

~~~powershell
# From the Shiftly repository, in one terminal:
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000

# Import now in a second terminal, or use Sync scans in the UI:
.\.venv\Scripts\python.exe manage.py sync_biometric_devices --force

# Restrict an import to one configured terminal:
.\.venv\Scripts\python.exe manage.py sync_biometric_devices --device <DEVICE_ID> --force
~~~

Without --force, the command respects effective due intervals. An external scheduler must invoke it periodically. The command is not a continuously running worker, and runserver alone does not schedule it.

The existing Docker Compose files do not define a biometric scheduler service. Office deployment must provide both LAN reachability and a scheduled invocation in the correct application environment.

### 8.8 Late evidence

New eligible evidence discovered after a projection is applied can be attached and flagged as Late evidence. The materialized attendance result is not recomputed by that path. This behavior has a targeted regression test.

This protection is scoped to eligible evidence in the projection's candidate range. It does not prove all later-time events, every finalized-payroll correction policy, or every source conflict has a complete recovery workflow.

### 8.9 Remaining biometric hardening

The provisional plan has a normal-path implementation, but some detailed plan requirements are not complete. The following are source-inspection findings on October 8, not new hardware-test results:

| Finding | Why it matters / next work |
| --- | --- |
| Apply uses persisted READY state without a submitted review fingerprint or fresh evidence check | Add stale-review protection covering evidence, shift/policy changes, and relevant locks before application |
| Effective scan gathering takes all employee punches in a shift window | Ensure each punch has exactly one authoritative eligible shift resolution; avoid consuming ambiguous evidence when candidate windows overlap |
| Projection fingerprint contains shift ID, punch IDs, and policy values | Include relevant shift time/employee/mapping inputs so changes can reliably invalidate a previous review |
| Conflicting application returns the existing session; the view still reports application success | Return an explicit conflict outcome and show an accurate message; maintain consistent lifecycle/live state |
| Provisional employee timer sends elapsed base seconds plus a scan timestamp to the shared JS timer | The JS adds elapsed time again; verify and correct the timer anchor before claiming accurate live duration |
| Ready/Needs review projection states are not handled as fully as collecting states on employee/daily dashboard screens | Present awaiting review and safe issue guidance; avoid misleading late/absent labels |
| Derived break times are displayed by slicing ISO strings in the review template | Convert to the intended work timezone and show date boundaries explicitly |
| Raw timeline identifies all entries as Immutable without per-event effective/duplicate reason | Add the raw-versus-effective explanation promised in the plan |
| Mapping creation/backfill exists; full end/reassign controls and all policy-change hooks are incomplete | Complete lifecycle UI, reprocessing behavior, and issue closure |
| No dedicated dry-run projection backfill command was found | Add planned pilot rebuild/reporting and audit evidence without creating fictional attendance |
| The due refresh sweeps collecting rows and checks close time in Python | Use bounded/indexed queries and tenant-aware scope; an index alone does not establish scale performance |
| Reprocessing one employer projection also calls the global due sweep | Restrict manual actions to authorized organization scope; retain a separate system-wide scheduled sweep |
| Dedicated reconcile/materialize audit events are not consistently wired | Add explicit review/application/state-change history; sync logs alone are not a complete audit trail |

These gaps are reasons to continue the pilot and hardening work. They do not erase the delivered first-scan feature, but they prevent treating every definition-of-done item as proven.

## 9. Reports and interface conventions

The report page provides four views under /reports/:

- Attendance: date, employee, and attendance status.
- Employee hours: organization-local weekly summaries.
- Timesheets: filtered records and quantities.
- Activity log: organization audit history.

The timesheet CSV endpoint is /reports/timesheets.csv. There is no separate completed API/reporting service.

The UI uses an employer sidebar/topbar and a simpler employee layout. The design guide favors white surfaces, pale slate backgrounds, blue interactive accents, text plus status color, compact forms/tables, and visible keyboard focus.

The user requested the report navigation style as the shared design reference: white bordered navigation surface, icons, clear active state, and blue underline. Navigation should distinguish:

1. Global module selection in the sidebar.
2. Related module pages in a contextual navigation bar.
3. Detail/edit pages using contextual back links.

A page-section anchor strip should not look like a second hierarchy of real pages. The employee payroll profile's redundant section-scrolling navigation was removed; the remaining payroll module navigation links are real destinations.

Recent UI work addressed:

- Payroll run review queue/filter presentation.
- Component edit labels and helper text.
- Misleading three-dot state toggle actions.
- Modal double scrolling.
- Centered form layout and holiday notices.
- Report navigation overflow and inconsistent tab styling.
- Field-specific attendance correction feedback.
- Styled payroll CSV/Excel export controls.
- Biometric setup progress, actions-column alignment, overflow menus, and modal setup forms.

These changes are present, but older browser results do not establish that every current screen passes at every viewport. The Reports attendance view also uses its own session-oriented data path rather than the provisional employer dashboard model; consistent biometric reporting remains review work.

## 10. Actual route map

These paths are based on current URL definitions. Replace placeholder IDs with records from the current database. Historic examples such as run 5 or employee 204 are not guaranteed to exist.

### 10.1 Shared and account pages

| Route | Purpose |
| --- | --- |
| /signup/ | Employer registration |
| /login/ | Shared login |
| /logout/ | Logout action |
| /home/ | Role-aware home |
| /settings/ | Employer organization/profile settings |
| /profile/ | Employee profile |
| /password-reset/ | Password reset |
| /invitations/<token>/ | Employee activation |
| /health/ | Health endpoint |
| /admin/ | Django administration |

### 10.2 Workforce pages

| Route | Purpose |
| --- | --- |
| /employees/ | Employer employee list |
| /employees/new/ | Add employee |
| /employees/<id>/ | Workforce profile |
| /employees/<id>/edit/ | Edit employee |
| /employees/<id>/schedules/ | Employee schedule history |
| /employees/<id>/attendance/ | Employee attendance history |
| /employees/<id>/timesheets/ | Employee timesheet history |
| /schedules/ | Employer schedules |
| /schedules/new/ | Create schedule |
| /schedules/<id>/ | Shift detail |
| /schedules/<id>/edit/ | Edit shift |
| /schedules/my/ | Employee schedules |
| /attendance/ | Employer daily monitor |
| /attendance/my/ | Employee attendance/home surface |
| /attendance/shifts/<id>/record/ | Employer missed-attendance entry |
| /attendance/sessions/<id>/correct/ | Employer correction |
| /timesheets/ | Employer timesheet list |
| /timesheets/<id>/ | Employer timesheet detail |
| /timesheets/my/ | Employee timesheets |
| /timesheets/my/<id>/ | Own timesheet detail |
| /reports/?report=attendance | Attendance report |
| /reports/?report=hours | Employee hours |
| /reports/?report=timesheets | Timesheet report |
| /reports/?report=activity | Activity log |
| /reports/timesheets.csv | Timesheet CSV download |

### 10.3 Payroll pages

| Route | Purpose |
| --- | --- |
| /payroll/ | Payroll runs/overview |
| /payroll/setup/ | Settings and rule profiles |
| /payroll/employees/ | Employee pay profiles |
| /payroll/employees/<id>/ | Employee payroll configuration |
| /payroll/employees/<id>/compensation/new/ | Dated compensation |
| /payroll/employees/<id>/components/new/ | Component assignment |
| /payroll/employees/<id>/period-inputs/new/ | Reviewed period input |
| /payroll/components/ | Shared component definitions |
| /payroll/components/<id>/edit/ | Component edit |
| /payroll/holidays/ | Holiday calendar |
| /payroll/runs/new/ | Run creation form |
| /payroll/runs/<id>/ | Run review and actions |
| /payroll/runs/<id>/statutory/ | Run-level statutory workspace link |
| /payroll/runs/<id>/statutory/<assessment-id>/ | Individual statutory exception |
| /payroll/runs/<id>/export.csv | Finalized CSV |
| /payroll/runs/<id>/export.xlsx | Finalized Excel |
| /payroll/my/ | Employee finalized payroll history |
| /payroll/my/<statement-id>/ | Own finalized printable statement |

Work details, compensation history, rule assignment, components, inputs, and audit history are sections/actions of the payroll profile. Do not invent standalone employee navigation tabs from those section names. The profile's wage-order/eligibility checklist is not a full statutory coverage administration page; run-level statutory amounts are reviewed after draft creation.

### 10.4 Biometric pages

| Route | Purpose |
| --- | --- |
| /attendance/devices/ | Biometric administration |
| /attendance/devices/<id>/edit/ | Edit terminal |
| /attendance/devices/<id>/identities/ | Terminal identity mapping |
| /attendance/devices/<id>/punches/ | Imported scan evidence |
| /attendance/devices/issues/ | Issue queue |
| /attendance/devices/projections/<id>/ | Employer projection review |

Important POST actions include:

~~~text
/attendance/devices/<id>/test/
/attendance/devices/<id>/sync-users/
/attendance/devices/<id>/sync-punches/
/attendance/devices/issues/<id>/resolve/
/attendance/devices/projections/<id>/reprocess/
/attendance/devices/projections/<id>/apply/
~~~

They are actions rather than additional page destinations.

## 11. Verification evidence and confidence

### 11.1 Recorded results

| Date/source | Result | Limit |
| --- | --- | --- |
| September 26 verification record | 98 tests recorded passing for a payroll follow-up, including targeted and browser scenarios | Predates bulk statutory, expanded export, and biometric changes |
| September 26 verification record | PostgreSQL Docker run: 63 discovered, 61 passed, two optional browser tests skipped | Historic checkpoint, not today's PostgreSQL/concurrency proof |
| September 26 UI record | 287 authenticated page/viewport combinations and ten public checks recorded | Predates several new/current screens |
| October 6 implementation session | Latest focused biometric + attendance run: 27 tests passed | Covers targeted behavior, not complete hardware/scale acceptance |
| October 6 implementation session | Django checks, Python compilation, migration consistency, and diff checks passed | Snapshot from that session |
| October 6 implementation session | Biometric migrations 0002 and 0003 applied locally | Other databases still require normal migration/deployment |
| October 6 implementation session | Broader run at that checkpoint: 116 tests, 17 errors, eight skipped | Errors were in the statutory reviewer-evidence/fingerprint path; full suite was not green |
| October 6 implementation session | View suite: nine tests, one error in finalized payslip setup through statutory review | Same compatibility issue |
| October 8 handoff preparation | Current code, routes, dependency manifests/runtime metadata inspected | No new application suite, browser pilot, migrations, or hardware operations |

Do not describe the older green runs as proof that the current full suite passes. The latest conversation includes focused passing tests and a broader known failure.

### 11.2 What targeted biometric coverage establishes

The tests include first-scan provisional state without AttendanceSession side effects, rendered employee/employer/review routes, time-based ready transition, flexible-break pairing, mapped employee web restrictions, mapping validation, durable failure handling, and late evidence after application.

Further proof is needed for concurrent PostgreSQL behavior, stale application, overlapping candidate windows, all state presentation, mapping lifecycle, scheduler operations, final-payroll scenarios, and real F7 accuracy.

### 11.3 Test locations and commands

Tests are in test_accounts.py, test_schedules.py, test_attendance.py, test_biometrics.py, test_payroll.py, test_payroll_scenarios.py, test_views.py, and test_browser.py under tests/.

config/test_settings.py provides an isolated SQLite test database and optional PostgreSQL test connection. Browser tests are opt-in through RUN_BROWSER_TESTS=1.

Example verification commands for later engineering work:

~~~powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test tests.test_biometrics tests.test_attendance --settings=config.test_settings
.\.venv\Scripts\python.exe manage.py test tests --settings=config.test_settings
~~~

They are documented commands, not claims that they were executed during this documentation task.

## 12. Manual end-to-end confirmation scenario

Use a test employee, actual enrolled terminal ID, and a controlled shift. Do not assume an old seeded user or record ID exists.

1. Employer enables biometric attendance, registers the F7, tests connection, and syncs users.
2. Employer maps the test employee's ID with an effective timestamp before the test shift.
3. Employer creates the shift and confirms there is no existing manual session.
4. Employee scans once, for example at 09:00.
5. Employer manually selects Sync scans in development.
6. Refresh employee and employer attendance pages; confirm Working biometric provisional, terminal name, and no attendance/timesheet record.
7. Scan at 12:05 and 13:01 for a flexible break, then at 18:02 for departure; sync the relevant terminals.
8. Confirm collecting state says Awaiting next biometric scan.
9. After configured candidate close, run sync/Refresh projection.
10. Review the four raw scans and derived candidate; confirm Ready for review.
11. Employer applies the reviewed sequence.
12. Confirm one completed biometric session, one break, and one pending timesheet.
13. Approve through the normal timesheet workflow.
14. Confirm approved time in a draft payroll calculation.
15. Verify first-scan/missing-scan, unmapped ID, no-shift, duplicate, manual conflict, and late-evidence cases independently.

For a 09:00-18:00 shift, default close is 22:00. A shorter configured pilot capture allowance can make the test practical. Actual scans should occur at their real timestamps; do not adjust the terminal clock on a live shared device to fabricate this sequence.

Use both terminals in the pilot when available. Their IDs must map to the same employee, and all imported evidence must match the same intended shift.

Manual confirmation remains pending until the user or an authorized tester records the observed results. The detailed biometric scenario file contains some older Product blocked notes that are now stale, so use the status explanations in this document to interpret it.

## 13. Deployment and configuration

Local development loads the repository .env without overwriting existing environment variables. Debug mode uses SQLite and normally console email. Non-debug settings require hosts and a PostgreSQL DATABASE_URL.

Important configuration names include SECRET_KEY, DEBUG, ALLOWED_HOSTS, DATABASE_URL, CSRF_TRUSTED_ORIGINS, BIOMETRIC_CREDENTIAL_KEY, email settings, and secure-cookie/TLS settings. This document intentionally omits their values.

Docker assets include:

- Python 3.12 runtime image running as a non-root application user.
- PostgreSQL 17 container and persistent database volume.
- Initialization command for migrations/static assets.
- Gunicorn web service.
- Nginx proxy/static service.
- Health checks and separate test image/configuration.
- Production TLS override and certificate mounts.
- Secret-file support for selected Django, database, and email credentials.

The biometric key is currently read from BIOMETRIC_CREDENTIAL_KEY. Compose does not explicitly wire that value or a biometric scheduler service; deployment must handle it deliberately. Debug-mode key fallback is not a production key-provisioning workflow.

Running containers on the same PC does not itself prove they can reach an office terminal. Validate the network path from the actual application/sync environment.

Production TLS, SMTP, backup/restore rehearsal, monitoring, dependency alignment, PostgreSQL race conditions, secret-key lifecycle, device access, and sync scheduling remain operational acceptance items.

No production deployment, backup restoration, or hardware command was performed to create this document.

## 14. Recent development history

The latest inspected local Git log ends at 2efb041 dated October 6, 2026. This is an inspected reference, not proof of a clean worktree or remote synchronization.

| Date | Milestone |
| --- | --- |
| September development | Core authentication, workforce, attendance, timesheets, reports, audit, and deployment configuration |
| September 26 | Payroll validation/UI checkpoint and recorded test runs |
| September 27-28 | Legacy workbook analysis; daily compensation, period input, component, classification, and schema expansion |
| October 3-4 | Application simulation/scenario work and UI correction; initial bulk statutory workflow |
| October 5 | Finalized XLSX export, expanded classification groups, statutory selection clarification, initial biometric integration |
| October 6 | Biometric UI revisions, mapping/connection recovery, provisional attendance and review/application work |
| October 7 | Manual biometric test sequence explained to the user |
| October 8 | This consolidated context and progress handoff |

The user previously requested commits/pushes and a payroll-run reset in separate turns. Their earlier authorization does not prove today's repository/remote/database state. This handoff does not assume that any particular run still exists.

## 15. Recommended next work

These priorities are recommendations from the current snapshot, not new approved implementation requests.

| Priority | Work | Evidence needed to close it |
| --- | --- | --- |
| 1 | Fix first individual statutory review creation | Targeted regression, individual/bulk compatibility, previously failing payroll scenarios |
| 1 | Finish biometric application/state integrity | Fresh evidence/revision check, consistent conflicts, unique shift ownership, tenant-scoped actions |
| 1 | Correct provisional timer and timezone/state display | Browser checks of first/later scans, overnight work, ready/review/conflict states |
| 2 | Perform real F7 end-to-end pilot | Device/user/mapping/scan/sync/review/timesheet evidence from office LAN |
| 2 | Complete recovery and audit | Mapping closure, late/out-of-window evidence, policy-change rematch, duplicate explanations, explicit review/application history |
| 2 | Reconcile documentation | Current runtime/routes/statuses in README, guides, scenarios, and verification record |
| 2 | Validate deployment/scheduler | PostgreSQL, TLS, credentials, backups/restoration, LAN connectivity, timed and overlapping syncs |
| 3 | Deliver batch statutory import/entry | Upload preview, validation, exactly-once confirmation, error export, audit |
| 3 | Build full employee coverage administration | Effective coverage UI/history, assignment, readiness, privacy controls |
| 3 | Implement adviser-approved statutory calculation | Reviewed source tables, rounding/cutoff rules, independent reference cases and sign-off |
| 3 | Finish obligations and financial operations | Repayment proposal/finalization posting and balance reconciliation; separate payment product scope |
| 3 | Measure population/terminal scale | Large queues, exports, pagination, sync duration, query counts, issue recovery and concurrency |

Automatic amounts, statutory remittance, and money movement should not be inferred from an export button, a model name, or a checked implementation-plan title.

## 16. Existing documents and how to use them

| Document | Useful content | Snapshot caveat |
| --- | --- | --- |
| SHIFTLY_PROJECT_DESCRIPTION.md | Original positioning and long-term direction | Routes and some feature boundaries predate current code |
| SHIFTLY_TECH_STACK.md | Architecture rationale and service conventions | Runtime prose is stale relative to current requirements |
| SHIFTLY_MVP_ACCEPTANCE_CRITERIA.md | Initial account/time/schedule/review rules | Later corrections, bulk payroll, and biometrics extend it |
| SHIFTLY_PROJECT_TASKS.md | Broad task history and payroll roadmap | Unchecked items can include later delivered features; confirm in code |
| SHIFTLY_PROJECT_DESIGN_SKILL.md | Design tokens, forms, accessibility, app layout | User's later requests resolve conflicts, including navigation and clock confirmations |
| SHIFTLY_GUIDE_README.md | Daily user workflows | Some statutory steps/routes need alignment |
| docs/FULL_APPLICATION_SIMULATION_SCENARIO.md | Broad manual application walkthrough | Confirm live IDs, destinations, and newer features |
| docs/PAYROLL_WORKBOOK_IMPLEMENTATION_PLAN.md | Legacy workbook analysis and daily/component/financial roadmap | Many later phases intentionally remain open |
| docs/PAYROLL_BULK_STATUTORY_WORKFLOW_IMPLEMENTATION_PLAN.md | Scale problem, assessment architecture, phased delivery | Initial phases delivered; automatic calculation/import not delivered |
| docs/PAYROLL_XLSX_EXPORT_IMPLEMENTATION_PLAN.md | Finalized workbook and classification rules | Current export code accepts all four groups |
| docs/PAYROLL_REFERENCE_CASES.md and PAYROLL_SCENARIOS.md | Synthetic arithmetic/review cases | References are not legal sign-off |
| docs/BIOMETRIC_ATTENDANCE_IMPLEMENTATION_PLAN.md | Hardware integration and user decisions | Foundation delivered; operational/pilot gates remain |
| docs/BIOMETRIC_ERROR_HANDLING_IMPLEMENTATION_PLAN.md | Mapping crash, typed errors, recovery design | Core fixes exist; deeper recovery remains |
| docs/BIOMETRIC_PROVISIONAL_ATTENDANCE_IMPLEMENTATION_PLAN.md | First-scan architecture and acceptance requirements | Title status says implemented; detailed remaining gaps are listed here |
| docs/BIOMETRIC_ATTENDANCE_END_TO_END_SCENARIO.md | Hardware/manual test guide | Some blocked notes predate delivered projection/duplicate/late-evidence work |
| docs/VERIFICATION.md and UI_REVIEW.md | Historic automated/browser/deployment evidence | Older results do not certify today's expanded feature set |

Source-inspection disagreements should be recorded, not silently resolved by assuming every checked task is current. This handoff summarizes observed behavior; it does not replace future user direction or reviewed business requirements.

## 17. Useful source starting points for a developer

| Question | Starting files |
| --- | --- |
| Who can access an object? | accounts/permissions.py; relevant scoped view/service |
| Employee invitation or activation | employees/services.py; accounts/views.py |
| Schedule validation and rematching | schedules/models.py; schedules/services.py |
| Attendance transitions/corrections | attendance/services.py; attendance/forms.py |
| Daily monitor/provisional metrics | attendance/dashboard.py; templates/attendance/list.html |
| Employee biometric display | attendance/views.py; templates/attendance/my_attendance.html; static/js/attendance_timer.js |
| Timesheet arithmetic | timesheets/calculations.py; timesheets/services.py |
| Payroll eligibility/period/rule resolution | payroll/services.py; payroll/compensation.py; payroll/forms.py |
| Statutory queue and shared review | payroll/statutory_assessments.py; payroll/views.py; static/js/payroll-statutory-bulk.js |
| Legacy individual statutory failure | payroll/statutory.py; PayrollStatutoryAssessment in payroll/models.py |
| Finalized workbook | payroll/exports.py; payroll/views.py |
| F7 network/error/import/reconciliation | biometrics/services.py; biometrics/models.py |
| Device/mapping/review actions | biometrics/views.py; biometrics/forms.py; biometrics/urls.py |
| Scheduled sync | biometrics/management/commands/sync_biometric_devices.py |
| Review page | templates/biometrics/projection_detail.html |
| New projection schema | biometrics/migrations/0002_biometricprojection_live_state.py and 0003_biometricprojection_due_index.py |
| UI conventions | templates/layouts/; templates/components/; static/css/; SHIFTLY_PROJECT_DESIGN_SKILL.md |
| Runtime/deployment | requirements/; .python-version; Dockerfile; compose*.yaml; config/settings.py; deploy/ |

## 18. Suggested message when uploading this file to ChatGPT

> This document is the current context and progress snapshot for our Shiftly project. Read it as project evidence. Explain what the product does, what we have implemented, which workflows are partial, what the known issues mean, and the most useful next steps. Distinguish delivered code, historical test evidence, source-inspection findings, and future plans. If an answer depends on code or a test result not included here, identify the missing evidence instead of assuming the feature is complete.

This file should be enough to establish the product, architecture, decisions, present feature set, recent work, and remaining priorities without uploading the complete repository or development chat.
