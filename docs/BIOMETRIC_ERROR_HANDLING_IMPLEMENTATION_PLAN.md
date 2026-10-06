# Biometric error handling and connection recovery plan

**Prepared:** 2026-10-06  
**Status:** Core mapping, typed connection errors, durable test/sync runs, and safe operator handling implemented; hardware pilot and deeper retry/issue lifecycle work remain  
**Scope:** Fix the terminal-identity mapping validation crash and make ZKTeco F7 connection, sync, import, and reconciliation failures safe, actionable, auditable, and recoverable.  
**Companion documents:** [Biometric attendance implementation plan](BIOMETRIC_ATTENDANCE_IMPLEMENTATION_PLAN.md) · [Biometric attendance end-to-end scenario](BIOMETRIC_ATTENDANCE_END_TO_END_SCENARIO.md)

## 1. Purpose and outcome

Biometric attendance is office-critical. A normal employer action such as mapping a terminal user must never produce a server error, and a failed terminal connection must not hide the reason, poison device health, or silently affect attendance and payroll.

This plan establishes one recovery model for identity mapping, terminal configuration, connection tests, scheduled/manual user sync, scheduled/manual punch sync, raw-punch validation, reconciliation, and issue resolution.

Every handled failure must:

1. preserve raw evidence and existing attendance records;
2. use a stable error code rather than a vendor or Python exception string;
3. show the employer a short, safe message with a next action;
4. retain only sanitized diagnostics for authorized administrators;
5. retry only transient transport failures; and
6. create a durable operation record without exposing communication passwords, encryption keys, stack traces, or fingerprint data.

### 1.1 Non-goals

This work does not add fingerprint enrollment, template copying, device access over the public internet, employee web clock fallback for biometric-required employees, or a second terminal vendor. It also does not change approved timesheets or finalized payroll because a later device operation fails or succeeds.

## 2. Current incident: terminal identity mapping returns HTTP 500

### 2.1 Observed behavior

| Item | Evidence |
| --- | --- |
| Route | POST /attendance/devices/1/identities/ |
| Employer action | Map a discovered terminal user ID to an employee |
| Result | HTTP 500 |
| Exception | DeviceIdentityAssignment.device_identity.RelatedObjectDoesNotExist |
| User impact | The mapping is not saved, and the employer cannot tell whether the employee, dates, or terminal ID needs correction. |

### 2.2 Confirmed cause

The terminal identity is intentionally excluded from the mapping form because it comes from the row selected by the employer. The form stores it only for its later save step. Django runs full model validation during form.is_valid first. Model validation then accesses the unloaded device identity relation while checking effective-date overlaps, which raises RelatedObjectDoesNotExist before the view can return a form error.

~~~text
POST mapping form
  -> form.is_valid
  -> ModelForm model validation
  -> DeviceIdentityAssignment.clean
  -> reads unloaded device_identity relation
  -> RelatedObjectDoesNotExist
  -> HTTP 500
~~~

This is a form/model validation lifecycle defect. It is not caused by invalid terminal data or an employee mistake.

### 2.3 Required behavior after the fix

- A valid mapping saves successfully.
- Invalid dates, overlap, employee eligibility, and organization mismatch stay on the same form and identify the relevant rule or field.
- A missing or invalid terminal identity context creates no mapping and never returns HTTP 500.
- Existing historical mappings remain unchanged.
- Browser forms, service calls, future APIs, and imports use the same business rules.

## 3. Safety principles

| Principle | Required behavior |
| --- | --- |
| Evidence first | Never delete or rewrite raw biometric punches because a connection, mapping, or projection failed. |
| Safe failure | A device failure must not alter approved attendance, approved timesheets, or finalized payroll. |
| Clear ownership | A form error names a field or business rule. A terminal error names the device and one safe next action. |
| Stable categories | UI behavior and retry policy use application codes, never a changing SDK exception string. |
| Least disclosure | Do not show passwords, encryption keys, raw stack traces, socket details, or raw terminal payloads in browser messages, audit events, or standard logs. |
| Honest health | Offline, bad credential, malformed data, unsupported protocol, and disabled device are different states. |
| Durable operations | Every connection test and sync attempt has a terminal, trigger, start/end time, outcome, and sanitized diagnostics. |
| Idempotency | Retry never duplicates a raw punch, identity assignment, attendance session, or issue. |

