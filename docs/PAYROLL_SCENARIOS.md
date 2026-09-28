# Philippine payroll scenario verification

Original verification: September 26, 2026. Scenario update: September 28, 2026.

## Scope and result

Simulated the current Philippine hourly payroll workflow using synthetic
employees and isolated Django test databases. The complete suite passed **98
tests**, including **29 Philippine payroll scenario tests** and **8 browser
tests**. The existing payroll calculation tests also cover overtime, holidays,
rest days, rate/rule changes at midnight, period boundaries, duplicate runs,
off-cycle corrections, and finalized-record immutability.

The browser scenario fills in the statutory review form, submits a missing-SSS
registration case, corrects a validation error, completes all four reviews,
submits the run, returns it to draft, and confirms removal of an adjustment.
Expanded form layouts were checked at 1440, 390, and 320 pixels.

After the payroll foundation update, the repository-wide suite passes **102
tests with 8 skips**. That run verifies compatibility of the existing
workflows and migrations.

The isolated execution recorded in
[`PAYROLL_SCENARIO_RUN_2026-09-28.md`](PAYROLL_SCENARIO_RUN_2026-09-28.md)
now verifies the selected-run, effective-dated records, obligation ledger,
idempotency, and monthly blocker additions. The remaining unchecked rows below
are still intentionally pending because they need browser evidence, all-active
scope coverage, approved-run checks, or the future statutory/monthly
calculation engines.

## Changes covered by the next scenario run

The next run must cover these additions:

- separate Regular and Probation/Part-time payroll periods in one organization;
- explicit all-active versus selected employee scope on a payroll run;
- hourly, daily, monthly, and mixed pay-basis metadata, including the monthly
  calculation blocker until a conversion policy is approved;
- reviewer-entered minimum daily base without inferring statutory coverage;
- effective-dated SSS, PhilHealth, Pag-IBIG, and BIR coverage records, including
  exemption reason/source and sensitive identifier access controls;
- effective-dated Cash and Bank Transfer payment methods without storing bank
  credentials;
- append-only cash-advance, SSS-loan, Pag-IBIG-loan, company-loan, and employee
  charge obligations and their proposed/posted ledger transactions;
- selected-run filtering, idempotency, and finalized-run scope immutability;
- morning/afternoon/overtime paper timecard mapping as reviewed work segments.

The examples in the questionnaire (including employee names, balances, and
payment methods) are not fixtures. Scenario setup must create synthetic
records explicitly and must never seed those values into a user's database.

## Defects found and fixed

1. **Omitted statutory review silently passed.** A statement with no SSS,
   PhilHealth, Pag-IBIG, or withholding review could be finalized. Both submission
   and finalization now require an explicit review of all four items per employee.
2. **No distinction between missing registration and zero contribution.** Each
   review now records registration status separately from employee and employer
   amounts. Pending registration requires follow-up evidence and cannot be used
   as an automatic not-applicable treatment.
3. **Reviewed figures could become stale after an adjustment.** Reviews are
   bound to the run, calculation inputs, and itemized lines. Changing a line
   requires review again. Recalculation rebuilds the regular payroll snapshot;
   old evidence remains in immutable calculation previews and audit events.
4. **No correction path from In review.** The employer can return a reviewed run
   to Draft, including older runs without structured reviews. Finalized and
   voided runs remain locked.
5. **Invalid monetary service inputs were not fully handled.** NaN, infinity,
   malformed, non-positive, oversized, and sub-cent manual amounts now return
   validation errors. Empty labels and source/reason text are rejected too.
6. **An acknowledged empty run could pass.** A regular run with no statements
   can no longer proceed simply by acknowledging the no-work exception.
7. **Unconfirmed work classification was ignored.** Automatic hourly premiums
   now block when rank-and-file coverage is not confirmed. Other classifications
   need a separately designed eligibility workflow; the checkbox must reflect
   the actual reviewed classification.
8. **Payroll confirmation conflicted with the submission guard.** The guard
   could disable a form before confirmation and then prevent the confirmed
   request. Payroll confirmations now intercept the first submit before the
   guard, leaving cancellation usable and allowing the confirmed request.

## Scenario matrix

