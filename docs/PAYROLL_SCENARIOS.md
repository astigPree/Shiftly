# Philippine payroll scenario verification

Date: September 26, 2026.

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
- `.artifacts/payroll-final-tests.log`: final 98-test run, all passing.
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
