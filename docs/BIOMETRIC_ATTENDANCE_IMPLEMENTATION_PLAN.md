# Biometric attendance implementation plan

**Prepared:** 2026-10-05  
**Status:** In implementation — foundation and reconciliation slices delivered; real-device connectivity proof and production rollout remain gated  
**Scope:** Add ZKTeco F7 fingerprint-terminal attendance to Shiftly's existing schedule, attendance, timesheet, approval, and payroll workflow.  
**Primary problem:** Employees who have an active biometric-terminal identity should clock in, take flexible breaks, and clock out through assigned terminals instead of the Shiftly website, while employers retain a controlled, auditable fallback for missed or ambiguous scans.  
**Intended reader:** A developer or coding agent implementing and verifying one phase at a time.

## Implementation status (2026-10-05)

The first implementation slice is now present in the repository:

- `biometrics` is a tenant-scoped Django app with encrypted device credentials,
  F7 adapter boundaries, idempotent raw-punch storage, effective-dated identity
  mappings, sync history, projections, and issue records.
- Employers can open **Attendance → Biometric devices**, save the organization
  sync policy, add/edit a terminal, test it, sync users or punches, map terminal
  IDs, and resolve the initial issue queue.
- `python manage.py sync_biometric_devices` is safe to run from Windows Task
  Scheduler or another office scheduler. It respects each device's effective
  interval and uses a durable per-device lock.
- Mapped employees are blocked from web clock-in, break, and clock-out at both
  the service and UI layers. A reviewed projection can be materialized into the
  existing attendance, break, and timesheet records with source `BIOMETRIC`.

The remaining gates are deliberate: prove the adapter against the actual F7
firmware and office network, add hardware clock-drift diagnostics and richer raw
timeline review, then pilot before enabling enforcement for a wider employee
population. The application does not store fingerprint templates.

## 1. Outcome and confirmed decisions

Shiftly will support office-LAN ZKTeco F7 terminals as the primary attendance source for employees who are mapped to at least one active terminal identity.

The confirmed product decisions are:

| Concern | Decision |
| --- | --- |
| First supported device | ZKTeco F7 fingerprint terminal |
| Connectivity | Shiftly and every terminal run on the same private office network |
| Device payload | Timestamped fingerprint verification events; no reliable clock-in, clock-out, or break event type |
| Sync cadence | Configurable; organization default is every 2 minutes |
| Employee eligibility | Biometric attendance is required only while an employee has at least one active terminal identity mapping |
| Multiple terminals | One employee may hold a different terminal user ID on every device |
| Employee fallback | No employee web clock-in, break, or clock-out fallback when biometric attendance is required |
| Employer fallback | Employer may record or correct attendance, with a reason and audit trail |
| Breaks | Flexible; derived from timestamp sequences rather than a fixed lunch window |
| Payroll boundary | Approved timesheets and finalized payroll records are never silently changed by a later device sync |

The target workflow is:

~~~text
ZKTeco F7 fingerprint match
        ↓
Raw biometric punch ledger
        ↓
Per-device employee identity mapping
        ↓
Shift-aware biometric attendance projection
        ↓
AttendanceSession + BreakSession snapshot
        ↓
Timesheet review and approval
        ↓
Payroll calculation and finalization
~~~

The device performs biometric verification. Shiftly receives only the resulting terminal user ID, timestamp, terminal metadata, and optional device status fields. Shiftly must never store fingerprint templates, fingerprint images, or face templates.

## 2. Problem, non-goals, and safety boundaries

### 2.1 Problem to solve

The existing web-clock workflow requires an authenticated employee to use Shiftly for every clock-in, break start, break end, and clock-out. It cannot consume terminal evidence directly.

The F7 records only timestamped fingerprint events. It does not provide a trusted, explicit semantic label for each scan. Shiftly therefore needs to preserve the raw evidence first, then derive a reviewable work and break timeline using the employee's assigned shift.

### 2.2 Non-goals for the first release

The first release does not:

- enroll, copy, compare, delete, or otherwise manage fingerprint templates;
- push employee records or templates from Shiftly to a terminal;
- expose a terminal to the public internet;
- use a device scan as a payroll amount or statutory calculation;
- support external cloud terminals, a public webhook, or a remote-branch connector;
- infer legal break compliance from a terminal scan sequence;
- replace employer attendance corrections;
- alter approved timesheets or finalized payroll from a late sync;
- support a second vendor before the ZKTeco F7 adapter is proven.

### 2.3 Safety boundaries

1. Raw biometric punches are evidence. They are append-only and remain available after reconciliation.
2. A derived attendance result may change only while it is a biometric draft. Employer corrections remain separate, append-only records.
3. Device data never silently overwrites a manually recorded, reviewed, approved, or payroll-locked attendance result.
4. A missing scan never becomes an assumed zero-duration break or an assumed clock-out.
5. Every device, identity, raw punch, projection, issue, and sync record belongs to one organization.

## 3. Existing Shiftly foundations to reuse

The implementation should extend the existing workflow rather than create a parallel payroll path.

| Existing foundation | Relevant behavior | Planned use |
| --- | --- | --- |
| AttendanceSession | One attendance row per Shift; original clock values are intentionally immutable | Store the approved biometric attendance snapshot after reconciliation |
| BreakSession | Stores start/end intervals related to one AttendanceSession | Persist inferred, paired biometric breaks |
| AttendanceCorrection | Append-only employer correction that overlays effective attendance values | Employer-only fallback for missed scans or accepted manual/device conflicts |
| effective_attendance_values() | Central effective attendance reader used by payroll | Continue using it after biometric attendance becomes an AttendanceSession |
| Timesheet and generate_timesheet() | A completed session creates a reviewable timesheet | Generate only after a biometric projection has a valid final work interval |
| review_timesheet() | Employer approval/rejection with audit history | Keep as the payroll gate |
| payroll.services.calculate_payroll_run() | Uses approved timesheets and effective attendance values | No new biometric payroll calculator |
| Shift | Contains employee, work date, scheduled start/end, and break allowance | Resolve a terminal punch to a work date and candidate shift |
| EmployeePayProfile timezone | Provides employee payroll/work timezone, falling back to organization timezone | Resolve local device dates and overnight shifts |
| AuditEvent | Append-only human-action audit history | Record configuration, mapping, conflict resolution, and employer corrections |

