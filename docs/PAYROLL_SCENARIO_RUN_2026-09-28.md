# Payroll scenario run — 2026-09-28

## Purpose

This run exercises the payroll foundation scenarios in `PAYROLL_SCENARIOS.md` against the local Django application after the payroll scope, pay basis, statutory, payment method, and obligation changes.

The development database was empty before the run, so the scenario created a temporary local workspace with persisted test records. It does not use production employee data. The login details are stored separately in the ignored file `.secrets/PAYROLL_SCENARIO_CREDENTIALS.md`.

## Execution

Environment:

- Base URL: `http://127.0.0.1:8000/`
- Organization: `Shiftly Payroll Scenario Workspace` (ID `1`)
- Organization timezone: `Asia/Manila`
- Payroll frequency: monthly
- Scenario script: `.secrets/run_payroll_scenario.py` (local-only, ignored by Git)

Command:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='dev'
& 'C:\Users\63948\Desktop\SAAS\global_venv\Scripts\python.exe' manage.py shell -c "exec(compile(open('.secrets/run_payroll_scenario.py', encoding='utf-8').read(), '.secrets/run_payroll_scenario.py', 'exec'))"
```

## Results

All assertions in the scenario passed:

| Check | Result |
| --- | --- |
| Overlapping employee statutory coverage rejected | Pass |
| Overlapping statutory rule version rejected | Pass |
| Overlapping payment method rejected | Pass |
| Proposed obligation transaction leaves posted balance unchanged | Pass |
| Obligation transaction deletion rejected as append-only | Pass |
| Reusing an idempotency key with a different employee scope rejected | Pass |
| Employee membership deletion rejected after a run is voided | Pass |
| Monthly payroll blocker is surfaced | Pass |

### Created run records

- **April selected run**: `PAY-20260401-20260430`, run ID `1`. It included the daily-paid employee and generated one statement with net `PHP 800.00`. The script then voided the run so the immutable-scope check could be exercised.
- **March monthly run**: `PAY-20260301-20260331`, run ID `2`. It surfaced `MONTHLY_INPUT_NOT_SUPPORTED` and `NO_PAYROLL_TIME`. This is expected: the current payroll engine records the monthly pay basis and reviewed period input, but monthly attendance-to-pay calculation is still intentionally blocked.

### Audit evidence

The run emitted `PAYROLL_RUN_CREATED` and `PAYROLL_RUN_RECALCULATED` audit events for both payroll runs.

## What this verifies

- An employer can configure one workspace with daily, hourly, monthly, and mixed pay profiles.
- Compensation versions can be recorded with effective dates and reviewer/source evidence.
- Employee statutory coverage and organization statutory rules are effective-dated and cannot overlap.
- Payment methods are effective-dated and cannot overlap.
- Cash advances can be represented as obligations; proposed installments do not reduce the posted ledger balance.
- Payroll runs can target an explicit employee subset and the submission token is idempotent for the same scope.
- A non-draft run cannot have its employee scope changed.
- The system does not silently calculate monthly pay before monthly calculation inputs are supported.

## Automated checks

- `manage.py check`: passed with no issues.
- `manage.py test tests.test_payroll --settings=config.test_settings --noinput`:
  22 tests passed.
- `manage.py test tests --settings=config.test_settings --noinput`:
  **102 tests passed, 8 skipped**.

The selected-run regression test also confirms that membership deletion reads
the current run status from the database, so a stale in-memory run object
cannot reopen a void scope.

## Not covered by this run

- Automatic SSS, PhilHealth, Pag-IBIG, and withholding tax calculations.
- Monthly salary proration and monthly attendance-to-pay calculation.
- Loan/cash-advance deduction posting during a finalized run.
- Cash denomination reports.
- Workbook import or comparison against `202604.xls`.
- Browser visual verification; the in-app browser connector was unavailable in this session.

## Repeating or cleaning up the run

Use the credentials in `.secrets/PAYROLL_SCENARIO_CREDENTIALS.md` while the local database is retained. Remove the temporary organization and users after verification, or reset `db.sqlite3` before another clean run.

## Large-workspace dataset

The temporary workspace was expanded after the scenario run to **200 active
employees** for pagination and large-list testing. The original four scenario
employees were preserved, and 196 additional synthetic employees were added
with `BULK-NNN` employee codes. Their email pattern and temporary password are
listed in the ignored credentials file.

The full scenario was then applied to all 200 employees:

- 50 Daily, 50 Hourly, 50 Monthly, and 50 Mixed pay-basis profiles.
- 200 October compensation versions with reviewed source data.
- 800 effective-dated statutory coverage records (four agencies per employee).
- 200 Cash payment methods effective October 1, 2026.
- 100 reviewed period inputs for Daily and Monthly employees.
- 200 reviewed cash-advance obligations and 200 proposed installment rows.
- Selected payroll run `PAY-20261001-20261031` (run ID `3`) containing all 200 employees.

The large run generated 150 statements: 50 Daily statements plus 100 Hourly
and Mixed statements from approved overnight shifts. Those shifts ran from
10:00 PM to 3:00 AM with a 30-minute break, producing 100 night entries and
27,000 night minutes. The run recorded a gross total of `PHP 89,500.00` and
the expected `MONTHLY_INPUT_NOT_SUPPORTED` exception for 50 Monthly
employees. No unsupported monthly pay was silently calculated.

## Six-month attendance history

To exercise attendance, timesheet, schedule, and pagination screens with
historical data, each employee received one completed weekday shift for every
weekday from **2026-04-01 through 2026-09-28**:

- 129 shifts per employee, **25,800 shifts total**.
- 25,800 completed attendance sessions.
- 25,800 approved timesheets.
- Daily shifts run 9:00 AM–6:00 PM with a 60-minute break.
- Mixed-basis employees run 10:00 PM–3:00 AM with a 30-minute break, adding
  6,450 overnight shifts to the history.
- Historical reviewed compensation was added where an employee did not already
  have a rate covering the six-month window.

The verification query confirmed every one of the 200 employees has exactly
129 shifts, completed attendance, and approved timesheets in this date range.
