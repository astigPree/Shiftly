# Biometric attendance end-to-end acceptance scenario

**Purpose:** Run a controlled, repeatable test from a ZKTeco F7 fingerprint
scan through Shiftly attendance, timesheets, and a draft payroll calculation.
This is a pilot acceptance guide. Use synthetic employees and a non-production
payroll period.

**Related plan:** [Biometric attendance implementation plan](BIOMETRIC_ATTENDANCE_IMPLEMENTATION_PLAN.md)  
**Supported device:** ZKTeco F7 on the same private office network as Shiftly  
**Default sync interval:** 120 seconds  
**Evidence rule:** Shiftly receives terminal user IDs and timestamps only. Do
not enter, upload, export, or screenshot fingerprint templates or images.

> **Status labels**
>
> - **Pass** — current code and normal UI support the step, and the test passes.
> - **Pilot blocked** — the step needs the real F7, office LAN, or production
>   scheduler proof.
> - **Product blocked** — the acceptance behavior needs implementation before
>   it can pass through the normal employer workflow.

## 1. Exit criteria

Treat the pilot as successful only when all required items below pass:

1. Both actual F7 terminals connect from the office LAN.
2. A mapped employee is prevented from using web clock actions.
3. Four scans across two terminals become one reviewed attendance result with
   one flexible break.
4. The result creates one biometric attendance session and one pending
   timesheet.
5. The approved timesheet appears in the existing payroll calculation.
6. Missing scans, manual conflicts, late evidence, and device outages have
   actionable employer workflows.
7. Approved timesheets and finalized payroll are never altered by later scans.
8. Scheduled sync remains duplicate-safe at the effective configured interval.

## 2. Controlled test data

Create or use this test-only data. Replace terminal IP addresses with the
verified private addresses. Do not use a live payroll period.

| Item | Value | Notes |
| --- | --- | --- |
| Employer operator | Company-admin employer account | Performs setup, review, and corrections. |
| Biometric employee | BIO-PILOT-001 | Active, payroll-ready employee. |
| Manual control employee | BIO-MANUAL-001 | Active employee with no terminal assignment. |
| Main terminal | Main Entrance F7 | Terminal ID 1001 for the biometric employee. |
| Warehouse terminal | Warehouse F7 | Terminal ID 2001 for the same employee. |
| Timezone | Asia/Manila | Record the terminal and employee work timezone. |
| Test shift | 09:00–18:00 | Scheduled break allowance: 60 minutes. |
| Evidence label | TEST-ONLY biometric pilot | Use in employer correction reasons. |

Maintain a pilot evidence sheet with device name, IP, port, firmware, serial,
device clock, Shiftly clock, terminal IDs, employee IDs, shift ID, sync result,
issue IDs, attendance ID, timesheet ID, and payroll draft ID. Keep passwords
and biometric templates out of this record.

## 3. Preconditions

- [ ] Use a pilot organization or synthetic employees only.
- [ ] Apply the current migrations.
- [ ] Install dependencies from requirements/base.txt, including pyzk and
  cryptography, in the environment that will communicate with the F7.
- [ ] Set BIOMETRIC_CREDENTIAL_KEY outside the repository.
- [ ] Confirm the Shiftly server can reach both F7 terminals on TCP 4370.
- [ ] Confirm each F7's timezone, date, time, seconds precision, user-ID
  format, and communication-password behavior.
- [ ] Enrol test user IDs on the F7 devices directly. Shiftly does not enrol
  fingerprints.
- [ ] Create the scheduled pilot shift before any scan.
- [ ] Confirm no approved timesheet or finalized payroll already includes the
  pilot shift.
- [ ] Agree which employer will record audited fallback attendance if a terminal
  scan is missed.

**Expected result:** The hardware, network, timestamps, and test data are known
before the biometric-required policy affects an employee.

## 4. Register and prove both terminals

### 4.1 Main Entrance F7

1. Sign in as the employer.
2. Open **Attendance → Biometric attendance** at /attendance/devices/.
3. Select **Add terminal** and enter:

   | Field | Value |
   | --- | --- |
   | Name | Main Entrance F7 |
   | Model | ZKTeco F7 |
   | Host | Verified private IP address |
   | Port | 4370, unless the device uses a verified alternative |
   | Timezone | Asia/Manila |
   | Status | Active |
   | Communication password | Verified device password, if configured |