## 4. Shared error contract and taxonomy

Create one application-level error/result type used by forms, views, adapters, services, management commands, and the UI result presenter.

~~~python
BiometricOperationError(
    code=...,
    category=...,
    retryable=...,
    health_outcome=...,
    operator_message=...,
    operator_action=...,
    diagnostics={...},  # sanitized structured values only
)
~~~

The implementation may use an enum-backed exception, dataclass, or equivalent. The stable fields and behavior are required.

### 4.1 Error taxonomy

| Code | Situation | Retry | Safe employer message and action | Health result |
| --- | --- | --- | --- | --- |
| BIO-MAP-CONTEXT | Missing, stale, or invalid terminal identity context | No | “This terminal user could not be found. Refresh the list and select the user again.” | Unchanged |
| BIO-MAP-DATE-RANGE | Effective-until is on or before effective-from | No | “The end date must be after the start date.” | Unchanged |
| BIO-MAP-OVERLAP | The terminal user is already mapped during the selected period | No | “This terminal user already has a mapping for part of this date range.” | Unchanged |
| BIO-MAP-TENANT-MISMATCH | Identity and employee belong to different organizations | No | “Choose an employee from this organization.” | Unchanged |
| BIO-MAP-EMPLOYEE-INELIGIBLE | Employee is inactive or cannot receive a biometric mapping | No | “Choose an active employee eligible for biometric attendance.” | Unchanged |
| BIO-CONFIG-INVALID | Host, port, timezone, interval, or terminal configuration is invalid | No | Show a field-level correction such as “Enter a valid private-network IP address and port.” | Configuration needs attention |
| BIO-CREDENTIAL-KEY | Credential encryption key is missing or invalid | No | “The terminal credential cannot be read. Save it again after an administrator fixes the server key.” | Configuration needs attention |
| BIO-CREDENTIAL-DECRYPT | Stored credential cannot be decrypted | No | “The saved terminal credential needs to be entered again.” | Configuration needs attention |
| BIO-CREDENTIAL-FORMAT | Password is invalid for the F7 adapter | No | “Enter a valid communication password for this terminal.” | Configuration needs attention |
| BIO-ADAPTER-MISSING | The supported F7 adapter is unavailable | No | “This server cannot communicate with ZKTeco F7 terminals yet. Contact the system administrator.” | Configuration needs attention |
| BIO-UNSUPPORTED-DEVICE | Model or firmware protocol is unsupported | No | “This terminal responded with an unsupported device protocol. Review its compatibility details.” | Degraded |
| BIO-NETWORK-UNREACHABLE | Connection refused, no route, host unreachable, or LAN failure | Yes | “{terminal} could not be reached on the office network. Check power, LAN access, address, and port.” | Offline after threshold |
| BIO-NETWORK-TIMEOUT | Device did not respond before timeout | Yes | “{terminal} did not respond in time. It will be retried automatically.” | Degraded, then Offline after threshold |
| BIO-AUTHENTICATION-FAILED | The device rejects its communication password | No | “{terminal} rejected its communication password. Update it and test again.” | Configuration needs attention |
| BIO-PROTOCOL-ERROR | SDK returns an unexpected protocol response | No | “{terminal} responded, but Shiftly could not read its terminal data. Review the operation details.” | Degraded |
| BIO-PAYLOAD-INVALID | A returned user/punch has invalid timestamp, ID, timezone, or shape | No automatic transport retry | “Some data from {terminal} could not be imported. Valid records were saved safely.” | Degraded |
| BIO-SYNC-LOCKED | Another test or sync owns the device lock | No | “A sync is already running for {terminal}. Wait for it to finish, then refresh.” | Syncing |
| BIO-DATABASE | A persistence or uniqueness race occurs | No automatic replay until classified | “Shiftly could not safely save all terminal records. The operation was recorded for review.” | Degraded |
| BIO-CLOCK-DRIFT | Terminal time exceeds the approved drift tolerance | No import retry until reviewed | “{terminal}’s clock differs from organization time. Review the terminal clock before applying new scans.” | Needs review |
| BIO-INTERNAL | Any unexpected application error after known cases are classified | No automatic retry until investigated | “Shiftly could not complete this biometric operation. The attempt was recorded for review.” | Degraded |