The primary source files affected by later implementation are expected to include:

- attendance/models.py, attendance/services.py, attendance/views.py, attendance/dashboard.py, and attendance/urls.py;
- timesheets/services.py and relevant templates;
- employees/models.py, forms.py, views.py, and profile templates;
- schedules/models.py and scheduling UI only if biometric-specific window configuration is added;
- audit/models.py and audit/services.py;
- config/settings.py, config/urls.py, requirements/base.txt, and requirements.txt;
- a new biometrics Django app with models, services, forms, views, templates, management commands, and tests.

## 4. Product rules

### 4.1 Biometric eligibility and manual-clock policy

An employee requires biometric attendance when all of the following are true:

1. the organization biometric feature is enabled;
2. the employee is active;
3. the employee has at least one active DeviceIdentity mapping; and
4. at least one mapped device is enabled.

This is evaluated in the service layer. Hiding a website button alone is insufficient.

| Employee state | Website clock controls | Terminal scans |
| --- | --- | --- |
| No active terminal mapping | Existing website workflow remains available | Imported as unmatched or mapped evidence only |
| Active terminal mapping | Employee clock-in, break, and clock-out actions are rejected | Normal attendance source |
| Terminal mapping removed | Website clock workflow returns for future attendance | Historical raw punches remain preserved |
| Device offline | Employee remains biometric-required | Employer uses the audited fallback after confirming the issue |

The attendance service must return a specific message when it blocks an employee action:

> Biometric clocking is required for this employee. Use an assigned terminal, or ask an employer to record a verified correction.

### 4.2 Multiple terminal identities

An employee may have any number of active mappings across terminals:

~~~text
Employee: Ana Cruz
Main Entrance F7     → user ID 007
Warehouse F7         → user ID 122
Back Office F7       → user ID ANA-01
~~~

The terminal user ID is an opaque string. Shiftly must not assume it is numeric, globally unique, or equal to the employee code.

The unique identity key is:

~~~text
attendance device + terminal user ID
~~~

An employee can clock in at one terminal and clock out at another. All eligible punches from all mapped terminals contribute to the same candidate shift.

### 4.3 Timestamp-only flexible break policy

The F7 provides timestamps without dependable IN, OUT, BREAK OUT, or BREAK IN labels. The reconciliation policy must use raw event order while retaining every scan as evidence.

When a candidate shift is finalized:

1. the first effective scan becomes clock-in;
2. the last effective scan becomes clock-out;
3. scans between the first and last are paired sequentially into break intervals;
4. an unpaired interior scan becomes a review exception;
5. the actual paired break durations are passed to Shiftly's existing attendance and timesheet calculation;
6. the scheduled break allowance remains a planning value; it does not erase actual raw break evidence.

Examples:

~~~text
2 scans
09:00  clock-in
18:02  clock-out

4 scans
09:00  clock-in
12:05  break starts
13:01  break ends
18:02  clock-out

6 scans
09:00  clock-in
10:30  break starts
10:45  break ends
12:05  break starts
13:01  break ends
18:02  clock-out
~~~

While the shift is still open, Shiftly must show a provisional state rather than prematurely declare a generic scan to be a final clock-out:

~~~text
Last device scan: 12:05 PM
State: Away from work — awaiting the next biometric scan
~~~

At the close of the candidate window, an incomplete sequence becomes an employer-facing issue. Examples include one scan only, an odd number of interior scans, a scan outside the allowed work window, and a late event after the candidate was applied.

### 4.4 Duplicate and accidental scans

Raw scans are never discarded. The reconciler may exclude a likely duplicate from the effective pairing set only when it matches the configured duplicate rule. The initial default is two scans from the same device identity within 60 seconds.

The device UI must show both:

- all raw scans; and
- which scans were excluded from the effective timeline, with the reason.

An employer can override a questionable result through the existing correction flow. The correction must not mutate or delete raw device evidence.

### 4.5 Timing windows and overnight shifts

The initial configurable organization defaults are:

| Setting | Initial default |
| --- | --- |
| Sync interval | 120 seconds |
| Early clock-in window | 30 minutes before scheduled start |
| Post-shift capture window | 240 minutes after scheduled end |
| Rapid duplicate window | 60 seconds |
| Device timezone | Asia/Manila, explicitly saved per device |

The shift matching window is:

~~~text
scheduled start − early clock-in window
through
scheduled end + post-shift capture window
~~~

All device timestamps are converted from the configured device timezone to UTC immediately after import. Matching and display use the employee work timezone, falling back to the organization timezone.

For an overnight shift, a scan after midnight can still belong to the previous shift's work date when it is within the shift's configured capture window.

### 4.6 Conflicts, approval, and payroll lock

| Existing state | Biometric sync result |
| --- | --- |
| No attendance exists | Create or update the biometric projection |
| Biometric projection is still collecting | Recalculate the projection from all eligible raw punches |
| No session exists and projection is ready | Apply a biometric AttendanceSession, BreakSessions, and a pending Timesheet |
| Employer manual attendance exists | Retain raw scans and create a source-conflict issue |
| Pending biometric session needs changed values | Create a biometric reconciliation revision or employer-approved correction; do not overwrite immutable raw session timestamps |
| Timesheet is approved or rejected | Retain raw scans and create a late-evidence issue; do not alter the reviewed timesheet |
| Payroll is finalized | Retain raw scans and create a locked-attendance issue; do not alter attendance, timesheets, or payroll |