4. Save the terminal.
5. Open the terminal action menu and select **Test connection**.
6. Record health, firmware, serial number, and test time in the evidence sheet.

**Expected result:** The terminal reports healthy and its password never appears
in the UI, messages, audit summary, or evidence sheet.

### 4.2 Warehouse F7

Repeat the same steps for Warehouse F7.

**Expected result:** Both terminal rows retain their own health, timezone, and
sync state.

### 4.3 Controlled connection failure

Use a non-production terminal or a temporary unreachable test address.

1. Run **Test connection** once.
2. Confirm the employer gets a password-free error.
3. Confirm the terminal health changes to offline or degraded.
4. Restore the terminal and confirm a later connection test becomes healthy.
5. Verify BIO-MANUAL-001 can still use normal web clocking.

**Expected result:** An outage is visible and does not block unrelated manual
employees.

**Pilot blocked:** A real F7/LAN connection proof is still required.

**Product blocked:** Connection tests should create durable DeviceSyncRun
records so the operational history matches the UI claim.

## 5. Synchronize users and map identities

### 5.1 Discover terminal identities

1. For each terminal, select **Sync users**.
2. Open **Map IDs** for Main Entrance F7 and find ID 1001.
3. Open **Map IDs** for Warehouse F7 and find ID 2001.

**Expected result:** The two terminal IDs appear as separate identities.

### 5.2 Create effective-dated mappings

1. Assign ID 1001 to BIO-PILOT-001.
2. Set **Effective from** before the pilot shift begins.
3. Leave **Effective until** blank.
4. Save the mapping.
5. Repeat for ID 2001 and the same employee.
6. Confirm both mappings are current and their history identifies the employer
   and effective date.

**Expected result:** One employee has active terminal identities on two devices.

### 5.3 Verify clock-policy enforcement

1. Sign in as BIO-PILOT-001, or open that employee's attendance view.
2. Open the pilot shift.
3. Confirm the employee sees guidance to use the fingerprint terminal.
4. If a web clock action is visible, attempt it and confirm the server rejects
   clock-in, break start, break end, and clock-out.
5. Sign in as BIO-MANUAL-001 and confirm normal web clock actions remain
   available.

**Expected result:** Only the actively mapped employee becomes
biometric-required.

## 6. Normal cross-terminal workday

Use this exact sequence in Asia/Manila:

| Local time | Terminal | Expected reviewed meaning |
| --- | --- | --- |
| 09:00 | Main Entrance F7, ID 1001 | Clock-in candidate |
| 12:05 | Main Entrance F7, ID 1001 | Break-start candidate |
| 13:01 | Warehouse F7, ID 2001 | Break-end candidate |
| 18:02 | Warehouse F7, ID 2001 | Clock-out candidate |

### 6.1 Import evidence

1. Have the pilot employee scan at all four times.
2. Wait for the configured scheduled sync, or select **Sync scans** for each
   terminal as the employer.
3. Open **View scans** for both terminals.
4. Confirm each scan has the expected terminal user ID, local timestamp,
   timezone, terminal, and employee mapping.
5. Run another manual sync without creating a new scan.

**Expected result:** Four raw evidence rows exist. A repeated import does not
create a duplicate row.

### 6.2 Review the candidate workday

After the post-shift capture window closes, review the candidate for the pilot
shift:

| Item | Expected result |
| --- | --- |
| Candidate state | Ready for employer review |
| Clock-in | 09:00 |
| Flexible break | 12:05–13:01 |
| Clock-out | 18:02 |
| Scan count | 4 |
| Evidence terminals | Main Entrance F7 and Warehouse F7 |

**Expected result:** Shiftly groups both terminal identities into one employee
and shift projection.

**Product blocked:** The projection service exists, but there is no normal
employer projection list, detail screen, or visible **Apply to attendance**
action. Record this checkpoint as blocked until that review UI is delivered.

### 6.3 Apply the approved candidate

