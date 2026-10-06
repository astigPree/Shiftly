# Biometric provisional attendance implementation plan

**Prepared:** 2026-10-06  
**Status:** Implemented in the current Shiftly workspace  
**Scope:** Show a matched employee as actively working immediately after their first fingerprint scan, while preserving the existing review, timesheet, and payroll safeguards.  
**Companion documents:** [Biometric attendance implementation plan](BIOMETRIC_ATTENDANCE_IMPLEMENTATION_PLAN.md) · [Biometric error handling and connection recovery plan](BIOMETRIC_ERROR_HANDLING_IMPLEMENTATION_PLAN.md) · [Biometric attendance end-to-end scenario](BIOMETRIC_ATTENDANCE_END_TO_END_SCENARIO.md)

## 1. Purpose

Today, a successful first fingerprint scan is safely imported as immutable biometric evidence, but it does not create an `AttendanceSession` until Shiftly has enough evidence to build a complete attendance sequence. This can make the employer and employee think that synchronization failed even though Shiftly received the scan.

This plan adds a clear operational state:

> **Working — biometric provisional**

The state appears immediately after exactly one matched, effective fingerprint scan. It communicates that the employee has been seen at a terminal, while truthfully explaining that the attendance record is still collecting evidence.

The state must never be treated as confirmed attendance, a completed clock-in/clock-out pair, a timesheet value, or a payroll input.

## 2. Intended outcome

For an employee with an active terminal-ID assignment and a scheduled shift:

1. The employee scans at an assigned terminal.
2. Sync imports the immutable raw scan and matches it to one scheduled shift.
3. Shiftly immediately shows **Working — biometric provisional** to the employee and employer.
4. Subsequent scans are collected without guessing whether each is a break or clock-out.
5. When the candidate window closes, Shiftly either makes the sequence ready for employer review or opens a clearly explained issue.
6. An employer explicitly applies a reviewed, valid projection before Shiftly creates `AttendanceSession`, `BreakSession`, or `Timesheet` records.

## 3. Product boundaries and non-goals

| Boundary | Required behavior |
| --- | --- |
| Raw biometric evidence | Append-only and immutable. Do not edit, relabel, or discard the terminal event. |
| Provisional state | A projection-level operational view only. It is not an attendance snapshot. |
| Attendance, timesheets, payroll | Created only after a projection is valid, reviewed, and explicitly applied. |
| Generic F7 scan semantics | A timestamp alone cannot be called a clock-in, break, or clock-out until a complete sequence supports that conclusion. |
| Web fallback | Mapped biometric employees continue to have no employee self-service web clock fallback. Employer correction remains available with a reason and audit trail. |
| Manual attendance | Never overwrite it. A biometric/manual conflict becomes a review issue. |
| Fingerprint privacy | Shiftly stores terminal timestamps and terminal IDs only. It does not store fingerprint templates or images. |

This work does not change payroll calculations, add employee-controlled clock actions, or automatically apply incomplete biometric activity.

## 4. Why the live state belongs on the projection

`AttendanceSession` is the existing reviewed attendance snapshot consumed by timesheets and payroll. Creating it after the first scan would make incomplete evidence appear as normal attendance and risks introducing a false clock-out, invalid work duration, or payroll-visible record.

`BiometricAttendanceProjection` already represents evidence that Shiftly has grouped for a shift before materialization. It is therefore the correct place to hold live provisional activity.

~~~text
terminal scan
    ↓
raw BiometricPunch (immutable evidence)
    ↓
BiometricAttendanceProjection (live, provisional or reviewable)
    ↓ explicit employer action only when valid
AttendanceSession + BreakSession + Timesheet
    ↓ approved timesheet
payroll
~~~

## 5. State model

### 5.1 Separate lifecycle fields

Keep the existing projection lifecycle (`COLLECTING`, `READY`, `NEEDS_REVIEW`, `MATERIALIZED`, `CONFLICT`) and add a separate presentation-oriented live state. This avoids overloading `COLLECTING` with ambiguous UI meaning.

Suggested persisted field:

~~~python
class BiometricProjectionLiveState(models.TextChoices):
    NONE = "NONE", "No visible activity"
    WORKING = "WORKING", "Working — biometric provisional"
    AWAITING_NEXT_SCAN = "AWAITING_NEXT_SCAN", "Awaiting next biometric scan"
    READY_FOR_REVIEW = "READY_FOR_REVIEW", "Ready for review"
    NEEDS_REVIEW = "NEEDS_REVIEW", "Needs review"
    MATERIALIZED = "MATERIALIZED", "Attendance applied"
    CONFLICT = "CONFLICT", "Attendance conflict"