An employer resolving a manual-versus-biometric conflict chooses one explicit action:

- keep the manual attendance;
- apply a reviewed biometric correction; or
- record a separate corrected attendance value with a reason.

## 5. Architecture and network topology

### 5.1 Office-LAN deployment

The first release uses a server-initiated pull from the Shiftly application host to each F7 terminal across the private office LAN.

~~~text
Shiftly application server
        │ private office LAN only
        ├── F7 Main Entrance
        ├── F7 Warehouse
        └── F7 Back Office
~~~

Requirements:

- assign every terminal a stable private IP address;
- restrict terminal access to the Shiftly host through the office firewall;
- never publish terminal ports to the public internet;
- maintain device timezone and clock accuracy;
- configure a communication password when supported by the device;
- retain a documented device inventory with location and owner.

The F7's available TCP/IP or serial connectivity makes this approach viable, but the exact firmware and protocol compatibility must be proven against a real terminal before production work relies on the adapter.

### 5.2 Adapter boundary

Create a narrow adapter contract in biometrics/providers rather than allowing pyzk objects to reach Django models or views.

~~~python
DeviceInfoDTO(
    name,
    serial_number,
    firmware_version,
    device_time,
)

DeviceUserDTO(
    uid,
    user_id,
    name,
    privilege,
    card,
)

DevicePunchDTO(
    uid,
    user_id,
    occurred_at,
    status,
    punch,
    raw_data,
)
~~~

Suggested adapter methods:

~~~python
test_connection(device) -> DeviceInfoDTO
list_users(device) -> list[DeviceUserDTO]
list_punches(device, since=None) -> list[DevicePunchDTO]
~~~

The initial adapter can use pyzk only after the connection proof confirms that it reads users and attendance from the actual F7 firmware. The adapter must wrap vendor failures in a Shiftly-owned exception type, such as BiometricDeviceError.

### 5.3 Sync execution model

Shiftly currently has no job queue. Use a scheduler-neutral Django management command for automatic synchronization:

~~~text
python manage.py sync_biometric_devices
~~~

The office environment can run that command every two minutes through Windows Task Scheduler, a service manager, or a deployment scheduler. The command must inspect each device's effective interval and only sync devices that are due.

Employer-initiated actions use the same service layer:

- Test connection
- Sync users now
- Sync attendance now

The browser starts a server-side action. It never connects to the terminal directly.

## 6. Data model and invariants

Create a new Django app named biometrics.

### 6.1 OrganizationBiometricSettings

One row per organization.

~~~text
organization                      OneToOne Organization
enabled                           Boolean
default_sync_interval_seconds     PositiveInteger, default 120
early_clock_in_minutes            PositiveInteger, default 30
post_shift_capture_minutes        PositiveInteger, default 240
duplicate_window_seconds          PositiveInteger, default 60
created_at / updated_at
~~~

Constraints and validation:

- interval must be within an operationally safe range, initially 30–3,600 seconds;
- each window must be non-negative;
- disabled organizations must not create automatic device sessions;
- changing a default affects future synchronization, never historical attendance snapshots.

### 6.2 AttendanceDevice

~~~text
organization                      FK Organization
name                              CharField
driver                            ZKTECO_PULL
host                              GenericIPAddressField or validated hostname
port                              PositiveInteger, configurable
encrypted_password                TextField
credential_key_version            PositiveSmallInteger
timezone                          IANA timezone string
sync_interval_seconds             nullable override; inherit organization when blank
enabled                           Boolean
location_label                    CharField
status                            UNKNOWN / ONLINE / OFFLINE / DEGRADED
last_connection_at                DateTime, nullable
last_user_sync_at                 DateTime, nullable
last_punch_sync_at                DateTime, nullable
last_successful_punch_at          DateTime, nullable
last_error                        TextField
sync_lock_until                   DateTime, nullable
created_at / updated_at
~~~

Constraints:

- unique organization/name;
- unique organization/host/port;
- the port must be between 1 and 65,535;
- the device timezone must be a valid IANA zone;
- password plaintext must never be stored;
- disabled devices cannot be selected as active employee clock sources.

### 6.3 DeviceIdentity

~~~text
organization                      FK Organization
device                            FK AttendanceDevice
terminal_user_id                  CharField
terminal_uid                      CharField, nullable
display_name                      CharField
card_reference                    CharField, blank
last_seen_at                      DateTime, nullable
created_at / updated_at
~~~

DeviceIdentity represents the durable identity stored on one terminal. Keep its mapping history in a separate effective-dated assignment model:

~~~text
DeviceIdentityAssignment
organization                      FK Organization
device_identity                   FK DeviceIdentity
employee                          FK Employee
effective_from                    DateTime
effective_until                   DateTime, nullable
mapped_by                         FK User
unmapped_by                       FK User, nullable
created_at / updated_at
~~~

Constraints:

- unique device/terminal_user_id;
- each assignment, identity, employee, and organization must have the same organization;
- assignment intervals cannot overlap for the same device identity;
- resolve a mapping using the punch occurrence time, not the employee currently mapped today;
- one employee may have active mappings on many devices;
- unmapped identities remain valid and visible for employer mapping;
- never infer a mapping from a non-unique employee code or display name.

This effective-dated mapping is required when a terminal ID is reassigned. A scan from last month must remain attached to the employee who held that terminal ID last month.

### 6.4 BiometricPunch

This is the immutable raw evidence ledger.