Only the code, safe message, next action, terminal name, and timestamps may be shown to an ordinary employer. Root exception types and sanitized technical details are administrator-only.

### 4.2 Diagnostic data policy

| May retain | Must never retain or expose |
| --- | --- |
| code, category, retryability, operation name, terminal ID/name, masked host where appropriate, port, start/end time, duration, SDK exception class, attempt count, result counts, safe protocol status, and clock-drift seconds | communication password, encryption/Fernet key, authenticated connection object, fingerprint template/image, raw stack trace in the browser, or an unredacted terminal payload containing secrets |

## 5. Phase 0: reproduce and protect the current failure

1. Add a regression test that posts the exact identity-mapping payload that produced the HTTP 500.
2. Establish fixtures for an organization, configured terminal, discovered terminal user, active employee, inactive employee, and historical assignment.
3. Assert the mapping form returns a normal rendered validation response for expected invalid input and never raises RelatedObjectDoesNotExist.
4. Capture current business rules for same-organization assignment, eligibility, date order, overlap, and historical mapping preservation.

**Exit condition:** the current production failure is reproducible in automated tests before source code changes begin.

## 6. Phase 1: repair mapping validation

### 6.1 Bind the identity before validation

In biometrics/forms.py, the mapping form constructor must require a valid selected identity context and bind that identity to the form instance before Django evaluates form.is_valid.

The form must not wait until save to attach device_identity. A missing identity must become a controlled form error, not an implicit relation failure.

### 6.2 Make model validation defensive

In biometrics/models.py, DeviceIdentityAssignment.clean must safely handle partially populated model instances:

- test device_identity_id and employee_id before accessing related objects;
- use foreign-key IDs for overlap queries;
- skip relation-dependent logic only when a relation has not yet been supplied;
- use ValidationError for expected business rules;
- attach date-range and overlap errors to the relevant field or non-field error; and
- preserve cross-organization validation when both related IDs are present.

The model must never dereference an unloaded device_identity relation as part of model validation.

### 6.3 Preserve service ownership and form state

- Keep the identity-assignment service as the authoritative write path inside a transaction.
- Let the service call full model validation after every required relation is attached.
- Catch ValidationError separately in the view and bind messages to the form.
- Do not broadly catch an exception and echo its string in the browser.
- Preserve selected terminal user, employee, and entered effective dates when re-rendering the form.
- For overlap messages, do not disclose unrelated employee names to users who do not have access.

### 6.4 Required mapping tests

| Case | Expected outcome |
| --- | --- |
| Valid terminal identity and dates | Assignment saved through the service |
| Missing identity context | Controlled non-field error; no save; no HTTP 500 |
| Unknown identity for selected terminal | Controlled non-field error; no save |
| Effective-until earlier than/equal to effective-from | Field error; no save |
| Overlapping assignment | Clear non-field/date error; no save |
| Cross-organization employee | Controlled validation error; no data disclosure |
| Inactive/ineligible employee | Controlled validation error |
| Concurrent mapping attempt | One valid outcome; second receives a controlled conflict/overlap result |
| Direct model full_clean with incomplete instance | Safe validation behavior; never RelatedObjectDoesNotExist |

**Exit condition:** every expected invalid mapping produces a normal form response, and the original HTTP 500 regression test passes.

## 7. Phase 2: credential and F7 connection recovery

### 7.1 Validate configuration before networking

Validate host, port, timezone, model, sync interval, and communication-password format before attempting a connection.

The terminal create/edit form currently encrypts the password after regular form validation. Missing cryptography support, absent/invalid encryption configuration, or an encryption error must be caught at the form/view boundary and presented as a safe field or non-field error. It must not become an HTTP 500.

### 7.2 Separate adapter stages

Refactor the F7 adapter and calling services into explicit stages:

~~~text
Validate configuration
  -> encrypt/decrypt credential
  -> load supported adapter
  -> open TCP connection
  -> authenticate
  -> request device metadata
  -> request users or punches
  -> validate returned records
  -> persist outcome
~~~

Map an exception at each stage to the stable code in Section 4. A bad password, invalid credential key, missing adapter, malformed device response, refused connection, and timeout must never all be reported as “could not reach device.”