~~~

The implementation may name this `live_state` or `provisional_state`, but it must be distinct from the existing projection status.

### 5.2 User-visible meaning

| Projection lifecycle | Live state | Employer and employee wording | Attendance / payroll effect |
| --- | --- | --- | --- |
| No matched shift | None | “No matching scheduled shift” | None; create an issue. |
| `COLLECTING` with one effective scan | `WORKING` | “Working — biometric provisional” | No session, timesheet, or payroll value. |
| `COLLECTING` with later scan(s) | `AWAITING_NEXT_SCAN` | “Additional scan received — awaiting the next biometric scan” | No session, timesheet, or payroll value. |
| `READY` | `READY_FOR_REVIEW` | “Scan sequence ready for review” | Employer must apply it. |
| `NEEDS_REVIEW` | `NEEDS_REVIEW` | A precise issue such as “Missing a final scan” | No session, timesheet, or payroll value. |
| `MATERIALIZED` | `MATERIALIZED` | “Biometric attendance applied” | Existing attendance and timesheet workflow applies. |
| `CONFLICT` | `CONFLICT` | “Review required: biometric evidence conflicts with recorded attendance” | Preserve the existing record. |

### 5.3 State transitions

| Trigger | Required result |
| --- | --- |
| First matched effective scan | Create/update a projection with `COLLECTING` + `WORKING`; record `provisional_started_at`. |
| Second or later effective scan before candidate close | Recompute from all evidence and set `AWAITING_NEXT_SCAN`. Do not guess that the most recent scan is clock-out. |
| Candidate window closes with 2, 4, 6, ... valid effective scans | Set `READY` + `READY_FOR_REVIEW`. |
| Candidate window closes with one scan, odd interior scans, invalid interval, or ambiguity | Set `NEEDS_REVIEW` + `NEEDS_REVIEW` and create or update a specific issue. |
| Employer applies a valid projection | Create immutable attendance snapshots and set `MATERIALIZED`. |
| Existing manual session, approved/rejected timesheet, or payroll lock conflicts | Preserve existing records and set `CONFLICT` or `NEEDS_REVIEW`, as applicable. |
| A late scan arrives after application or a locked review point | Retain evidence and create a late-evidence issue; do not rewrite attendance. |

## 6. Matching and reconciliation prerequisites

The provisional display is reliable only if Shiftly can accurately associate a scan with a shift. Implement these rules before enabling the new UI as a source of operational truth.

### 6.1 Resolve a candidate shift by time window

Replace exact-date-only matching with a single authoritative service:

~~~python
resolve_biometric_shift(employee, punch_time, organization) -> ShiftResolution
~~~

It must:

1. convert imported device time to UTC at import, retaining original device-time context for audit;
2. use the employee work timezone for display and work-date reasoning, falling back to organization timezone;
3. search scheduled shifts whose UTC candidate window contains the scan;
4. calculate the candidate window as scheduled start minus the configured early-clock-in allowance through scheduled end plus post-shift capture allowance;
5. consider an overnight shift from its previous work date after midnight;
6. return one deterministic match, no match, or an ambiguity result; and
7. exclude cancelled shifts and ineligible employee mappings.

No match and more than one match must produce a clear issue rather than an arbitrary provisional Working state.

### 6.2 Repair scans that arrive before schedules or mappings

An imported scan must be eligible for reconciliation again when:

- an employer creates or changes a relevant shift;
- an employer creates, changes, backfills, or ends a terminal-ID assignment;
- a terminal's timezone or candidate-window policy changes; or
- an employer reprocesses a documented issue.

Implement `reconcile_unmatched_punches_for_shift(shift)` and an identity-assignment equivalent. Each must find raw punches in the affected time range, rerun the authoritative resolver, and close/supersede resolved no-shift or unmapped-ID issues with audit context.

Repeated syncs must remain idempotent: a duplicate raw scan must not create another projection or another status change.

### 6.3 Refresh open projections even when no new scan arrives

The current candidate can become reviewable merely because time passes. Add a scheduled reconciliation sweep such as:

~~~python
refresh_due_biometric_projections(now) -> RefreshResult
~~~

It re-evaluates `COLLECTING` projections whose candidate-close time has passed. Run it after each successful sync and from the existing biometric scheduler/management command, even when a terminal returns no new punch records.

## 7. Data changes and migration