~~~text
organization                      FK Organization
device                            FK AttendanceDevice
device_identity                   FK DeviceIdentity, nullable
identity_assignment               FK DeviceIdentityAssignment, nullable
employee                          FK Employee, nullable
terminal_user_id                  CharField
terminal_uid                      CharField, nullable
device_record_id                  CharField, nullable
source_local_timestamp            CharField
source_timezone                   IANA timezone string
occurred_at                       DateTime, stored in UTC
device_status                     CharField, blank
device_punch_type                 CharField, blank
raw_payload                       JSON
payload_hash                      CharField
dedupe_key                        CharField
sync_run                          FK DeviceSyncRun
imported_at                       DateTime
processed_at                      DateTime, nullable
projection                        FK BiometricAttendanceProjection, nullable
created_at / updated_at
~~~

Constraints and immutability:

- use a vendor transaction or record ID as the preferred deduplication key when the F7 exposes a stable one;
- otherwise derive a canonical dedupe key from device, terminal user ID, original local timestamp, normalized timestamp, status, punch type, and payload hash;
- do not collapse two potentially genuine same-second scans merely because their timestamps match;
- raw device timestamp, identity, status, punch type, and raw payload cannot be updated after insert;
- raw rows cannot be deleted through normal application code;
- mapping and processing metadata may be appended only through narrowly scoped services;
- raw payload must exclude fingerprint templates and unbounded binary data;
- employee and device identity must always belong to the same organization as the punch.

### 6.5 DeviceSyncRun

~~~text
organization                      FK Organization
device                            FK AttendanceDevice
kind                              CONNECTION / USERS / PUNCHES
trigger                           MANUAL / SCHEDULED / RETRY
state                             QUEUED / RUNNING / SUCCEEDED / FAILED / SKIPPED
initiated_by                      FK User, nullable
started_at / completed_at
records_received
records_created
records_duplicate
records_unmatched
records_issued
message
error_code
error_detail
device_time_at_test              DateTime, nullable
clock_drift_seconds              Integer, nullable
created_at
~~~

System-triggered syncs should use DeviceSyncRun for operational history. Do not weaken the existing AuditEvent actor requirement merely to represent a background worker.

### 6.6 BiometricAttendanceProjection

One mutable draft per eligible Shift. It allows repeated syncs to recompute the candidate before an immutable AttendanceSession snapshot is applied.

~~~text
organization                      FK Organization
employee                          FK Employee
shift                             OneToOne Shift
work_date                         DateField
state                             COLLECTING / AWAY / READY / NEEDS_REVIEW / APPLIED / LOCKED
effective_punch_ids              JSON or derived relation
candidate_clock_in_at            DateTime, nullable
candidate_clock_out_at           DateTime, nullable
candidate_breaks                 JSON
punch_count
effective_punch_count
input_fingerprint                CharField
last_punch_at                    DateTime, nullable
finalize_after                   DateTime
applied_session                  OneToOne AttendanceSession, nullable
calculated_at
created_at / updated_at
~~~

Constraints:

- unique shift;
- employee and organization must match the shift;
- a projection may apply to one AttendanceSession at most once;
- an applied or locked projection is never silently rewritten;
- a changed raw-evidence set after application creates an issue rather than modifying the prior snapshot.

### 6.7 BiometricPunchIssue

Use a first-class exception record instead of burying uncertainty in messages.

~~~text
organization                      FK Organization
employee                          FK Employee, nullable
device                            FK AttendanceDevice, nullable
punch                             FK BiometricPunch, nullable
projection                        FK BiometricAttendanceProjection, nullable
shift                             FK Shift, nullable
code                              UNMAPPED_IDENTITY / NO_SHIFT / AMBIGUOUS_SHIFT /
                                  INCOMPLETE_SEQUENCE / LATE_EVIDENCE /
                                  SOURCE_CONFLICT / DEVICE_CLOCK_DRIFT /
                                  OUTSIDE_WINDOW / DEVICE_OFFLINE
state                             OPEN / RESOLVED / IGNORED
summary
detail
resolved_by                       FK User, nullable
resolved_at                       DateTime, nullable
resolution_note
created_at / updated_at
~~~

Issues are employer-facing and auditable. They must contain no biometric template data or sensitive registration values.

### 6.8 Attendance source fields

Extend AttendanceSession with an additive source field:

~~~text
EMPLOYEE_WEB
EMPLOYER_MANUAL
BIOMETRIC
MIXED
~~~

Existing rows migrate to EMPLOYEE_WEB without changing timestamps or historical payroll results. A session can be labeled MIXED only after an explicit employer-reviewed source resolution.

## 7. Synchronization and device services

### 7.1 Credential handling

Add a separately managed Fernet-compatible setting:

~~~text
ZK_CREDENTIAL_KEY
~~~

Requirements:

- encrypt the terminal communication password before it reaches the database;
- decrypt only in memory during a connection attempt;
- store the key version for a future rotation path;
- fail closed in production if the credential key is absent;
- never include passwords in forms after save, logs, audit summaries, error messages, or raw payloads.

### 7.2 Connection proof

Before enabling a real device, test the actual F7 and record:

1. reachability at configured host and port;
2. connection with the configured communication password;
3. terminal name, serial number, and firmware when available;
4. terminal clock and drift from Shiftly;
5. ability to retrieve enrolled users;
6. ability to retrieve attendance transactions;
7. observed fields for user ID, UID, timestamp, status, and punch type.

The connection test must show a concise operator-safe result and retain diagnostic detail in DeviceSyncRun.

### 7.3 User synchronization

Implement:

~~~python
sync_device_users(device, actor=None) -> SyncResult
~~~

Behavior:

1. create a DeviceSyncRun in RUNNING state;
2. read users through the adapter;
3. ignore empty terminal user IDs;
4. upsert DeviceIdentity by device and terminal user ID;
5. preserve existing effective-dated assignment history;
6. refresh safe metadata such as display name, UID, card reference, and last seen time;
7. leave unmatched users visibly unmapped;
8. update device health and sync timestamps;
9. complete the sync record with counts.