| Scenario | Verified behavior |
| --- | --- |
| Missing SSS number | Pending registration and follow-up are recorded; reviewed contributions remain in the statement |
| Missing PhilHealth number | Same behavior; missing registration does not automatically exclude the employee |
| Missing Pag-IBIG / tax registration | Explicit pending status and follow-up required for the corresponding item |
| Pending registration treated as exempt | Rejected |
| No statutory review at all | Submission and finalization blocked |
| Only three items reviewed | The remaining item is named in the validation error |
| Reviewed zero amount | Accepted with a source and reason; no invented deduction line |
| Reviewed exemption | Requires explicit not-applicable decisions and evidence, rather than a missing number |
| Contributions handled in another cutoff | Explicit treatment and external cutoff reference retained; the second run still requires its own review |
| Employee and employer shares | Employee share reduces net; employer share remains separate |
| Withholding recorded as employer contribution | Rejected |
| “Use line” without a matching line | Rejected |
| Wrong employee / wrong line kind | Rejected |
| Same line reused for two agencies | Rejected |
| Zero treatment with a selected deduction | Rejected |
| Repeated review submission | Does not create or duplicate any deduction |
| Bonus added or deduction removed after review | Prior reviews become stale; submission blocked until re-reviewed |
| Recalculation after review | Regular-run statutory review must be repeated; historical evidence remains |
| Older In review run without statutory evidence | Finalization blocked; Return to draft provides a repair path |
| Finalized review changed | Rejected; snapshot unchanged |
| Another employer or an employee attempts review | Denied |
| Negative net pay | Submission blocked |
| Invalid adjustment amount | Validation error, no partial manual line saved |
| Missing work location / wage information | Existing setup exceptions block submission |
| Unconfirmed classification | Calculation exception blocks automatic premium treatment |
| 10 PM–3 AM shift with 30-minute break | 270 payable/night minutes; configured test rate produces the expected amount |
| Night eligibility unconfirmed | Exception blocks submission; confirmed eligibility plus recalculation resolves it |
| Two employees, different rates/rule profiles and missing different registrations | Each employee keeps the correct rules, contributions, review evidence, and net amount |
| Payslip and CSV after finalization | Finalized net pay and employer-share totals match the itemized statement |
| Missing form values | Inputs remain visible, the review section stays open, and field/toast feedback is shown |
| Separate Regular and Probation/Part-time periods | Verified in the 2026-09-28 run: Regular and Probation profiles were placed in separate selected runs with different inclusive periods |
| All-active employee scope | **Pending next run:** verify that `ALL_ACTIVE` evaluates active payroll employees using the existing behavior |
| Selected employee scope | Verified in the 2026-09-28 run for an active selected employee; empty and cross-organization rejection remain covered by service tests |
| Scope idempotency | Verified in the 2026-09-28 run: reusing the same token with a changed employee selection was rejected |
| Finalized scope immutability | Verified for a voided run in the 2026-09-28 run; finalized-run browser evidence remains pending |
| Employment classification | Verified in the 2026-09-28 run for Regular, Probation, and Mixed metadata; Other remains a future fixture |
| Pay-basis metadata | Verified in the 2026-09-28 run for Hourly, Daily, Monthly, and Mixed values; negative/missing-base validation remains covered by model tests |
| Monthly compensation attendance | **Pending next run:** verify the `MONTHLY_CALCULATION_NOT_CONFIGURED` exception until a conversion formula is approved |
| Monthly compensation register input | Verified in the 2026-09-28 run: monthly employees received `MONTHLY_INPUT_NOT_SUPPORTED` (and the expected no-time exception) |
| Statutory coverage dates | Verified in the 2026-09-28 run for an SSS overlap and a BIR exemption with evidence; all-agency fixtures remain pending |
| Statutory rule versions | Verified in the 2026-09-28 run for overlap rejection; approved-version append-only editing remains pending |
| Payment method history | Verified in the 2026-09-28 run for adjacent Cash and Bank Transfer methods and overlap rejection; no bank credential is stored |
| Obligation opening terms | Verified in the 2026-09-28 run with reviewed cash-advance terms; invalid-term cases remain pending |
| Obligation ledger append-only | Verified in the 2026-09-28 run for deletion rejection; correction/reversal row workflows remain pending |
| Draft obligation proposal | Verified in the 2026-09-28 run: a proposed installment did not change the posted ledger balance |
| Paper timecard source | **Pending next run:** verify reviewed morning, afternoon, overtime, day-off/closed, and signature inputs remain separate from raw attendance |

## Next-run execution checklist

Use a fresh test database and synthetic employees. Run the checks in this
order so failures identify the responsible layer:

1. Create one organization with a reviewed payroll rule profile and at least
   four employees: hourly, daily, monthly, and mixed-basis.
2. Create separate Regular and Probation/Part-time employee groups. Create a
   monthly Regular run and a different period for the Probation/Part-time
   group using **Selected employees**.
3. Re-submit each run with the same idempotency key, then change its dates,
   scope mode, and selected IDs one at a time. Only the exact original request
   may be reused.
4. Add dated statutory coverage records for all four agencies. Verify that a
   Regular/Probation label does not change coverage, that an exemption requires
   evidence, and that overlapping effective dates fail validation.
5. Add one reviewed statutory rule version, attempt an overlap, approve it,
   and verify that an approved version is append-only.