### 7.1 Projection fields

Add only fields needed to make the state auditable and queryable:

| Field | Purpose |
| --- | --- |
| `live_state` | Persist the state listed in section 5.1. |
| `provisional_started_at` | First effective matched scan that supports the live state. |
| `last_effective_scan_at` | Latest non-duplicate evidence used by the projection. |
| `candidate_closes_at` | Calculated end of the candidate window used for automatic refresh. |
| `last_reconciled_at` | Operational diagnosis and stale-projection detection. |
| `input_fingerprint` | Deterministic fingerprint of effective punch IDs, time-policy values, algorithm version, and shift identity. |
| `algorithm_version` | Lets future reconciliation explain how a historic projection was derived. |

Add indexes for the normal operational queries, including `(employee, live_state)` and `(status, candidate_closes_at)` for the due collecting sweep. Projections are tenant-scoped through their required shift and organization relationship, so dashboard and review queries continue to filter through `shift__organization`.

### 7.2 Backfill and rollout migration

1. Add nullable/default-safe fields with `NONE` as the initial live state.
2. Deploy the schema without creating attendance records.
3. Add a management command that rebuilds projection states from existing raw biometric punches and current configuration.
4. Run it in dry-run mode first, report how many records would become provisional, ready, or issues, then run it for the approved pilot organization.
5. Never backfill fictional `AttendanceSession`, `BreakSession`, or `Timesheet` records.
6. Record a concise audit event when an existing projection's visible state changes because of the backfill, without writing one event for unchanged duplicate evidence.

## 8. Service design

### 8.1 Authoritative operations

Keep reconciliation in services, not in views. The core operations should be:

~~~python
resolve_biometric_shift(employee, punch_time, organization)
reconcile_biometric_projection(shift, actor=None, now=None)
reconcile_unmatched_punches_for_shift(shift, actor=None)
reconcile_identity_assignment_punches(assignment, actor=None)
refresh_due_biometric_projections(now=None)
apply_ready_biometric_projection(projection, actor=None)
~~~

Every recomputation must read the complete eligible raw-punch set, order by occurrence time then deterministic tie-breaker, and construct a separate effective scan list after applying only the configured rapid-duplicate rule. It must never derive a state from a terminal-provided clock-in/clock-out label.

### 8.2 Pairing rule after the candidate closes

For a valid completed sequence:

~~~text
effective scan 1         → clock-in
effective scans 2 and 3  → break 1
effective scans 4 and 5  → break 2
...
final effective scan     → clock-out
~~~

At least two scans are required. An odd number of scans cannot support a complete timeline. A generic scan remains provisional until the close rule or an employer review can determine a complete sequence.

### 8.3 Concurrency and idempotency

- Continue the existing per-device lock for sync.
- Use transaction/row locking when recalculating a projection so concurrent device syncs or manual reprocessing cannot emit inconsistent states.
- Save a new visible state only when the input fingerprint or state changes.
- Do not make `apply_ready_biometric_projection` automatic in this delivery. It remains an explicit authorized employer action.
- Preserve raw evidence and prior audit records whenever recalculation produces a different outcome.

## 9. User experience

Follow `SHIFTLY_PROJECT_DESIGN_SKILL.md`: compact operational surfaces, information hierarchy, text plus color, readable status badges, and no oversized decorative dashboard cards.

### 9.1 Employee attendance page

After the first matched scan, show a compact state block:

~~~text
Working — biometric provisional
Fingerprint scan received at 9:03 AM at Main Entrance F7.
Work time is provisional until the remaining scans are received and reviewed.
~~~

Requirements:

- Use a blue informational badge for `Working — biometric provisional`.
- Show a clearly named **Provisional elapsed time** only; do not call it approved work time.
- Do not show employee controls to start a break or clock out.
- For `AWAITING_NEXT_SCAN`, state the time of the most recent scan and explain that Shiftly cannot infer whether it is a break or clock-out yet.
- For `READY_FOR_REVIEW`, say the scan sequence is awaiting employer review.
- For an issue, show a short safe message and direct the employee to contact their employer; do not reveal other employees, internal candidate rules, or raw device credentials.

### 9.2 Employer attendance dashboard

Keep confirmed attendance and provisional biometric activity distinct:

- Existing **On shift**, **On break**, **Late**, and **Absent** figures continue to represent established attendance data.
- Add a compact **Provisional biometric activity** count with explanatory helper text: “Fingerprint activity received; not yet attendance or payroll-ready.”
- In the daily attendance table, show source **Biometric · provisional**, the first/last scan times, and a **Review scan timeline** action.
- Do not calculate confirmed worked hours, late/absence rules, or payroll readiness from a provisional row.
- A manual attendance conflict receives the existing manual source plus a prominent review badge rather than two competing attendance rows.

### 9.3 Imported scans and projection review

Replace generic or ambiguous status wording with state-aware text:

| Situation | Imported-scans status | Link/action |
| --- | --- | --- |
| One matched scan | `Working · provisional` | View scan timeline |
| Later collecting scan | `Awaiting next biometric scan` | View scan timeline |
| No match | `No matching scheduled shift` | Open issue |
| Ambiguous match | `Multiple possible shifts` | Open issue |
| Complete candidate | `Ready for review` | Review projection |
| Applied candidate | `Attendance applied` | View attendance |

Add a projection review page or slide-over that contains:

1. employee, scheduled shift, work timezone, and candidate window;
2. a compact scan timeline with raw versus effective scan indication and duplicate reasons;
3. the current state, exact review blockers, and related issues;
4. derived work and break intervals only after a valid sequence exists;
5. **Apply confirmed attendance** only when the projection is `READY`; and
6. **Record employer correction** for a conflict or invalid/incomplete evidence state.

Use blue for provisional information, amber for waiting/review, red for a blocking issue, and green only for confirmed/applied attendance.

## 10. Permissions, navigation, and API contract

| Concern | Requirement |
| --- | --- |
| Employee access | May see only their own provisional state, scan times, terminal display name, and safe guidance. |
| Employer access | Existing attendance/biometric permissions control device views, issue resolution, reprocessing, and apply action. |
| Sensitive data | Never return communication password, raw SDK payload, fingerprint artifact, or another employee's terminal mapping. |
| Navigation | Keep pages under **Attendance → Biometric devices / imported scans / issues**. Add the projection review as a contextual action, not a new global item. |
| Dashboard data | Add a projection-aware view model. Do not force templates to query biometric models row by row. |

Suggested endpoints, subject to existing URL conventions:

~~~text
GET  /attendance/biometric-projections/<id>/
POST /attendance/biometric-projections/<id>/apply/
POST /attendance/biometric-projections/<id>/reprocess/
~~~

The apply endpoint must reject a projection that is not ready, has changed since review, conflicts with manual attendance, or is locked by timesheet/payroll state.

## 11. Error and edge-case handling

| Scenario | Expected behavior |
| --- | --- |
| Scan has no active terminal-ID mapping | Store raw scan, create unmapped-ID issue, show no provisional attendance. |
| Scan has no scheduled shift | Store raw scan, create no-shift issue, support rematch after scheduling. |
| Scan matches more than one shift | Create ambiguity issue; do not choose a shift or show Working. |
| Shift is created after a scan | Reprocess affected unmatched evidence and show provisional state once exactly one shift matches. |
| Identity assignment is backfilled | Reprocess affected raw scans within the assignment interval. |
| Duplicate rapid scan | Preserve raw evidence; omit only from effective pairing with a visible duplicate reason. |
| Multiple terminals | Combine mappings for the same employee into one candidate ordered timeline. |
| Overnight shift | Use the previous shift's candidate window when a post-midnight scan belongs there. |
| Manual attendance already exists | Preserve it and create source-conflict review; do not overlay provisional Working. |
| Timesheet approved/rejected or payroll finalized | Preserve it and create late-evidence/locked-attendance issue. |
| Device offline | Retain existing state; show terminal health separately. Do not infer absence because no new scan arrived. |
| Scheduler is unavailable in development | Manual **Sync scans** plus an explicit projection refresh/reprocess path must support testing. Production scheduler runs the same service. |

## 12. Testing plan

### 12.1 Service and model tests

- One matched effective scan creates `COLLECTING` + `WORKING`, with no `AttendanceSession`, `BreakSession`, or `Timesheet`.
- A second scan keeps a collecting projection and displays `AWAITING_NEXT_SCAN`.
- Two, four, and six effective scans become ready after the candidate closes and produce the expected derived intervals.
- One, three, and five effective scans become precise incomplete-sequence issues after the candidate closes.
- Duplicate scans remain in raw evidence but do not distort the effective list.
- Exact candidate window, early allowance, post-shift allowance, employee timezone fallback, cross-terminal timeline, and overnight shift matching work correctly.
- A scan imported before schedule creation or identity mapping becomes matched after the relevant reconciliation hook runs.
- Repeated sync/reprocess is idempotent, including concurrent attempts.
- Manual conflict, approved/rejected timesheet, and payroll lock prevent application.