The first release should require employer mapping. It must not silently link a terminal identity because its display name resembles an employee name.

### 7.4 Punch synchronization

Implement:

~~~python
sync_device_punches(device, actor=None, now=None) -> SyncResult
~~~

Behavior:

1. acquire a per-device database lock;
2. create a DeviceSyncRun;
3. download normalized terminal events;
4. interpret naive device timestamps in the configured device timezone;
5. preserve the original local timestamp and timezone, then convert and store UTC;
6. resolve a DeviceIdentity, then a DeviceIdentityAssignment, by device, terminal user ID, and punch occurrence time;
7. attach an employee only through the assignment active at that occurrence time;
8. insert raw punches idempotently using a stable device-record key when available, otherwise the canonical evidence signature;
9. mark duplicates in the sync counts without deleting evidence;
10. collect affected employee/shift candidates;
11. reconcile each affected candidate inside a transaction;
12. update device health, watermark information when supported, and sync timestamps;
13. record any unmatched, out-of-window, or ambiguous data as issues.

Repeated full reads must be safe even when the device cannot provide a reliable watermark. A future adapter may add a vendor cursor, but database deduplication remains mandatory.

### 7.5 Concurrency, retries, and health

The synchronization service must:

- use select_for_update or a durable lock field so one device cannot sync concurrently;
- time out device calls;
- classify transient network failure separately from malformed device data;
- retry transient scheduled failures with bounded backoff;
- avoid clearing terminal attendance logs in the first release;
- record clock drift and flag an employer-visible issue above a configured threshold;
- surface devices whose last successful sync exceeds a configurable multiple of their sync interval;
- avoid queries inside per-punch loops for large imports.

## 8. Reconciliation into Shiftly attendance

### 8.1 Candidate shift resolution

Implement:

~~~python
resolve_biometric_shift(employee, punch_time, organization) -> Shift | Issue
reconcile_biometric_projection(shift, actor=None, now=None) -> ProjectionResult
apply_ready_biometric_projection(projection, actor=None) -> AttendanceSession | Issue
~~~

Resolution uses the employee work timezone, the shift work date, and the configurable candidate window. It must handle:

- an early scan within the early clock-in allowance;
- scans after midnight belonging to an overnight shift;
- cross-terminal punches for the same employee;
- no scheduled shift;
- cancelled shifts;
- a scan that matches more than one possible shift;
- an employee whose mapping has become inactive;
- punches arriving after a candidate has already been applied.

### 8.2 Effective scan list

For one projection:

1. load all raw punches whose identity assignment was active when the punch occurred, across every terminal mapped to the employee within the candidate window;
2. order by occurred_at, then device and primary key for deterministic ties;
3. retain every raw punch;
4. build a separate effective scan list excluding only configured rapid duplicates without deleting or hiding their raw evidence;
5. save an input fingerprint containing effective raw-punch IDs, timing settings, projection algorithm version, and shift identity;
6. rebuild the candidate whenever its input fingerprint changes before application.

### 8.3 Flexible break pairing

When the candidate window has closed or an employer deliberately finalizes the candidate:

~~~text
effective scan 1           → clock-in
effective scans 2 and 3    → break 1
effective scans 4 and 5    → break 2
...
final effective scan       → clock-out
~~~

This produces a valid result only when:

- there are at least two effective scans;
- clock-out is later than clock-in;
- the number of interior scans is even;
- every inferred break has a positive duration;
- every selected scan is within the candidate window.

The candidate window closing is the normal finalization rule. An employer may request an earlier review, but a generic timestamp is never treated as a final clock-out merely because it is the latest scan so far. An early departure, a long open break, or a post-out scan creates an issue when the evidence cannot support a deterministic timeline.

Examples:

| Effective scan count | Result |
| --- | --- |
| 0 | No biometric attendance |
| 1 | Missing clock-out issue |
| 2 | Valid work interval, no device-recorded breaks |
| 3 | Incomplete sequence issue |
| 4 | Valid work interval and one break |
| 5 | Incomplete sequence issue |
| 6 | Valid work interval and two breaks |

During the day, the projection remains COLLECTING or AWAY. A generic scan is not treated as a final clock-out until the candidate is ready to finalize or the employer resolves it.

### 8.4 Applying a ready projection

If no AttendanceSession exists for the shift, applying a READY projection must:

1. create AttendanceSession with source BIOMETRIC;
2. set the derived clock-in and clock-out;
3. create BreakSession records for each inferred break;
4. link contributing BiometricPunch rows to the projection and session;
5. generate a Timesheet through the existing service;
6. record an attendance audit event for the applied biometric result;
7. mark the projection APPLIED.

If a projection requires review, do not create a misleading completed session. Show the issue to an employer instead.

The existing correction form currently limits the visual editor to three break rows. The biometric review and correction experience must support every inferred break interval, with a paginated or expandable timeline when the count is high.

### 8.5 Existing session rules

| Existing session | Action |
| --- | --- |
| None | Apply a valid biometric projection |
| BIOMETRIC with no reviewed timesheet | Leave snapshot immutable; create a late-evidence issue when the raw set changes |
| EMPLOYEE_WEB or EMPLOYER_MANUAL | Create a source-conflict issue |
| MIXED | Create a source-conflict issue |
| Timesheet approved/rejected | Preserve attendance and create late-evidence issue |
| Finalized payroll entry | Preserve attendance and create locked-attendance issue |

For a source conflict, an employer can explicitly create a correction after reviewing the raw scan timeline. The correction must name the evidence source and reason.

### 8.6 Payroll behavior

No new payroll calculation path is required. Once a biometric projection becomes an AttendanceSession and its Timesheet is approved, the current payroll services continue to use:

~~~text
AttendanceSession
    → effective_attendance_values()
    → approved Timesheet
    → PayrollTimeEntry snapshot
~~~