6. Add Cash and Bank Transfer payment methods with adjacent effective dates.
   Attempt an overlap and confirm that no bank account credential field is
   requested or persisted.
7. Add a synthetic cash advance and loan obligation. Preview a proposed
   installment, recalculate the draft, and confirm the ledger balance remains
   unchanged. Exercise correction and reversal as new rows.
8. Add monthly compensation and approved attendance. Confirm the explicit
   monthly conversion blocker. Add daily compensation and a reviewed daily
   input separately, then confirm the daily path still calculates once.
9. Record a paper timecard as reviewed morning, afternoon, and overtime
   segments with a day-off marker and signature evidence. Confirm the source
   record is retained independently from automatic punches.
10. Finalize a synthetic selected run, attempt to change its scope, and verify
    that the operation is rejected. Record any unexplained differences before
    updating the acceptance checkboxes.

### Evidence to retain

For each scenario, retain the test name or reproduction steps, relevant object
IDs, validation/error text, and a screenshot for any browser behavior. Keep
synthetic values only. Do not attach real employee identifiers, bank details,
or government registration numbers to the scenario artifacts.

### Independent arithmetic examples

These are deliberately synthetic amounts, **not Philippine contribution tables**.

- Eight paid hours at PHP 100/hour = PHP 800 gross. Four employee deductions of
  PHP 10 give PHP 760 net. Three employer contributions of PHP 20 total PHP 60
  and do not reduce that net amount.
- A five-hour overnight shift at PHP 100/hour with a configured 10% night premium
  gives PHP 550 gross. A second employee at PHP 200/hour with a configured 20%
  company night policy receives PHP 1,200 gross. Separate PHP 30 deductions give
  PHP 520 and PHP 1,170 net respectively.
- The overnight break scenario uses 4.5 paid hours × PHP 100 × 1.10 = PHP 495.

## Using the review

In a draft run, add reviewed manual employee deductions and employer
contributions under **Add an itemized line**. Then expand **Statutory items**
under the relevant employee statement and select one agency/item at a time.

For each share, explicitly choose a linked line, reviewed zero, another cutoff,
or not applicable. Provide the calculation/source reference and review reason.
For pending registration, record the follow-up. Do not store government ID
numbers in these notes. Save all four reviews after finishing adjustments.

The feature records review evidence, not agency enrollment, remittance, or
statutory calculation approval. There is no automatic SSS, PhilHealth,
Pag-IBIG, or withholding engine. No tax threshold, exemption, or contribution
amount was inferred from a missing number. The payroll reviewer remains
responsible for the correct assessment, amount, allocation, and source.

## Official references consulted

- SSS describes employers' reporting, employee-share deduction, and
  employer-share remittance duties in its [employer guidance](https://www.sss.gov.ph/employer-er/).
  Its [membership guidance](https://www.sss.gov.ph/become-an-sss-member/) covers
  obtaining a missing SS number.
- PhilHealth provides separate [employee registration steps](https://www.philhealth.gov.ph/partners/employers/registration.php)
  and [deduction/remittance procedures](https://www.philhealth.gov.ph/partners/employers/pay_procedures.php).
- Pag-IBIG's [member data form and instructions](https://www.pagibigfund.gov.ph/document/pdf/dlforms/providentrelated/PFF039_MembersDataForm_V12.pdf)
  include employed mandatory coverage even where SSS registration is not yet complete.
- BIR publishes [compensation withholding procedures](https://bir-cdn.bir.gov.ph/local/pdf/RR%20No.%2011-2018.pdf).
  The application requires a reviewed withholding decision instead of assuming
  that every employee owes a positive amount.

These sources support distinguishing registration from contribution treatment.
They do not establish a blanket exemption or certify any test amount as legally
correct. Automatic statutory tables, agency filing, and real payroll reviewer
sign-off remain separate tasks.

## Evidence and repeatability

- `tests/test_payroll_scenarios.py`: 29 scenario tests, with agency/input subcases.
- `tests/test_payroll.py`: existing calculation and payroll lifecycle tests.
- `tests/test_browser.py`: browser workflow and layout checks.
- `.artifacts/payroll-scenarios-before.log`: initial failing statutory-review reproduction.
- `.artifacts/payroll-final-tests.log`: historical 98-test run, all passing.
- Latest local verification: **102 tests passed, 8 skipped**, including the
  selected-run membership immutability regression test.
- `.artifacts/ui/statutory-review-*.png`: browser screenshots.

```powershell
python manage.py migrate
$env:RUN_BROWSER_TESTS = '1'
python manage.py test tests --settings=config.test_settings --noinput
```

The audit migrations add the new action choices without changing existing
payroll records. Structured reviews use the existing statement snapshot field;
previously finalized statements are not rewritten or given invented reviews.
Tests use separate databases and synthetic people. Browser verification used
Chromium; the test results do not constitute legal/accounting certification.