Close an opened device connection in a finally block even when user or punch retrieval fails.

### 7.3 Durable connection tests

Replace the direct view-to-adapter test path with a shared service operation that:

1. validates configuration;
2. creates a durable DeviceSyncRun with trigger MANUAL_TEST;
3. acquires the standard per-device lock;
4. performs handshake and safe metadata lookup;
5. records outcome, duration, error code, diagnostics, and available serial/firmware;
6. updates device health using the policy in Section 9; and
7. releases the lock in finally.

Every failed and successful test must be visible in the same operational history as sync operations.

## 8. Phase 3: sync orchestration, locks, and retries

### 8.1 One protected orchestration path

Use one service wrapper for manual user sync, manual punch sync, scheduled sync, and test connection. It owns run creation, adapter selection, locking, error mapping, counts, health updates, audit events, and cleanup.

Create the operation record and enter the protected cleanup scope before adapter selection where possible. Otherwise unsupported model/configuration errors can leave a run marked RUNNING and a durable lock held until expiry.

### 8.2 Lock behavior

| Situation | Required result |
| --- | --- |
| Current lock belongs to active run | Create/finish a SKIPPED operation with BIO-SYNC-LOCKED; never show a success toast with zero rows. |
| Process exits after lock acquisition | Finally releases its tokenized lock. |
| Stale lock remains after crash | Bounded expiry recovers it safely, records the recovery, and prevents two concurrent imports. |
| Manual request arrives during scheduled run | Show current run time/status and link to activity history. |
| Scheduled request reaches disabled terminal or disabled organization | Skip it explicitly; create no attendance data and no misleading success summary. |

Use a lock token so one worker cannot release another worker’s lock.

### 8.3 Retry policy

- Manual Test connection makes one intentional attempt and reports the classified outcome.
- Scheduled sync retries only BIO-NETWORK-UNREACHABLE and BIO-NETWORK-TIMEOUT failures.
- Default retry sequence: 2 minutes, 5 minutes, then 15 minutes. Cap retries for the current scheduled cycle and return to the configured normal cadence afterward.
- Do not automatically retry configuration, credential, adapter, protocol, validation, clock-drift, or malformed-payload errors.
- Persist attempt number, retry-parent run, next retry time, and final disposition.
- Add a small schedule jitter where multiple terminals would otherwise retry at the same instant.

## 9. Phase 4: import integrity, health, and reconciliation

### 9.1 Per-record validation and partial results

Validate each returned user or punch before persistence. Distinguish:

- missing/invalid terminal user ID;
- missing or malformed timestamp;
- unsupported source timezone;
- invalid payload shape;
- duplicate database race;
- partial/truncated attendance history;
- repeated same-window scan;
- clock drift beyond the allowed tolerance; and
- persistence failure after some valid records are imported.

Use idempotent source keys and transaction/race-safe upsert behavior. A malformed row must not cause an otherwise healthy terminal to become Offline or discard valid rows.

For a partially usable response:

1. store valid evidence idempotently;
2. count imported, duplicate, invalid, deferred, and rejected records;
3. finish as PARTIAL or equivalent with BIO-PAYLOAD-INVALID;
4. create an issue where sufficient safe context exists; and
5. mark device health Degraded, not Offline.

A configured duplicate-window setting must be applied deliberately during reconciliation. The raw punch ledger remains immutable; duplicate-candidate suppression must be explainable and must not delete raw evidence.

### 9.2 Device health states

| State | Meaning | Example |
| --- | --- | --- |
| Healthy | Recent verified connection and no blocking data condition | Successful punch sync |
| Syncing | Active device lock/run | Scheduled import in progress |
| Degraded | Device responded or data was read, but review is needed | Invalid payload, protocol issue, clock drift |
| Offline | Consecutive transient network failures crossed the threshold | Power/LAN/network route failure |
| Configuration needs attention | Non-network setup blocks communication | Bad password, credential key, missing adapter |
| Disabled | Operator intentionally excludes the device | Terminal under maintenance |

Do not mark a terminal Offline after one timeout. Use an explicit configurable/documented threshold, such as three consecutive transport failures. Reset the counter only after a verified successful connection.

### 9.3 Issue lifecycle and late evidence