Payroll must continue to reject incomplete, missing, unapproved, or invalid timesheets. Finalization retains the same attendance-lock rule.

If a draft payroll preview has already used a biometric-derived Timesheet and an employer later accepts a correction, mark the affected draft run for recalculation using the existing payroll revision and exception behavior. A run in review or finalized state must not be silently rewritten.

## 9. User experience and navigation

Follow Shiftly's compact operational-dashboard design system from SHIFTLY_PROJECT_DESIGN_SKILL.md. Device management belongs inside Attendance, not as a new global navigation item.

~~~text
Attendance
├── Today
├── Review
└── Devices
~~~

### 9.1 Employee experience

For a mapped employee, remove employee-facing web clock controls and show:

~~~text
Attendance method
Biometric terminal required

Assigned terminals
Main Entrance F7 · Warehouse F7

Last scan
12:05 PM · Main Entrance F7

Current state
Away from work — awaiting the next biometric scan
~~~

For an unmapped employee, preserve the current web attendance experience exactly.

Employee pages must not reveal device communication passwords, other employees' IDs, or raw device diagnostics.

### 9.2 Employer attendance dashboard

Extend the attendance table with compact source and device status information:

| Employee | Shift | Attendance source | Status | Last device scan | Action |
| --- | --- | --- | --- | --- | --- |
| Ana Cruz | 9:00–18:00 | Biometric | Away | 12:05 PM | Review timeline |

Employer filters should include:

- biometric required;
- device not synced;
- unmatched identity;
- scan sequence needs review;
- source conflict;
- missing clock-out;
- device offline.

### 9.3 Devices dashboard

The Devices view should show:

- device name and location;
- enabled state;
- online, offline, or degraded status with text;
- last successful user and punch sync;
- configured effective sync interval;
- clock-drift warning;
- active mapped identities;
- unresolved issue count;
- primary actions: Test connection, Sync users, Sync attendance, View identities, View logs.

Use compact rows or cards, thin borders, visible text status badges, and direct next actions. Do not use a decorative device dashboard.

### 9.4 Device detail and identity mapping

The detail page contains:

1. Connection and sync health
2. Device configuration
3. Terminal identities
4. Unmapped identities
5. Recent punch activity
6. Sync history
7. Unresolved issues

Mapping requires an explicit employee selection and a confirmation that the terminal identity will make that employee biometric-required.

The mapping UI should warn when an employee has no other active identity or when a device is offline, but it should not block legitimate multi-device mappings.

### 9.5 Attendance review timeline

An employer reviewing a biometric candidate sees:

~~~text
09:00  Clock-in candidate        Main Entrance F7
12:05  Break start candidate     Main Entrance F7
13:01  Break end candidate       Warehouse F7
18:02  Clock-out candidate       Main Entrance F7
~~~

The page must distinguish:

- raw scans;
- scans excluded as likely duplicates;
- inferred work and break intervals;
- employer corrections;
- unresolved uncertainty;
- approved or payroll-locked state.

### 9.6 Loading, errors, and accessibility

- Device sync actions show in-button progress after the server accepts the job.
- A device error names the device and action, such as: “Warehouse F7 could not be reached. Last successful sync: 10:02 AM.”
- Forms show field-level connection errors for invalid host, port, timezone, or password.
- Tables remain semantic, searchable, filterable, and paginated.
- Status uses text in addition to color.
- Buttons retain visible keyboard focus and at least 44px touch targets.
- A save or sync success message appears only after the server confirms the result.

## 10. Endpoints, authorization, and jobs

Suggested template routes:

~~~text
GET  /attendance/devices/
GET  /attendance/devices/new/
POST /attendance/devices/new/
GET  /attendance/devices/<device>/
GET  /attendance/devices/<device>/edit/
POST /attendance/devices/<device>/edit/
POST /attendance/devices/<device>/test/
POST /attendance/devices/<device>/sync-users/
POST /attendance/devices/<device>/sync-punches/
GET  /attendance/devices/<device>/identities/
POST /attendance/devices/<device>/identities/<identity>/map/
POST /attendance/devices/<device>/identities/<identity>/unmap/
GET  /attendance/biometric-issues/
GET  /attendance/biometric-issues/<issue>/
POST /attendance/biometric-issues/<issue>/resolve/
POST /attendance/biometric-projections/<projection>/finalize/
~~~

Rules:

- device configuration, sync, mapping, unmapping, and issue resolution require employer authorization;
- every state-changing browser route is POST-only and CSRF-protected;
- every query is scoped to the active organization;
- a device ID, employee ID, identity ID, projection ID, or issue ID from a browser must never bypass organization scoping;
- employee endpoints expose only the employee's own summarized biometric status;
- scheduled jobs execute without an authenticated browser user and write DeviceSyncRun records.

## 11. Security, privacy, audit, and retention

### 11.1 Privacy

- Do not import biometric templates, images, or proprietary binary biometric data.
- Treat terminal user IDs and attendance timestamps as sensitive personnel data.
- Keep raw payloads bounded, structured, and free of communication credentials.
- Restrict raw punch, device configuration, and identity mapping views to employers.
- Define a business-approved retention period before a production rollout.

### 11.2 Audit

Add audit actions for human decisions:

- biometric device configured, updated, enabled, or disabled;
- terminal identity mapped or unmapped;
- biometric issue resolved or ignored;
- biometric projection manually finalized;
- manual-versus-biometric conflict resolved.

DeviceSyncRun is the operational audit trail for automatic jobs. Its diagnostic detail must not leak device passwords or raw biometric templates.

### 11.3 Immutability

Use database and model protections for raw punches:

- reject normal update and delete operations;
- separate raw evidence fields from enrichment fields;
- preserve a content hash;
- store correction/reconciliation decisions in separate records;
- retain evidence after a terminal is disabled.

### 11.4 Device health