When the projection review UI exists:

1. Open the ready projection.
2. Compare its derived times with the immutable raw timeline.
3. Select **Apply to attendance**.
4. Open the resulting attendance record.

**Expected result:** Exactly one completed attendance session, one break session,
and one pending timesheet exist. Attendance source is **Biometric terminal**.
Reapplying the same candidate must not create duplicates.

## 7. Timesheet and payroll handoff

### 7.1 Timesheet approval

1. Open **Timesheets** and locate the generated pilot record.
2. Verify its work and break intervals match the applied attendance.
3. Approve it through the normal employer workflow.
4. Record the approval audit event in the evidence sheet.

**Expected result:** The normal timesheet workflow approves the biometric work.

### 7.2 Draft payroll verification

1. Create a **draft-only** payroll run covering the pilot work date.
2. Select BIO-PILOT-001.
3. Recalculate the draft.
4. Inspect the employee statement or calculation evidence.
5. Confirm the approved biometric time is included under existing payroll
   rules.
6. Void the synthetic draft after recording the result.

**Expected result:** Existing payroll consumes the approved timesheet. No money
is transferred and no live payroll run is finalized for this test.

## 8. Exception scenarios

Run every exception against a fresh synthetic shift or employee. Keep the normal
path evidence unchanged.

### 8.1 Unmapped terminal ID

1. Scan using an enrolled ID with no active Shiftly mapping.
2. Sync scans and open the issue queue.
3. Map the identity to the correct employee with an effective date covering the
   scan.

**Expected result:** An **Unmapped terminal identity** issue exists, the raw
scan is retained, and historical assignment can be resolved without rewriting
the raw evidence.

### 8.2 Incomplete flexible-break sequence

Capture only:

~~~text
09:00  clock-in candidate
12:05  break-start candidate
18:02  clock-out candidate
~~~

**Expected result:** The candidate needs review and produces an incomplete
sequence issue. Shiftly must not guess a break end or create attendance.

### 8.3 No matching shift

1. Scan a mapped employee on a date with no scheduled shift.
2. Sync scans.

**Expected result:** A **No matching shift** issue appears; the raw evidence
remains available and attendance is not created.

### 8.4 Repeated terminal scan

1. Scan twice within the configured duplicate interval.
2. Sync twice.
3. Compare evidence count, duplicate count, and the candidate sequence.

**Expected result:** The approved duplicate policy prevents an extra break or
work interval while preserving the evidence and its resolution reason.

**Product blocked:** duplicate_window_seconds is configured but current
reconciliation does not apply it.

### 8.5 Terminal outage and employer fallback

1. Make a test terminal unavailable during a synthetic scheduled shift.
2. Confirm device-health or issue feedback appears for the employer.
3. As an employer, record missed attendance with reason
   TEST-ONLY biometric terminal outage.
4. Confirm the attendance source is **Employer manual** and its audit entry
   includes the reason.
5. Restore the terminal and sync any later evidence.

**Expected result:** The employer can create a controlled fallback. The employee
does not regain self-service web clocking because a terminal is offline.

### 8.6 Manual-versus-biometric conflict

1. Record employer manual attendance for a scheduled test shift.
2. Import a complete biometric sequence for that same shift.
3. Open the issue queue.

**Expected result:** A source-conflict issue presents a documented choice to
keep manual attendance, apply an employer-approved biometric correction, or
defer. It does not overwrite either source.

**Product blocked:** The system identifies a source conflict, but the explicit
conflict-resolution workflow is not implemented.

### 8.7 Late scan after approval

1. Complete the normal scenario through timesheet approval.
2. Import one additional scan for the same workday.
3. Inspect attendance, candidate state, timesheet, issue queue, and payroll
   draft.

**Expected result:** A **Late evidence** issue is created. Attendance, the
approved timesheet, and payroll calculation remain unchanged until an employer
chooses an audited correction path.

**Product blocked:** Materialized projections currently need late-evidence
protection before this can pass.

### 8.8 Evidence after payroll finalization

1. Use a separate synthetic payroll period.
2. Approve the test timesheet and finalize a test payroll run.
3. Import later evidence for the finalized workday.

