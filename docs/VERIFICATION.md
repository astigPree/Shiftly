# Shiftly verification record

Scope: all current authentication, employee, schedule, attendance, timesheet,
reporting, payroll and audit features; desktop/mobile UI against
SHIFTLY_PROJECT_DESIGN_SKILL.md; Docker deployment and recovery.

Automated simulations use synthetic data and isolated databases. The live
browser review uses a separate temporary workspace authorized by the user.
Existing local company records are not changed by the verification tools.

## Work in progress

### Latest recorded results (September 26, 2026)

- Philippine payroll follow-up: all 98 tests passed, including 29 targeted
  scenario tests and eight Chromium browser tests. Missing registration,
  statutory review, cutoff, stale-review, and confirmation scenarios and fixes
  are recorded in [Philippine payroll scenarios](PAYROLL_SCENARIOS.md).

- PostgreSQL in Docker: 63 tests discovered; 61 passed and two optional browser
  tests skipped. No failures in this run.
- The four previously recorded browser overflow failures are fixed. The
  expanded SQLite test run passed all 68 tests, including seven Chromium
  browser tests. The live review completed 287 authenticated page/viewport
  combinations across seven widths, plus ten public-page checks. See
  [Browser layout review](UI_REVIEW.md) for coverage, fixes, and evidence.
- Docker images built and the isolated local application stack started.
  Production TLS and backup/restore verification remain pending.

This is an implementation checkpoint, not a completed verification report.
Generated logs and screenshots are local artifacts and are not versioned.

- [ ] Automated service/model/form/view scenarios for every application
- [ ] Role, tenant and object isolation; CSRF and duplicate submissions
- [ ] Overnight/DST/timezone, breaks, incomplete attendance and review scenarios
- [ ] Payroll profiles/assignments, rate boundaries, calculations and lifecycle
- [ ] PostgreSQL concurrency, migrations and repeatable test execution
- [x] Desktop, tablet and mobile Chromium browser review, including empty/error states
- [ ] Docker build, start, health, static assets, persistence and restore rehearsal
- [ ] Deployment runbook and final evidence/limitations

The project design guide's old advice to omit normal clock confirmations is
superseded by the user's explicit request to confirm clock and break actions.
Payroll tests verify configured behavior and arithmetic, not legal sign-off.
