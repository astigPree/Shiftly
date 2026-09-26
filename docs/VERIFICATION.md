# Shiftly verification record

Scope: all current authentication, employee, schedule, attendance, timesheet,
reporting, payroll and audit features; desktop/mobile UI against
SHIFTLY_PROJECT_DESIGN_SKILL.md; Docker deployment and recovery.

All simulations use synthetic data and isolated databases. Existing local
employee/payroll records must not be changed by the verification tools.

## Work in progress

### Latest recorded results (September 26, 2026)

- PostgreSQL in Docker: 63 tests discovered; 61 passed and two optional browser
  tests skipped. No failures in this run.
- Separate Chromium browser run: two test methods executed with four failing
  viewport scenarios. The employee pay profile list overflows at 1024px and
  390px in its empty state and at 390px with records. Employee details also
  overflow at 390px with records. These layout issues remain open.
- Docker images built and the isolated local application stack started.
  Production TLS and backup/restore verification remain pending.

This is an implementation checkpoint, not a completed verification report.
Generated logs and screenshots are local artifacts and are not versioned.

- [ ] Automated service/model/form/view scenarios for every application
- [ ] Role, tenant and object isolation; CSRF and duplicate submissions
- [ ] Overnight/DST/timezone, breaks, incomplete attendance and review scenarios
- [ ] Payroll profiles/assignments, rate boundaries, calculations and lifecycle
- [ ] PostgreSQL concurrency, migrations and repeatable test execution
- [ ] Desktop, tablet and mobile browser review, including empty/error states
- [ ] Docker build, start, health, static assets, persistence and restore rehearsal
- [ ] Deployment runbook and final evidence/limitations

The project design guide's old advice to omit normal clock confirmations is
superseded by the user's explicit request to confirm clock and break actions.
Payroll tests verify configured behavior and arithmetic, not legal sign-off.