Implement explicit creation, resolution, reopening, and audit transitions for:

- unmapped identity;
- no matching or ambiguous shift;
- incomplete scan sequence;
- open break;
- duplicate candidate;
- late evidence after projection materialization;
- manual-versus-biometric conflict;
- payroll-locked attendance;
- clock drift; and
- offline/stale terminal.

A materialized projection must not be recalculated by later evidence. Later punches create a late-evidence issue and preserve the attendance, timesheet, and payroll snapshot. An odd-sequence issue may auto-close only when newly arrived evidence genuinely completes the sequence; record that transition.

An application result must distinguish Applied, Conflict, Partial, Skipped, and Failed. The UI must never report success when an existing manual attendance result prevented application.

## 10. Phase 5: operator UI, audit, and privacy

### 10.1 User-facing messages

Replace broad messages.error(request, str(error)) paths with a shared result presenter.

| Surface | Required behavior |
| --- | --- |
| Identity mapping | Inline field/non-field errors; entered values remain visible; expected validation does not use a generic toast. |
| Add/edit terminal modal | Adjacent errors for host, port, timezone, and credential; never re-render the password value. |
| Test/sync result | Terminal name, safe code/message, last successful sync when relevant, and one next action such as Edit terminal, Retry, or View operation. |
| Connected terminals table | Health badge, last result/time, next retry where relevant, and one compact action menu. |
| Activity history | Trigger, operation type, outcome, safe code, counts, duration, and administrator-only sanitized diagnostic details. |
| Review queue | Separate terminal/configuration problems from raw-punch and reconciliation issues. |
| Stale terminal warning | Persistent, non-blocking warning after configured no-success threshold with a link to terminal history. |

Never show passwords, Fernet keys, SQL errors, raw vendor exception strings, raw payloads, or stack traces.

### 10.2 Additive schema and audit changes

Use additive migrations only. Preserve raw punches, mapping history, projections, attendance, timesheets, and existing audit events.

| Record | Proposed additions |
| --- | --- |
| AttendanceDevice | last_attempt_at, last_success_at, last_error_code, last_error_at, last_error_summary, consecutive_failure_count, next_retry_at, health_state, and clock_drift_seconds |
| DeviceSyncRun | trigger, attempt number, retry parent, started/finished time, duration, stable error code, diagnostics schema version, sanitized diagnostics, imported/duplicate/invalid/deferred counts, and SKIPPED/PARTIAL outcomes |
| Audit events | device edit, credential update, test requested/completed, sync started/completed/failed/skipped, stale-lock recovery, issue resolution/reopen, and attendance conflict outcome |

Limit diagnostic sizes and enforce redaction before storage. Audit who started manual operations and who resolved issues, but never store credentials or fingerprint material.

### 10.3 Operator runbook

Link an operational runbook from the terminal page:

1. confirm terminal power and LAN link;
2. verify private IP address and TCP port 4370;
3. run Test connection;
4. distinguish offline from credential/configuration/protocol errors;
5. update credentials only through the secure form;
6. review the stable operation code and safe detail;
7. retry only after the stated corrective action; and
8. use the existing employer correction process for an attendance deadline rather than inventing biometric evidence.

## 11. Verification matrix

### 11.1 Unit and model tests

| Case | Expected result |
| --- | --- |
| Valid identity mapping | Assignment is saved through the service |
| Missing identity context | Controlled error; no save; no HTTP 500 |
| Invalid date order | Field error; no save |
| Overlap | Controlled date/non-field error |
| Tenant mismatch | Controlled validation error with no cross-tenant disclosure |
| Inactive employee | Controlled eligibility error |
| Incomplete model instance full_clean | Safe validation; never relation exception |
| Missing cryptography/Fernet configuration | BIO-CREDENTIAL-KEY; no HTTP 500 |
| Invalid/non-numeric communication password | BIO-CREDENTIAL-FORMAT; no network mislabel |
| Missing adapter | BIO-ADAPTER-MISSING; no network attempt |
| Refused connection | BIO-NETWORK-UNREACHABLE and retryable |
| Timeout | BIO-NETWORK-TIMEOUT and retryable |
| Rejected password | BIO-AUTHENTICATION-FAILED and not retryable |
| Invalid device payload | BIO-PAYLOAD-INVALID and Degraded |
| Concurrent operation | SKIPPED run with BIO-SYNC-LOCKED |