**Expected result:** Attendance, payroll snapshots, and payslips remain
unchanged. A visible issue directs the employer to the approved correction or
off-cycle policy.

**Product blocked:** Finalized-payroll late-evidence handling needs end-to-end
verification and protection.

### 8.9 End a mapping

1. End both terminal assignments after the last biometric test shift.
2. Schedule a later shift for the same employee.
3. Sign in as that employee and open the later shift.

**Expected result:** Future shifts return to standard web-clock policy while
past raw scans retain their original assignment history.

**Product blocked:** Mapping closure and reassignment controls need a dedicated
employer workflow.

## 9. Scheduled synchronization and resilience

1. Set the organization default interval to 120 seconds and leave device
   overrides blank.
2. Configure the office scheduler to run:

~~~text
python manage.py sync_biometric_devices
~~~

3. Observe three normal runs with no new scans.
4. Add one test scan and confirm import occurs within the interval.
5. Trigger two overlapping runs and confirm the per-device lock safely skips
   one operation.
6. Disconnect a test terminal for several cycles, then restore it.
7. Verify failure, recovery, health, and sync history.

**Expected result:** Sync uses each device's effective interval, imports raw
evidence once, and isolates failures to the affected terminal.

**Pilot blocked:** The command is scheduler-safe, but deployment scheduling,
retries, stale-device alerts, clock-drift diagnostics, and the operator runbook
still require implementation and proof.

## 10. Pilot scale check

Run this only after the single-employee scenario passes.

| Pilot dimension | Minimum target |
| --- | --- |
| Terminals | 2 F7 terminals |
| Biometric employees | 10 synthetic or volunteer employees |
| Mapped identities | At least one each; several mapped to both terminals |
| Workdays | 5 consecutive scheduled days |
| Expected scans | At least 4 per employee per day |
| Payroll review | One draft-only synthetic payroll |

Measure import duration, duplicate counts, missing scans, unmapped identities,
sync age, offline duration, exception volume, manual fallback use, conflict
resolution time, and attendance-to-payroll discrepancies.

**Product blocked:** The plan's 200-employee load and pagination acceptance
criteria need implementation and measured evidence before wide rollout.

## 11. Evidence and sign-off

Capture the following for every pilot run:

- [ ] Sanitized device configuration and connection-test results.
- [ ] User-sync and scan-sync run summaries.
- [ ] Mapping history for IDs 1001 and 2001.
- [ ] The four-scan normal-path timeline.
- [ ] Reviewed projection and action record.
- [ ] Biometric attendance record and break record.
- [ ] Generated and approved timesheet.
- [ ] Draft payroll calculation evidence.
- [ ] Every exception result and corresponding audit record.
- [ ] Scheduler evidence for normal, skipped, failed, and recovered runs.
- [ ] Confirmation that no fingerprint templates or images entered Shiftly data,
  logs, screenshots, or exports.

| Area | Result | Evidence link or ID | Reviewer | Date |
| --- | --- | --- | --- | --- |
| F7 connection and user import | Pass / Fail / Blocked |  |  |  |
| Mapping and employee clock policy | Pass / Fail / Blocked |  |  |  |
| Normal multi-terminal attendance | Pass / Fail / Blocked |  |  |  |
| Projection review and application | Pass / Fail / Blocked |  |  |  |
| Timesheet and payroll handoff | Pass / Fail / Blocked |  |  |  |
| Unmapped and incomplete scans | Pass / Fail / Blocked |  |  |  |
| Outage and employer fallback | Pass / Fail / Blocked |  |  |  |
| Conflict and late evidence | Pass / Fail / Blocked |  |  |  |
| Scheduled synchronization | Pass / Fail / Blocked |  |  |  |
| Pilot scale result | Pass / Fail / Blocked |  |  |  |

## 12. Release decision

Enable biometric attendance beyond the pilot only after every required
normal-path item passes, exception paths are actionable, and no unresolved
product-blocked item can affect attendance, timesheet, or payroll integrity.

When an item fails, retain the evidence, keep the rollout restricted to the
pilot organization or observation mode, and create the next work item against
the implementation plan.