Record and surface:

- last successful connection;
- last successful user sync;
- last successful punch sync;
- time since last sync;
- last error category;
- clock drift;
- unresolved identity and attendance issue counts.

## 12. Migration and backward compatibility

Use additive migrations only.

1. Add the biometrics app and new tables.
2. Add AttendanceSession.source with EMPLOYEE_WEB as the migration default.
3. Do not alter existing AttendanceSession timestamps, BreakSession rows, Timesheets, approvals, PayrollTimeEntries, or finalized payroll snapshots.
4. Existing employees remain manual-clock employees until an employer creates an active terminal identity mapping.
5. Existing schedules keep their current flexible break allowance; no schedule backfill is required.
6. Existing employer manual-record and correction behavior remains available.
7. Do not backfill fictional raw biometric events for historical attendance.

## 13. Phased implementation

### Phase 0 — Hardware proof and operational discovery

- [ ] Confirm the F7 terminal's private IP, port, communication password behavior, and timezone.
- [ ] Install the candidate adapter dependency in a disposable development environment.
- [ ] Test connection, user retrieval, and attendance retrieval against a non-production terminal.
- [ ] Capture normalized sample user and punch DTOs without persisting biometric templates.
- [ ] Verify timestamp precision, repeated-punch behavior, terminal user-ID format, and observed status/punch fields.
- [ ] Record device clock drift and validate office LAN firewall rules.

**Done when:** Shiftly can safely prove it can read a real F7, or the adapter choice is revised before production models depend on it.

### Phase 1 — Data foundation and employer device configuration

- [x] Create the biometrics Django app.
- [x] Add OrganizationBiometricSettings, AttendanceDevice, DeviceIdentity, DeviceIdentityAssignment, DeviceSyncRun, BiometricPunch, BiometricAttendanceProjection, and BiometricPunchIssue models.
- [x] Add encrypted credential helpers and production settings validation.
- [x] Add additive AttendanceSession.source migration.
- [x] Add employer-only device list, create, edit, test, identity-list, and mapping pages.
- [x] Add audit events for human device and mapping changes.
- [x] Add initial tenant, mapping, projection, and biometric-required service tests; expand credential-redaction coverage before production rollout.

**Done when:** An employer can configure one F7, test it, sync its users, and explicitly map terminal identities to employees.

### Phase 2 — Raw punch import and operational visibility

- [x] Implement the adapter interface and F7 pull adapter.
- [x] Implement idempotent raw-punch import with per-device locks.
- [x] Implement DeviceSyncRun counts, failures, and health status. Clock-drift diagnostics remain a hardware-proof follow-up.
- [x] Add manual employer Sync users and Sync attendance actions.
- [x] Add unmapped identities and unmatched-punch issue pages. A detailed raw-punch timeline is a follow-up UI slice.
- [x] Add a scheduler-safe sync_biometric_devices management command.

**Done when:** Repeated pulls preserve exactly one raw evidence row per terminal event and display operational status without changing attendance automatically.

### Phase 3 — Projection, flexible breaks, and exception handling

- [x] Implement shift resolution in terminal timezones with organization-shift fallback boundaries.
- [x] Implement cross-terminal raw-punch grouping by employee and scheduled shift.
- [x] Implement duplicate candidate exclusion while retaining raw rows.
- [x] Implement first/last boundary and interior break pairing.
- [x] Implement collecting, ready, and needs-review projection states. Away/materialization controls remain in the review UI follow-up.
- [x] Implement incomplete-sequence and no-shift issues. Ambiguous-shift and out-of-window issue refinements remain hardware-proof follow-ups.
- [x] Add employer biometric issue-resolution UI.
- [x] Add flexible multi-break and biometric-required service tests; overnight edge coverage remains a follow-up.

**Done when:** A valid timestamp sequence produces a reviewable projection and ambiguous data is clearly routed to employer review.

### Phase 4 — Attendance, timesheet, and manual-clock integration

- [x] Apply READY projections into biometric AttendanceSession and BreakSession records.
- [x] Generate existing Timesheets after a valid clock-out.
- [x] Add source display to the employer attendance view.
- [x] Enforce biometric-required policy inside employee clock-in, break, and clock-out services.
- [x] Remove employee web clock actions from the UI only when the service-level policy applies.
- [ ] Keep employer manual record and correction as the controlled fallback.
- [ ] Implement manual-versus-biometric conflict resolution.
- [ ] Protect approved and finalized records from automatic changes.

**Done when:** A mapped employee completes an entire scheduled workday from terminal scans through an approved, payroll-ready timesheet without using web clock buttons.

### Phase 5 — Scheduled synchronization, resilience, and rollout

- [ ] Run scheduled synchronization at the configured per-device effective interval.
- [ ] Add bounded retries, stale-device alerts, and an operator runbook.
- [ ] Add a device health summary to the Attendance dashboard.
- [ ] Load-test at the target employee, terminal, and punch volume.
- [ ] Pilot one terminal and a small employee group behind an organization feature flag.
- [ ] Compare biometric-derived attendance with the existing process before broad rollout.
- [ ] Enable more terminals and employees only after pilot acceptance.

**Done when:** Devices synchronize reliably in the office environment, exceptions are manageable, and payroll is unaffected by late or malformed terminal evidence.

## 14. Verification plan

### 14.1 Service and model cases

- mapped and unmapped identity imports;
- same terminal user ID in different organizations;
- same employee with IDs on multiple terminals;
- historical terminal-ID reassignment resolves old and new punches to the correct employee;
- overlapping effective identity assignments are rejected;
- duplicate repeated device pulls;
- two, four, and six effective-scan sequences;
- one, three, and five effective-scan incomplete sequences;
- duplicate scans within and outside the configured duplicate window;
- clock-in before the early window;
- clock-out after the post-shift window;
- cancelled shifts and no-shift punches;
- overnight shifts with scans after midnight;
- device timestamp conversion and clock-drift calculation;
- manual attendance already present;
- approved and rejected Timesheets;
- finalized payroll lock;
- disabled device, inactive identity, and inactive employee;
- stale device lock, retry, and synchronization failure;
- cross-tenant lookup attempts;
- raw-punch update/delete rejection;
- credential redaction in messages, sync logs, and audit metadata.