### 12.2 View and permission tests

- Employee sees only their own provisional state and no prohibited details.
- Employer daily attendance page receives projection-aware data without N+1 biometric queries.
- Dashboard metrics keep provisional activity separate from confirmed on-shift/on-break counts.
- Imported scans show meaningful state labels and route to the correct timeline/issue.
- The apply endpoint rejects stale, non-ready, conflicting, and locked projections.

### 12.3 Manual acceptance test

Use the end-to-end scenario added in section 14. Run it with a real F7 only after automated tests pass. In development, use imported or test-adapter punch records and manual refresh because `runserver` does not start the scheduled sync worker.

## 13. Delivery phases

| Phase | Deliverable | Exit criteria |
| --- | --- | --- |
| 0 | Reconcile matching foundations | Candidate-window resolver, overnight/timezone behavior, rematch hooks, and regression tests pass. |
| 1 | Projection live-state data and services | First scan becomes projection `WORKING`; no attendance/session side effects. |
| 2 | Scheduled and manual refresh | Time-based closure works without a new scan; dev manual reprocess works. |
| 3 | Employee and employer UI | Clear provisional wording, separate counts, accessible timeline link, and conflict states work. |
| 4 | Projection review/apply | Employer can inspect evidence and explicitly apply only valid, unlocked projections. |
| 5 | Pilot and observability | One controlled terminal/department proves matching accuracy, sync latency, issue rates, and audit completeness. |

## 14. End-to-end acceptance scenario

### Setup

1. Enable biometric attendance and configure a terminal with a two-minute default sync interval.
2. Create an active employee with an active terminal-ID assignment for that terminal.
3. Give the employee a scheduled 9:00 AM–6:00 PM shift in their work timezone, with a flexible break.
4. Confirm the employee has no manual `AttendanceSession` for that shift.

### First scan: immediate visibility

1. At 8:58 AM, record the employee's first fingerprint scan.
2. Run **Sync scans** manually in development, or wait for the configured production scheduler.
3. Open the employee attendance page.
4. Verify it shows **Working — biometric provisional**, first scan time, terminal display name, and provisional elapsed time.
5. Open the employer Attendance page.
6. Verify the employee appears under **Provisional biometric activity** with source **Biometric · provisional**.
7. Verify there is still no `AttendanceSession`, timesheet, confirmed work hour, or payroll input.

### Flexible break and end of shift

1. Record scans at 12:05 PM and 1:01 PM.
2. Sync and verify the projection says **Awaiting next biometric scan** rather than declaring an unverified break or clock-out.
3. Record a final scan at 6:02 PM and sync.
4. Verify the scan timeline shows the complete raw evidence and remains reviewable until the post-shift capture window closes.
5. Run the projection refresh after candidate close.
6. Verify the projection becomes **Ready for review** with derived 9:00–12:05, 1:01–6:02 work intervals and a 12:05–1:01 break.

### Review and application

1. As an employer, open the projection review view and confirm all raw scans, effective scans, candidate window, and derived intervals.
2. Select **Apply confirmed attendance**.
3. Verify exactly one immutable biometric `AttendanceSession`, the correct `BreakSession`, and a pending `Timesheet` are created.
4. Approve the timesheet through the existing process.
5. Verify payroll sees the approved attendance through its existing time-entry workflow.

### Negative paths

1. Repeat with only a first scan, advance/reprocess beyond candidate close, and verify a **Missing final scan** issue instead of materialized attendance.
2. Repeat with a scan before the shift is created, then create the shift and verify rematching works.
3. Repeat with a manual attendance record present and verify a conflict issue without replacement.
4. Repeat after approved timesheet or finalized payroll and verify late evidence is retained but no existing record changes.

## 15. Definition of done

- A successful first matched scan is visible within the next completed sync as **Working — biometric provisional**.
- UI wording makes clear that the state is not confirmed attendance, timesheet time, or payroll-ready time.
- No first-scan path creates an `AttendanceSession`, `BreakSession`, or `Timesheet`.
- No-shift, ambiguous, unmapped, duplicate, conflict, locked, and late-evidence paths are visible and auditable.
- A due projection becomes ready or issue-bearing when time passes even if no new scan is imported.
- Existing attendance, approval, payroll, source precedence, and privacy protections remain intact.
- The end-to-end scenario and automated tests pass for a pilot terminal before broader rollout.