### 11.2 Integration and security tests

- Every connection test creates and completes one durable operation record on success, failure, configuration error, and lock contention.
- Adapter creation, connection, list, parsing, storage, health update, and audit failures always release their lock.
- Retry chains are bounded and preserve the original run link.
- Partial imports store valid records once and count rejected/deferred records accurately.
- Three configured transport failures become Offline; a verified connection becomes Healthy.
- Authentication/configuration failures do not increase the offline transport counter.
- Disabled organization or disabled terminal is not automatically synced.
- Browser messages, audit metadata, DeviceSyncRun fields, and ordinary logs contain no password, encryption key, stack trace, or raw vendor exception.
- A late punch cannot rewrite materialized attendance, approved timesheet, or payroll evidence.

### 11.3 Hardware and office-network acceptance

Run the following against the actual office ZKTeco F7 before broad enablement:

1. correct IP, port, and password test;
2. powered-off/unreachable terminal;
3. wrong password;
4. response timeout;
5. manual sync while scheduled sync is active;
6. malformed/unknown user or timestamp;
7. network recovery after retry;
8. clock drift outside tolerance; and
9. a valid four-scan day across approved terminals after recovery.

For each, capture stable code, employer message, health transition, operation history, raw-punch result, issue state, and audit record.

## 12. Delivery order, rollout, and acceptance criteria

### 12.1 Recommended delivery order

| Order | Deliverable | Likely areas |
| --- | --- | --- |
| 1 | Mapping crash regression test and fix | biometrics/forms.py, models.py, views.py, services.py, tests |
| 2 | Credential/form boundaries and typed taxonomy | forms, views, services, adapter |
| 3 | Durable test/sync orchestration and lock cleanup | services, management command, models/migration |
| 4 | Partial import, health states, retry/stale policy | services, models/migration, command |
| 5 | Issue lifecycle, safe result presenter, activity UI | views, templates, audit service |
| 6 | Runbook and actual F7 pilot evidence | docs and pilot records |

The mapping repair can ship independently and should be treated as P0. Do not wait for retry/health work to remove the active HTTP 500.

### 12.2 Rollout and rollback

1. Deploy mapping validation fix and tests first.
2. Apply additive schema migrations before code writes new fields.
3. Enable typed runs and health tracking behind existing device-management permissions.
4. Pilot retry/stale policy with one F7.
5. Complete hardware acceptance and the existing end-to-end scenario with a small mapped employee group.
6. Expand only when all acceptance checks pass.

Rollback disables new retry policy/UI behavior without deleting raw punches, mapping history, run history, attendance, timesheets, or payroll. If one terminal is unreliable, disable that terminal only and use employer attendance correction for affected shifts.

### 12.3 Definition of done

- [ ] The original mapping POST saves or returns a normal validation response; it never returns HTTP 500.
- [ ] No mapping validation path accesses an unloaded relation.
- [ ] Every expected form error preserves entered values and identifies an actionable rule.
- [ ] Every connection test, manual/scheduled sync, skip, partial import, and failure creates a completed durable operation record.
- [ ] Connection, timeout, credential, adapter, protocol, payload, lock, and internal errors have separate safe codes/messages.
- [ ] No password, encryption key, stack trace, or fingerprint data appears in user-facing output, standard logs, audit events, or stored diagnostics.
- [ ] Locks release on all failure paths and stale locks recover safely.
- [ ] Retried imports are idempotent and do not duplicate raw punch evidence.
- [ ] Health states distinguish Healthy, Syncing, Degraded, Offline, Configuration needs attention, and Disabled.
- [ ] Late evidence never changes materialized attendance, approved timesheets, or finalized payroll.
- [ ] Hardware acceptance is complete against the office ZKTeco F7.

## 13. Relationship to the broader biometric plan

The main implementation plan defines raw evidence preservation, identity mapping, projection, attendance reconciliation, and payroll boundaries. This companion plan supplies the failure contract needed to operate those features safely on an office network.

After implementation, use the [end-to-end acceptance scenario](BIOMETRIC_ATTENDANCE_END_TO_END_SCENARIO.md) to prove both normal scan flows and the recovery branches described here.