### 14.2 UI states

- no configured devices;
- configured but never connected;
- online, offline, and degraded device;
- manual sync running, successful, skipped, and failed;
- no terminal identities;
- unmapped identity queue;
- employee with one and several mapped terminals;
- biometric-required employee attendance screen;
- unmapped employee website clock screen;
- collecting biometric projection;
- away state while awaiting a return scan;
- ready completed projection;
- incomplete break sequence;
- no-shift, source-conflict, late-evidence, and locked-attendance issue;
- empty scan timeline;
- employer correction after a missing device scan;
- keyboard-only mapping and review workflow;
- narrow desktop and tablet layouts.

### 14.3 End-to-end acceptance scenario

Use the detailed, repeatable acceptance guide in
[`BIOMETRIC_ATTENDANCE_END_TO_END_SCENARIO.md`](BIOMETRIC_ATTENDANCE_END_TO_END_SCENARIO.md)
for the full terminal-to-payroll workflow, exception paths, evidence capture,
and pilot sign-off. The concise checklist below remains the plan-level summary.

1. Configure Main Entrance F7 and Warehouse F7 for one organization.
2. Test both connections and sync their users.
3. Map one employee to a different ID on each terminal.
4. Confirm employee web clock controls are unavailable.
5. Import this sequence:

~~~text
09:00  Main Entrance F7
12:05  Main Entrance F7
13:01  Warehouse F7
18:02  Warehouse F7
~~~

6. Confirm one biometric projection shows clock-in, one flexible break, and clock-out.
7. Apply the projection and confirm one completed AttendanceSession, one BreakSession, and one pending Timesheet.
8. Approve the Timesheet and confirm payroll can read it through the current workflow.
9. Import a late extra scan and confirm an issue is created without changing the approved timesheet.
10. Finalize a payroll run containing the approved time, then import another late scan and confirm attendance and payroll remain unchanged.
11. Create an employee with no mapping and confirm web clocking still works.
12. Remove an employee mapping and confirm future attendance returns to the manual policy.

### 14.4 Scale acceptance

For 200 biometric employees and multiple terminals:

- scheduled sync completes within the configured interval under normal device response time;
- repeated sync does not create duplicate raw punches, projections, sessions, breaks, or timesheets;
- device and issue tables remain paginated and responsive;
- no query is issued per punch when resolving identities and shifts;
- a temporary device outage creates visible health state without blocking unrelated manual employees;
- payroll preview continues to use only approved Timesheets.

## 15. Rollout controls and operational runbook

1. Ship behind an organization-level biometric feature flag.
2. Begin with one F7 and a small volunteer group.
3. Run device sync in observation mode before enforcing biometric-required employee policy.
4. Compare raw scan timelines with expected attendance for several payroll periods.
5. Enable biometric-required policy per mapped employee only after the mapping is verified.
6. Keep employer correction instructions available at every device issue.
7. Monitor missed scans, clock drift, source conflicts, and device offline duration.
8. Document device IP, physical location, owner, configured timezone, sync cadence, and recovery steps.
9. Do not delete terminal logs during the pilot.
10. Expand terminal and employee coverage gradually.

Suggested employer recovery path:

~~~text
Device offline or scan missing
        ↓
Employer opens biometric issue
        ↓
Review raw evidence and schedule
        ↓
Record or correct attendance with a reason
        ↓
Review generated timesheet
        ↓
Approve before payroll
~~~

## 16. Out of scope for the first release

- remote office networks, VPN onboarding, or a cloud connector;
- push events from the terminal;
- direct terminal user enrollment from Shiftly;
- device-side fingerprint template management;
- device-side payroll rules or time calculations;
- auto-approval of biometric timesheets;
- explicit IN/OUT terminal modes;
- automated legal break-compliance decisions;
- a second device vendor;
- bulk device provisioning;
- offline mobile employee clocking for biometric-required employees.

## 17. Definition of done

The biometric attendance feature is complete when:

- an employer can configure and test a ZKTeco F7 on the office LAN;
- terminal identities are mapped per device and can map several IDs to one employee;
- an active mapping makes the employee biometric-required and server-side blocks web clock actions;
- raw terminal punches are tenant-scoped, idempotent, auditable, and protected from normal mutation;
- timestamp-only scans correctly create flexible break intervals for complete sequences;
- incomplete or ambiguous sequences become clear employer issues;
- a valid projection produces one biometric attendance session, break records, and a pending timesheet;
- existing timesheet approval and payroll calculation continue to work without a parallel payroll path;
- employer corrections remain available and auditable;
- approved timesheets and finalized payroll are protected from late device evidence;
- automatic synchronization uses the effective configured interval, defaulting to two minutes;
- device health, sync failure, clock drift, and mapping issues are visible to employers;
- the UI follows Shiftly's compact, status-driven operational design;
- the real F7 pilot and end-to-end acceptance scenario pass before the feature is enabled broadly.

## 18. Reference limits and source material

- ZKTeco F7 product information: https://www.zkteco-ea.com/f7/
- Internal biometric attendance porting guide supplied for this planning session.
- Shiftly architecture inspected for this plan: attendance, timesheets, schedules, payroll, employees, audit, and configuration modules.

The F7 page confirms terminal transaction storage and network connectivity, but it does not prove exact compatibility with a particular pyzk version or installed firmware. Phase 0 is therefore a required hardware proof, not an optional documentation exercise.
