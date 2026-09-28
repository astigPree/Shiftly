# Payroll workbook analysis and implementation plan

**Prepared:** 2026-09-27  
**Reference file:** `202604.xls`  
**Code reviewed:** Shiftly commit `c2b72dd`  
**Status:** Analysis plus the first daily-pay/component implementation slice. Statutory automation, obligations, cash preparation, and workbook import remain open.
**Intended reader:** A developer or GPT 5.5 Luna implementing one task at a time.

## 1. Answer: does Shiftly already support this workbook?

**Partly. Shiftly cannot yet reproduce this workbook as a complete payroll process.**

Shiftly already calculates hourly work, overtime and some premiums, supports different employee rule assignments, records manual deductions, produces payslips, and locks finalized runs. The workbook adds a daily-rate payroll register, separate allowances, absence/undertime amounts, cash advances and several loan deductions, contribution lookup/helper calculations, and cash denomination reports.

The largest gaps are **daily compensation and allowance policies, automatic statutory assessment, loan balances, and detailed reconciliation/reporting**. A manual line can record an amount today, but that does not mean Shiftly automatically calculates it, remembers an outstanding loan, or prevents the same monthly contribution from being deducted twice.

The workbook also contains calculation and reference problems. Treat it as evidence of the existing business process, not as an unquestionable calculation specification. Preserve the useful workflow; resolve the questionable formulas before implementing them.

### Read this document in this order

1. Sections 2–4: understand what the workbook actually does and its problems.
2. Section 5: distinguish existing features from missing features.
3. Section 6: resolve the business decisions that affect amounts.
4. Sections 7–9: implement the proposed architecture and tasks in order.
5. Sections 10–12: verify arithmetic, rollout, and references.

**Scope of the original analysis:** the source workbook and application behavior were not changed while this document was prepared. The application now has a separate implementation slice for dated hourly/daily compensation, reviewed daily inputs, and reusable pay components; it does not import the workbook's people or balances into the live database.

## Current implementation status (2026-09-27)

The application now supports effective-dated hourly, daily, and monthly compensation metadata, reviewed date-level payroll inputs for daily-paid employees, reusable dated earning/deduction components, component-safe recalculation, component-aware CSV columns, and payslip display of reviewed daily inputs. It also has additive schema support for employee pay-basis/status, statutory coverage evidence, reviewer-gated statutory rule versions, effective-dated payment methods, append-only obligations, and selected employee scope per payroll run. Existing legacy hourly rates and finalized statements remain compatible. The checklist below marks verified behavior; open boxes are deliberate gaps or acceptance work that still requires policy decisions, UI wiring, calculation services, additional tests, or independent payroll review.

Synthetic acceptance inputs for this slice are recorded in [`PAYROLL_REFERENCE_CASES.md`](PAYROLL_REFERENCE_CASES.md). They contain no workbook employee identities or production balances.

Automatic SSS/PhilHealth/Pag-IBIG/withholding calculations, contribution cutoff allocation, loan and cash-advance balances, cash denomination preparation, workbook comparison/import, and the policy decisions D1–D11 remain deliberately manual or unimplemented. Do not describe those areas as automatic payroll features until their tasks below are completed and independently reviewed.

## Owner decisions received (2026-09-28)

The follow-up answers resolve the remaining product decisions that can be represented safely in the application. They do **not** constitute legal approval of Philippine payroll amounts. The workbook and the photographed timecards remain reference material; their employee names, balances, and payment examples are not production fixtures.

### Decisions now represented by the payroll foundation

- Regular and probation/part-time employees may run in separate, user-entered periods. A run owns its inclusive start date, end date, pay date, frequency, and optional selected employee scope.
- Employment status is classification metadata only. It never infers SSS, PhilHealth, Pag-IBIG, or BIR coverage.
- Employee profiles can identify a primary hourly, daily, monthly, or mixed pay basis and a reviewer-entered minimum daily base. Dated compensation supports hourly, daily, and monthly rate versions; monthly conversion formulas remain reviewer-gated until the owner supplies them.
- Statutory coverage, identifiers, exemption evidence, dated payment methods, statutory rule versions, and append-only obligation ledgers now have additive schema support. These controls are not automatically populated and are not yet wired into final payroll calculation.
- A selected run can carry explicit employee memberships. Existing runs default to all active payroll employees for compatibility.

### Rules kept reviewer-gated

- Ordinary overtime defaults remain configurable and review-required; the owner decision of 1.00× is not treated as universal law.
- Holiday/rest-day and premium stacking uses explicit reviewed rule inputs; legacy 1.3/2.3 values remain shadow-comparison fields only.
- Night differential is represented as a configurable 10:00 PM–6:00 AM, 10% policy with per-employee eligibility and work-location timezone, but final stacking still requires an approved matrix.
- SSS, PhilHealth, Pag-IBIG, and BIR versions require effective dates, source, rates/tables, rounding, reviewer, and production approval before automatic use. Until then they remain manual reviewed lines.
- Obligation repayments are proposed during draft/review and must post only from a finalized run. Cash preparation, denomination rules, retention, named approvers, and bank credentials remain outside this schema slice.

### Manual timecard interpretation

The photographed cards contain morning and afternoon punches, overtime punches, day-off/closed markers, and a signature. The intended mapping is one shift with multiple reviewed work segments plus an optional overtime segment. Raw punches should remain separate from reviewed payroll inputs; a correction is an explicit adjustment with source and reviewer rather than an overwrite.

## 2. Workbook inventory and evidence

The file is a legacy Excel binary workbook (`.xls`, OLE/BIFF), not an `.xlsx` file. Inspection read stored cell values, formula records, shared formulas, and references. Stored values are the results saved in the workbook; they are not proof that every formula is correct or freshly recalculated.

Source SHA-256: `0B2F1E8F4FCCD82EBD66CB072B1C18B1E767CB927604869C7F62A48D4E3256AC`.

Personal names, actual individual wages, and loan balances are deliberately omitted from this document. Cell addresses below let an authorized reviewer check the original file. Examples in section 10 use synthetic data.

| Sheet | Observed purpose | Formula cells | Stored Excel errors |
| --- | --- | ---: | ---: |
| `Regular` | Payroll register and helper calculations; employee rows 9–16 | 239 | 0 |
| `Probation` | Similar register; rows 9–15 include zero-work rows | 131 | 0 |
| `Payslip Regular` | Repeated printable payslips linked to register cells | 161 | 0 |
| `Payslip Probation` | Repeated printable payslips, including broken blocks | 195 | 30 |
| `Sheet1` | Empty | 0 | 0 |
| `Cash Count` | Selected net amounts split into notes and coins | 420 | 0 |
| `No ATM` | Another cash denomination layout with broken inputs | 419 | 81 |
| `SSS` | Contribution lookup data, including EE, ER, EC and WISP columns | 0 | 0 |

There are **1,565 formula cells** and **111 stored `#REF!` errors**. An error-free register does not make its linked payslips or cash totals reliable.

The saved net-pay relationship was independently recomputed for all 15 register rows listed above: `E + F + G - SUM(I:Q) + S`. It matched the saved `T` results within PHP 0.000001 before cent rounding. That confirms the arithmetic relationship, not the correctness of its inputs or policies. One row has negative net pay. The cash amount total and denomination total differ by about PHP 0.01703125, or PHP 0.02 when comparing the two rounded totals.

### Period information is inconsistent

- `Regular!H5` says **April 2026**.
- `Probation!I5` says **March 2026**.
- `Payslip Probation!F2` reads the period from `Regular!H5`.
- `Regular!E5` uses `TODAY()`, which is a changing date, not a payroll period definition.

Do not infer all rows belong to April merely from the filename. Before importing or reconciling real records, obtain the intended period start, period end, pay date, and group membership.

## 3. What the workbook calculates

### 3.1 Register inputs and outputs

Both main registers use columns `B:T` for payroll outputs. Their helper columns differ, so a future importer must use a separate explicit mapping for each sheet.

| Output | Register column | Meaning in this file |
| --- | --- | --- |
| Salary rate | B | A period amount derived from a daily basic component and calendar working days; it is not evidence of fixed monthly salary |
| Absent | C | Money removed for the difference between planned and worked days |
| Undertime | D | Money removed for entered undertime minutes |
| Basic | E | Salary amount less absence and undertime |
| Holiday | F | Daily basic component multiplied by an entered holiday quantity/factor |
| Overtime | G | Entered OT minutes converted to money |
| Total compensation | H | Basic + holiday + overtime |
| SSS / PhilHealth / Pag-IBIG | I / J / K | Employee deductions from linked helpers or entered amounts |
| Adjustment | L | Signed input; a negative value inside the deduction sum increases net pay |
| Cash advance | M | Cash advance deduction; Regular combines four input slots |
| Charges | N | Other deduction from a helper input |
| SSS / Pag-IBIG / company loan | O / P / Q | Separate loan deduction inputs |
| Intermediate total | R | Compensation less deductions; despite its heading, this is not the deduction total |
| Allowance | S | Separate allowance, also called COLA on payslips |
| Net pay | T | Intermediate total + allowance |

**Regular helpers:** `W` daily amount, `X` minimum/basic daily component, `Y` calendar working days, `Z` days worked, `AA:AB` hours/minutes, `AE` holiday input, `AF` allowance per day, `AG` adjustment, `AM` undertime minutes, `AN` overtime minutes, `AS:AU` contribution inputs, `AV:AY` four cash advances, `AZ:BA` agency loan deductions. Some additional helper columns are blank or not used by the main outputs.

**Probation helpers:** `W:X` daily amounts, `Y:Z` planned/worked days, `AA` hours, `AC` holiday input, `AD:AE` allowance-related inputs, `AK:AL` undertime/overtime minutes, `AQ:AS` contributions, `AT` cash advance, `AU:AV` agency loans. These are not interchangeable with Regular column letters.

### 3.2 Calculation flow

For the common Regular row pattern, the readable calculation is:

```text
period_basic_before_time_deductions = daily_basic_rate × planned_working_days
absence_amount = daily_basic_rate × (planned_working_days − worked_days)
undertime_amount = daily_basic_rate ÷ 8 ÷ 60 × undertime_minutes
basic_earned = period_basic_before_time_deductions − absence_amount − undertime_amount

holiday_amount = daily_basic_rate × entered_holiday_factor
overtime_amount = daily_OT_basis ÷ 8 ÷ 60 × entered_overtime_minutes
compensation_subtotal = basic_earned + holiday_amount + overtime_amount

deduction_sum = SSS + PhilHealth + PagIBIG + signed_adjustment
             + cash_advance + charges + SSS_loan + PagIBIG_loan + company_loan
allowance_earned = worked_days × daily_allowance
                 − daily_allowance ÷ 8 ÷ 60 × undertime_minutes
net_pay = compensation_subtotal − deduction_sum + allowance_earned
```

These describe this workbook, **not approved Philippine pay rules**. The fixed eight-hour divisor, eligibility, premium basis, holiday factors, and allowance deductions all need explicit policy decisions.

The overtime basis is column **W**, while basic/absence/undertime use column **X**. Those values can differ. Do not collapse them into one rate without resolving D2/D5.

Traceable examples:

- `Regular!C9` uses `B9/Y9*(Y9-Z9)`.
- `Regular!E9` uses `B9-C9-D9`; `H9` uses `E9+F9+G9`.
- `Regular!M9` adds `AV9+AW9+AX9+AY9`.
- `Regular!R9` uses `H9-SUM(I9:Q9)`.
- `Regular!G9` uses `W9/8/60*AN9`; `Probation!G9` uses `W9/8/60*AL9`. Neither formula adds an overtime multiplier.
- `Regular!S9` uses `Z9*AF9-(AF9/8/60*AM9)`.
- Allowance formulas are not uniform: `S12` adds `AG12`, while `S15:S16` subtract `AQ15:AQ16`. `AF9` derives allowance from `W9-X9`; other rows contain directly entered allowance amounts.
- `Regular!AC9` calculates a days/hours/minutes alternative, but the main `E9` does not reference it. Do not assume filling the hour/minute helpers changes the register's main basic pay.
- `Probation!S9` uses `Z9*AD9-(AD9/8/60*AK9)+AF9`. Here the additive input is in a column headed **Per day**. Its actual business meaning needs confirmation; do not rename it an approved adjustment merely from the formula.

### 3.3 Contributions and tax

The `SSS` sheet contains compensation brackets and separate employee (EE), employer (ER), Employees' Compensation (EC), and WISP columns. Its named range **`SSSS` is `SSS!$B$5:$J$57`**, although the table continues through row 65.

The Regular employee SSS path is `I9 -> BD9 -> VLOOKUP($BC$9,SSSS,6)`, where `BC9=E9`. The sixth lookup column is `SSS!G`, the regular EE component. The ER helper `BE9` selects column 5 (`SSS!F`), and `BF9=SUM(BD9:BE9)` combines those two amounts. Despite the **Total EE** label, `BF` is EE plus ER. This does not assemble all the EC/WISP components present in the table. There is no completed statutory remittance report.

There are also wrong-row references: `BD15` and `BD16` use `BC14`, and `BE16` uses `BC15`. A separate helper `BI10:BI16` remains anchored to `BC9`. Main employee deductions `I9:I16` use `BD`, not `AS/BI`; distinguish an unused wrong helper from a wrong reference that actually reaches net pay.

The Regular PhilHealth path is `J9 -> AT9 -> IF(BM9<=250,250,BM9)`, with `BM9=BL9`, `BL9=BC9*BK9`, `BC9=E9` and `BK9=0.025`. Thus it uses a basic amount already reduced for absence/undertime, applies a PHP 250 floor, and has no ceiling in this formula. This is observed workbook behavior, not a validated contribution policy.

Regular Pag-IBIG uses `K9=AU9`, an entered amount. Probation SSS and PhilHealth use manually entered `AQ`/`AR` helpers; Pag-IBIG is entered directly in `K`. Zero values in those rows do not establish exemption.

Payslips include a **BIR TAX** label, but there is no complete withholding-tax calculation demonstrated in these registers. A label or blank cell is not an implemented tax engine. For example, `Payslip Regular!M9` references `Q18` on that same payslip sheet, which has no populated cell in the inspected file.

### 3.4 Payslips and cash preparation

- Payslips link to register amounts and calculate earnings, deductions, COLA, and net earnings. They also have a signature area.
- `Cash Count!B3:B33` supplies selected payment amounts. `D:N` divides those amounts into denominations of 1000, 500, 200, 100, 50, 20, 10, 5, 1, 0.25 and 0.01 using `INT` and successive remainders.
- `Cash Count!B34` totals the selected amounts; `O36` totals the calculated denomination amounts.
- `No ATM` is a similar layout. Its name suggests a cash-payment grouping, but the workbook does not establish a reliable bank/payment-method master record.
- Neither sheet proves that money was transferred, released, or received.

## 4. Workbook issues that must not become product behavior

| Finding | Evidence | Required treatment |
| --- | --- | --- |
| Broken references | 30 errors in `Payslip Probation`, 81 in `No ATM`; examples `Payslip Probation!C87`, `No ATM!B3:B5` | Flag and reject affected imported results; never convert errors to zero |
| Conflicting period labels | `Regular!H5`, `Probation!I5`, `Payslip Probation!F2` | Require explicit dates; do not identify periods by filename or `TODAY()` |
| OT uses straight-time conversion | `Regular!G11` with `AN11`; `Probation!G12` with `AL12` | Review the intended multiplier and whether base pay already includes those hours; do not replace Shiftly's existing OT rules with this formula |
| Holiday input mixes meaning | Label says number of days, but inputs include 1.3 and 2.3 | Store actual dates, day type, paid hours, and reviewed multipliers separately |
| Negative adjustment acts as a credit | Negative values in register column L are subtracted in `SUM(I:Q)` | Classify a correction as an earning, deduction, or refund/reversal with its own basis treatment |
| Negative net pay reaches cash count | `Regular!T9` is negative; linked `Cash Count!D3` becomes a negative note count | Retain Shiftly's negative-net blocker; explicitly resolve any unpaid balance |
| Cash allocation does not exactly reconcile | `Cash Count!B34` and `O36` differ; sub-cent values flow into `INT` | Round monetary lines under a reviewed policy and calculate cash denominations using integer centavos |
| Allowance rules vary by employee row | `Regular!AF9`, `S9`, `S12`, `S15:S16` | Use named, dated component assignments; do not encode employee-row special cases |
| Partial and cross-group totals | `Regular!T17` sums rows 9–16; `T19` only rows 9–14; `Probation!T19` imports `Regular!T16` | Define group membership and reconciliation totals explicitly; prevent duplicate employee payment |
| Payslip can pull an unrelated row | `Payslip Probation!C3/C6` use employee row 10 while `C17` uses `Probation!S12`; right-hand block similarly uses another allowance row | Generate a payslip from one statement ID; test with different nonzero amounts so mapping bugs cannot hide behind zeros |
| Parallel statutory helper chains disagree | `AS/BI` and `BD` can differ, but register `I` uses `BD`; PhilHealth also applies a floor | Trace the actual dependency chain; do not assume every differing helper is an intentional override |
| SSS references use other employees | `BD15:BD16 -> BC14`, `BE16 -> BC15`; separate `BI10:BI16 -> BC9` | Resolve by employee and applicable date; test different compensation per employee |
| SSS lookup range is incomplete | `SSSS` ends at row 57 while the table continues to row 65; lookup returns regular share only | Validate complete bracket coverage and regular/provident/EC component totals |
| PhilHealth helper has a questionable basis/bounds | `BC=E` after absence/UT; `AT=MAX(250,BC*0.025)` with no upper cap | Confirm the agency-specific salary basis, coverage, floor and ceiling from the applicable reviewed rule version |
| Two-decimal display can hide precision | Register money cells use `0.00` formatting while formulas retain sub-cent values without line rounding | State where rounding occurs and reconcile rounded lines to net; never compare only formatted screenshots |

**Conclusion:** matching every saved workbook total exactly is not the acceptance criterion. Matching an agreed, corrected set of cases is. Keep discrepancies visible rather than introducing hidden adjustments to force equality.

## 5. Feature comparison with current Shiftly

Legend: **Supported** = dedicated functionality exists; **Partial/manual** = related capability exists but not the complete process; **Missing** = requires implementation.

| Workbook need | Shiftly today | Reuse or extend |
| --- | --- | --- |
| Employee-specific pay rules | Supported: dated overrides and company default | `PayrollRuleProfile`, `PayrollRuleSet`, `PayrollRuleAssignment`; `resolve_effective_rule()` |
| Employee hourly rate history | Supported | `EmployeePayRate`, `effective_pay_rate()` |
| Daily basic rate and calendar/day quantities | Supported through dated daily compensation and reviewed period inputs | Complete mixed/monthly conversion services; do not disguise daily pay as an unexplained hourly rate |
| Actual work, breaks, overnight hours | Supported; stronger than this workbook's aggregate inputs | `_worked_intervals()`, `split_worked_segments()` |
| Absence/undertime amounts | Partial: time quantities exist; hourly pay already excludes unworked time | Basis-specific pay calculation, reviewed time quantities |
| Ordinary overtime | Supported using configured daily threshold and multiplier | `calculate_payroll_run()` |
| Ordinary night differential | Supported; workbook has no dedicated night calculation found | Preserve current night-window and timezone logic |
| Rest/holiday premiums | Partial: reviewed single cases; complicated combinations need manual review | Existing holiday models and exception workflow |
| Daily allowance/COLA and recurring charges | Manual amounts only | Add structured components and dated employee assignments |
| Signed adjustments | Positive earning/deduction lines supported; negative amount inputs rejected | Explicit correction/refund types; never relax amount validation globally |
| SSS/PhilHealth/Pag-IBIG calculations | Manual reviewed lines only; reviewer-gated statutory rule/coverage schema added | Add approved effective tables, cutoff allocation, and calculation services |
| Statutory review evidence | Manual review layer plus dated coverage/rule evidence schema | Preserve `payroll/statutory.py`; wire generated lines to approvals deliberately |
| Agency/company loans and cash advances | Append-only obligation and transaction schema added; no automatic deductions yet | Add preview/finalization posting services, priority/defer rules, and UI |
| Regular/Probation groups | Effective employee employment-status and pay-basis metadata added | Keep status separate from rule profile and statutory eligibility; add history if needed |
| Payslips | Supported: employee-owned finalized statements and printable HTML | Add component detail and rate/quantity explanations |
| Payroll register export | Partial: finalized CSV totals exist | Add classified contribution/allowance/loan columns and reconciliation |
| Cash denomination report | Missing | Optional preparation report over finalized statements; no transfers |
| Custom cutoffs | Run dates/pay date are user-entered; frequency validation still applies to regular runs | Add an explicit cutoff policy when the owner supplies its rules; never infer from workbook dates |
| Fixed monthly salary, 13th month, annual tax engine | Missing; not demonstrated as working calculations in this file | Separate future scope, not prerequisite for daily-register parity |

### Code map for the implementer

| File | Existing responsibility |
| --- | --- |
| `payroll/models.py` | Settings, rule profiles/versions/assignments, hourly rates, holidays, runs, statements, lines, time entries, exceptions, snapshots |
| `payroll/services.py` | Rule resolution, interval splitting, calculation, line adjustments, review/finalization, reconciliation |
| `payroll/statutory.py` | Manual statutory treatment evidence and stale-review fingerprints; **not contribution calculations** |
| `payroll/forms.py` | Employer setup, rate/assignment, run, adjustment, and statutory review forms |
| `payroll/views.py` | Readiness, bulk/individual assignment, employer pages, export, employee statements |
| `employees/models.py` | Employee identity, code, job title, Active/Inactive; no employment-category or service-date history |
| `timesheets/models.py` | Worked/payable/late/undertime minutes and approval state |
| `templates/payroll/` | Existing page templates, including `employee_profile.html`, `run_detail.html`, `statement.html` |
| `static/css/payroll.css` | Payroll presentation; follow `SHIFTLY_PROJECT_DESIGN_SKILL.md` for UI changes |
| `audit/models.py`, `audit/services.py` | Audit event choices and recording |
| `tests/test_payroll.py`, `tests/test_payroll_scenarios.py`, `tests/test_browser.py` | Existing behavioral and UI coverage to preserve |

### Existing calculation differences to preserve deliberately

- Shiftly values **exact worked seconds** after actual breaks, using `Decimal`; calculated line amounts use `ROUND_HALF_UP` to two decimals. The workbook uses entered aggregate quantities and often keeps sub-cent intermediates.
- Shiftly's base line already includes all worked hours. Its ordinary overtime line adds only the premium: `OT hours × hourly rate × (multiplier − 1)`. Comparing that line alone with the workbook's full OT amount is misleading.
- Approved time, reviewed rules, profile/location evidence, exceptions, all four statutory reviews, and nonnegative net pay currently gate payroll processing.
- Recalculation replaces calculated lines and preserves manual lines. Finalized statements remain locked; corrections use an off-cycle run.
- Readiness cards currently check current hourly setup. They are not a complete validation of the selected payroll period.

## 6. Decisions required before monetary implementation

Record answers in a reviewed policy note. These are focused questions for the payroll owner; the coding model must not invent the answers.

| ID | Decision | Recommended design until confirmed |
| --- | --- | --- |
| D1 | What actual dates do both register groups cover? What are the cutoffs and pay date? | Explicit dates; block ambiguous import |
| D2 | What do Daily (`W`), Minimum (`X`), and allowance represent? Which components belong in each premium/contribution/tax basis? | Separate compensation and allowance components; never assume the column named Minimum is a current legal wage |
| D3 | Are worked days entered manually, derived from attendance, or mixed? How are partial days, paid holidays, approved paid absence, and Saturdays handled? | One selected, auditable source per employee/period; no automatic merging of duplicate quantities |
| D4 | What does holiday input 1.3 or 2.3 mean: days, a combined premium, or an amount factor? | Replace it with dated holiday events and reviewed policies |
| D5 | Is straight-time OT in the workbook intentional or an error? What is the applicable base and premium? | Preserve configured Shiftly overtime until a reviewed replacement is approved |
| D6 | After correcting the wrong references, what contribution bases/coverage apply, which month/cutoff is being charged, and are any overrides intended? | Preserve manual reviewed mode; require an explicit override/allocation reason |
| D7 | What do negative adjustments represent: extra earnings, a deduction refund, an advance correction, or another item? | Explicit transaction type and original-reference link |
| D8 | Do CA1–CA4 represent advances already received? What are loan opening balances, repayment agreements, installments, and remaining balances? | Import only authorized opening obligations; do not infer a balance from one month's deduction |
| D9 | Why are some regular rows excluded from one total and included in another group? | Explicit report/payment grouping, separate from employment classification |
| D10 | What should happen when deductions exceed earnings? | Block finalization; require an explicit reviewed repayment/carryforward decision; never silently clamp net to zero |
| D11 | What rounding policy applies to pay lines, contribution shares, installment allocations, and cash payout? | Preserve existing cent rounding unless a reviewed policy version replaces it |

Regular/probationary labels alone must never automatically set contribution exemption, night eligibility, or wage coverage. Employment category, compensation basis, assigned payroll policy, payment method, and statutory coverage are separate concepts.

### Workbook answers received on 2026-09-27

The supplied workbook review resolves several **legacy comparison** questions, while leaving policy approval separate. These findings may be used to build a read-only shadow calculator and import preview:

| Area | Workbook evidence | Shiftly treatment |
| --- | --- | --- |
| Period | April 2026 monthly payroll; pay date appears to be 1 May 2026; no explicit cutoff dates | Require owner confirmation before importing or finalizing; retain the March 2026 probation label as a period inconsistency |
| Pay basis | Daily-rated employees, 8-hour day; Daily and Minimum are separate bases; allowance is separate | Use daily compensation, reviewed date-level quantities, and dated components; do not infer monthly or hourly contracts |
| Quantity source | Calendar days, worked days, UT minutes, OT minutes, and manual holiday-equivalent units | Prefer approved attendance/timesheets; use reviewed period inputs for authorized manual exceptions or legacy comparison |
| Overtime | Workbook uses straight-rate `Daily / 8 / 60 × OT minutes` | Keep Shiftly's configured multiplier until the payroll owner approves whether legacy parity or the reviewed legal multiplier is required |
| Night work | No workbook night-differential rule | Continue using Shiftly's separately reviewed night rule; do not derive one from the workbook |
| Statutory data | SSS lookup table; formula-based PhilHealth; flat/manual Pag-IBIG; no usable BIR tax engine | Treat as reference/manual evidence until effective dates, coverage, source, and reviewer approval are recorded |
| Loans and advances | Period deduction columns only; no balances or repayment terms | Require obligation opening balances and terms before creating repayment postings |
| Cash | Denominations are PHP 1,000, 500, 200, 100, 50, 20, 10, 5, 1, 0.25, and 0.01; cash amounts do not reconcile after truncation | Build integer-centavo reporting only after the rounding and payment-group policy is approved; block negative net pay |
| Import | Names only, no employee IDs; both comparison and selective reviewed import are recommended | Require explicit employee mapping, source hash, sheet/row validation, and reference-only computed totals before writes |
| Governance | No preparer/approver or retention policy is encoded | Require separate prepared/approved roles, two or more shadow cycles, zero unexplained line differences, and reviewer sign-off |

The workbook review narrows the remaining decisions to: April period/cutoff/pay-date confirmation; Regular/Probation coverage intent; approved overtime multiplier; night and holiday/rest-day policy; current statutory sources and effective dates; obligation terms; rounding; employee mapping; approval roles; retention; and shadow-run acceptance. Workbook observations are not legal approval and must not silently change the live payroll defaults.

## 7. Proposed architecture

Everything in this section is **proposed**, not already implemented. Suggested model/module names may be adjusted to project conventions; the behaviors and constraints are required.

### 7.1 Extend the current pipeline

```text
Selected payroll period + eligible employees
    -> resolve dated compensation + existing rule assignment
    -> approved attendance OR reviewed period quantities
    -> basic earnings + premiums + allowance components
    -> agency-specific contribution bases and assessments
    -> loan/advance installment preview + other reviewed deductions
    -> itemized statement + exceptions + immutable calculation preview
    -> employer review
    -> atomic finalization and once-only ledger postings
    -> employee payslip + register + optional cash report
```

Do not build a second payroll engine in templates, JavaScript, or Excel. Keep pure calculations in Python services, use `Decimal`, and keep ownership/lifecycle checks in shared transactional services.

### 7.2 Proposed records

| Record | Minimum purpose and fields |
| --- | --- |
| `EmployeeCompensationVersion` | Employee/org, effective dates, basis initially `HOURLY` or `DAILY`, amount, currency, reviewed day-length/conversion policy, source/reviewer |
| `PayrollComponentDefinition` | Org-scoped stable code, label, earning/deduction role, allowed calculation method, separately reviewed inclusion rules for premium, SSS, PhilHealth, Pag-IBIG and tax bases |
| `EmployeeComponentAssignment` | Employee, component, effective dates, fixed/per-day/per-hour amount, recurrence/cutoff allocation and reviewed proration policy |
| `PayrollPeriodInput` | Employee, exact period, reviewed quantities allocated to local work dates, source/import reference, input mode, reviewer/time; only needed for approved aggregate imports or non-attendance entitlements |
| `StatutoryRuleVersion` | Agency, effective dates, applicable classification, brackets/rates/floors/caps, source and reviewer, immutable reviewed version |
| `StatutoryAssessment` + allocations | Employee/org/agency/month/revision, applicable base, EE/ER amounts, prior finalized allocations, remaining amount, linked statement postings |
| `EmployeeObligation` + repayments | Loan/advance type, authorized opening balance/terms, creditor reference, installment policy, append-only finalized repayments and linked corrections |

All employee-linked records must enforce the same organization on every related object. Store calculation inputs and stable source/version IDs in snapshots. Do not rely only on text labels or a mutable current employee profile.

**Hourly compatibility:** retain existing hourly rate records and behavior initially. One resolver must select the new compensation version or the legacy hourly rate deterministically. Reject ambiguous overlap; do not pay both. Do not rewrite old finalized snapshots.

**Daily pay:** choose one reviewed method per period. A worked-quantity method pays approved days/fractions and does not then subtract the same absence again. A planned-days-minus-absence method may show that breakdown, but must reconcile to the same approved paid quantity. Track whether undertime is already reflected in the quantity.

**Dated quantities:** a period total alone cannot resolve a mid-period rate, rule or component change. Require date-level allocations in those cases; block calculation until they are provided. Never spread a total across dates by guessing. Begin employee discovery from eligible employees and approved dated inputs, then attach attendance. The current attendance-only grouping would otherwise omit legitimate approved daily/non-worked entitlements.

**Automatic statutory amounts:** place calculators in a proposed `payroll/statutory_calculations.py`; preserve `payroll/statutory.py` as the evidence layer. Its current review function accepts only manual lines, so generated statutory lines need a deliberate extension with agency/share/assessment identity and equivalent review safeguards.

**Monthly allocation:** assess a monthly target using that agency's approved basis, then allocate to cutoffs. Draft previews are not prior paid/deducted amounts. Only finalized postings count. Distinguish contribution month from pay date and work period explicitly.

**Loans:** previewing/recalculating a run must not reduce balances. Finalization posts a repayment once. Use unique source keys and row locks, and cap a proposed installment to the remaining authorized balance. Insufficient net requires review, not an implicit write-off or silently changed installment.

### 7.3 Integration points that must change together

| Existing function | Required extension |
| --- | --- |
| `calculate_payroll_run()` | Resolve pay basis, quantity source, components, contribution assessment, and installment previews; make employee eligibility basis-aware |
| `_refresh_statement()` / `_assert_statement_reconciles()` | Keep gross, employee deductions, ER contributions and net consistent across the new categories |
| `_record_preview()` | Snapshot source IDs, versions, quantity, rate, formula method, intermediate amounts, rounding and engine version |
| `submit_for_review()` | Reject unresolved policies, invalid mappings, missing coverage, stale inputs and unbalanced statements |
| `finalize_payroll_run()` | Recheck source versions, lock assessment/obligation records, post once and finalize in one transaction |
| `return_payroll_to_draft()` / `void_payroll_run()` | Release draft claims if introduced; never change finalized postings |
| `add_adjustment()` / `remove_adjustment()` | Preserve manual corrections, classification and review invalidation; do not let generic lines bypass statutory/loan allocation controls |
| `statement_fingerprint()` | Include new source revisions, component classifications, assessment allocations and correction references |
| `_payroll_readiness()` and employee list | Show basis-aware setup; use shared period-validation services for actual enforcement |
| `run_export()` and `statement.html` | Show structured line categories and their calculation explanations; preserve historical output |

**Freshness:** the existing review fingerprint binds stored snapshots and lines. New code must also detect changes to their external source records before review/finalization. Require recalculation instead of silently changing reviewed amounts.

**Existing guard to strengthen:** individual assignment checks against finalized payroll exist in forms, but the bulk-assignment form does not have the equivalent finalized-period check. Centralize essential dated-mutation checks in a shared service used by both paths before extending assignments further.

## 8. Implementation tasks

Complete one task and its acceptance criteria before marking it done. If a listed policy decision is unanswered, document the blocker for that task and continue only independent work. A checked item means the corresponding application behavior and repository evidence exist; it does not certify legal or accounting approval.

Suggested delivery stages:

1. **Daily pay and allowance pilot:** WB-00 through WB-03, the relevant WB-06 safeguards, WB-07 output and WB-10 verification. Contributions and loan amounts remain explicitly manual during this stage.
2. **Contribution and loan automation:** WB-04 and WB-05, with WB-06/07/10 extended for each. Do not label the pilot as having these engines before this stage is complete.
3. **Optional operational tools:** WB-08 cash preparation and WB-09 comparison/import. These do not control whether the core payroll calculation can work without a spreadsheet.

### WB-00 — Agree the corrected reference cases

- [ ] **Dependencies:** none; resolve D1–D11 with the payroll owner.
- [ ] Record a sheet/column mapping, intended periods, meanings of input quantities, and accepted corrections to section 4 findings.
- [x] Build synthetic reference cases with nonzero, different amounts for each employee. Keep real workbook data out of Git.
- [ ] Record expected component amounts, gross, each deduction, ER share, net, and approved rounding. Label workbook behavior separately from approved behavior.
- [x] **Files:** this document, `docs/PAYROLL_REFERENCE_CASES.md`, and synthetic fixtures under `tests/`.
- [ ] **Done when:** an implementer can calculate each expected result without guessing what a workbook column means. No production import or default legal rates are enabled yet.

### WB-01 — Add explicit compensation basis and shared guards

- [ ] **Dependencies:** WB-00 decisions D2/D3/D5.
- [x] Add dated compensation records and a single resolver; support the daily-rate case while preserving hourly behavior.
- [x] Store basic daily rate separately from any allowance. Make day length and premium conversion explicit and reviewed.
- [x] Enforce tenant ownership, positive finite amounts, date validity, overlapping-source rejection and finalized-period protection in the current compensation and component assignment flows.
- [x] Do not add employment category until reporting requires it; never infer it from Active/Inactive or use it as an exemption rule.
- [x] **Files:** `payroll/models.py`, `payroll/services.py`, `payroll/forms.py`, `payroll/views.py`, and migration `0004_payrollcomponentdefinition_and_more.py`.
- [x] **Done for the implemented slice:** schema and resolver distinguish hourly and daily contracts with dated policies, reject ambiguous sources, and preserve legacy hourly/finalized records. Mixed-case acceptance remains under WB-02.

### WB-02 — Calculate daily quantities, absence and undertime once

- [ ] **Dependencies:** WB-01; D3/D4/D5 resolved.
- [x] Implement a pure daily basic-pay calculator with explicit quantity source and fractions of a day. Do not equate a day with any nonzero attendance automatically.
- [x] Prefer approved attendance. Add reviewed period input only when aggregate import or non-attendance entitlement is authorized; store provenance and prevent duplicate attendance/import payment.
- [x] Discover eligible employees from approved period inputs as well as attendance. Replace `NO_PAYROLL_TIME` only with a basis-aware decision for legitimate approved inputs; keep blockers for unexplained missing attendance. Date-level inputs are required for the implemented daily register path.
- [x] Explain planned days, unpaid absence, paid days, already-applied undertime and final basic amount in the daily snapshot.
- [x] Reuse employee-local timezone and effective rule resolution for reviewed daily inputs. A full leave-management system remains separate scope.
- [x] Preserve configured overtime and represent it as a premium on top of the base, avoiding double payment.
- [x] **Files:** `payroll/compensation.py`, `payroll/services.py`, models/forms, and `tests/test_payroll.py`.
- [ ] **Done when:** a mixed hourly/daily run uses each employee's assigned policy correctly; full days, partial days, undertime, no-work, overnight and mixed-rate cases reconcile; no absence/UT/OT amount is counted twice.

### WB-03 — Add allowance and deduction components

- [ ] **Dependencies:** WB-01/WB-02; D2/D7/D11 resolved.
- [x] Add definitions and dated employee assignments for fixed, per-day and per-hour components; start with daily allowance/COLA and reviewed recurring charges.
- [x] Allow shared definitions with different employee amounts. Reuse existing payroll-rule assignments for policies rather than copying policy fields onto every employee.
- [x] Make component basis inclusion explicit per calculation. Contribution and tax treatment remains a separate open task.
- [x] Add stable generated-line identity and metadata. Recalculation replaces generated components and preserves manual entries without duplicates, including separate provenance for mid-period assignments.
- [ ] Use positive earning/deduction amounts; add explicit refund/reversal handling for corrections where ordinary earnings would misstate taxable/contribution bases.
- [x] **Files:** `payroll/models.py`, `payroll/services.py`, `payroll/forms.py`, `payroll/views.py`, payroll templates, and migration `0004_payrollcomponentdefinition_and_more.py`.
- [ ] **Done when:** allowances with different rates and UT policies, one-off corrections, repeat recalculation, and mid-period assignment changes remain explainable and reproducible.

### WB-04 — Add reviewed contribution calculations and cutoff allocation

- [ ] **Dependencies:** WB-02/WB-03; D6/D11; authoritative rules and eligibility approved for the applicable period.
- [ ] Implement separate pure calculators for SSS, PhilHealth and Pag-IBIG using dated rule versions. Do not copy a worksheet rate/table without confirming its date, bracket boundaries, coverage and pay basis.
- [ ] Include cases beyond the workbook's truncated `SSSS` range and cases with different employee bases that expose wrong-row references. Independently verify regular/provident/EC components and PhilHealth floor/ceiling/basis treatment.
- [ ] Keep regular SS, EC and provident components identifiable; keep EE and ER totals separate. Do not use gross earnings as every agency's basis.
- [ ] Add monthly assessments and finalized cutoff allocations. Cover first cutoff, second cutoff, later corrections, and changed compensation within the month.
- [ ] Keep manual evidence mode. Require explicit manual override/replacement relations so automatic and manual amounts cannot both charge the same agency/share/month slot.
- [ ] Extend statutory review to eligible generated lines. Pending registration must not become an automatic zero or exemption.
- [ ] Retain the existing withholding review as manual until a separately approved tax engine exists; the workbook does not supply one.
- [ ] **Files:** new statutory calculation module, `payroll/statutory.py`, models/services/forms/views, migrations, statutory review template.
- [ ] **Done when:** independently approved boundary cases, EE/ER separation, multiple cutoffs, pending registration, overrides and recalculation all reconcile without duplicate deductions.

### WB-05 — Track cash advances and loans

- [ ] **Dependencies:** WB-03; D8/D10 resolved.
- [ ] Model separate advance, SSS loan, Pag-IBIG loan and company-loan obligations. Capture authorized opening balance and installments; do not treat a contribution as a loan.
- [ ] Map CA1–CA4 to distinct referenced transactions when their meaning is confirmed. Do not limit the database to four spreadsheet columns.
- [ ] Preview due deductions without posting; finalize repayments atomically once. Keep remaining balance and history visible.
- [ ] Handle partial/final installments, skipped installments with reason, external repayment, opening-balance corrections and insufficient-net exceptions.
- [ ] **Files:** models/migrations, proposed `payroll/obligations.py`, services/forms/views, audit choices and tests.
- [ ] **Done when:** refresh, recalculation, retry, concurrent finalization and off-cycle correction cannot duplicate repayment or silently change an outstanding balance.

### WB-06 — Integrate review, snapshots and finalization

- [ ] **Dependencies:** each preceding monetary module being enabled. Apply these safeguards with that module, not only at the end.
- [ ] Make preview input fingerprints include compensation, component, contribution and obligation revisions; detect external changes after preview.
- [ ] Preserve source classifications and manual review evidence. A changed amount or policy requires recalculation/review again.
- [ ] Lock shared balances/assessments in a deterministic order, validate remaining allocations, create unique postings, and finalize in the same transaction.
- [ ] Make regular/off-cycle behavior explicit: off-cycle corrections must not regenerate full recurring earnings or installments.
- [ ] Preserve negative-net and unresolved-exception blockers. Do not silently waive deductions, create a new loan, or erase an old one.
- [ ] **Files:** service integration points in section 7.3, models/constraints, audit, direct-service tests.
- [ ] **Done when:** stale, cross-tenant, duplicate and concurrent operations fail safely; previous finalized payslips stay unchanged after migrations and policy edits.

### WB-07 — Improve the register and payslip output

- [ ] **Dependencies:** WB-03/WB-04/WB-05 for enabled columns.
- [x] Add classified columns or export fields for the implemented basic, holiday, OT, night differential, component earnings, other earnings, deductions, ER shares, gross, and net values. Statutory and loan columns remain open with WB-04/WB-05.
- [x] Explain base rate, quantity and component amount in snapshots and statement detail. Distinguish compensation before components from gross including components when comparing against the workbook.
- [ ] Group/filter by explicit category if approved; totals must include exactly the displayed/exported scope and identify excluded rows.
- [x] Build every employee payslip from its statement record, never sheet-row positions. Keep employee access restricted to their own finalized records.
- [x] Keep existing CSV formula-injection protection; export amounts from finalized snapshots.
- [ ] **Files:** `payroll/views.py:run_export`, payroll templates, report services, tests.
- [ ] **Done when:** employee payslip totals, statement totals, register rows and grand totals reconcile to the cent, including employees with distinct nonzero allowances and multiple deductions.

### WB-08 — Add an optional cash preparation report

- [ ] **Dependencies:** WB-07; D9/D11 resolved. This is a report, not money movement.
- [ ] Select authorized finalized statements marked for cash preparation; require an explicit group/method instead of copying the `No ATM` row list.
- [ ] Convert each rounded net amount to integer centavos. Divide by approved available denominations using integer division/remainders.
- [ ] Reject negative amounts. If available denominations cannot represent the amount, show an unresolved remainder; do not underpay by truncation.
- [ ] Sum per-employee counts and verify `sum(count × denomination) + unresolved_remainder = selected_net_total`.
- [ ] **Files:** proposed `payroll/reports.py`, views/URLs/template, tests.
- [ ] **Done when:** denominations exactly reconcile for every employee and the total; repeated report generation does not mark a payment as transferred or received.

### WB-09 — Add safe workbook comparison/import tooling

- [ ] **Dependencies:** WB-00 mappings and each imported feature's completed implementation.
- [ ] First build a read-only comparison mode. Show original cell/result, normalized component, Shiftly result, difference and reason.
- [ ] Map employee codes through an explicit reviewed mapping. Names and row numbers are not permanent identities.
- [ ] Detect mismatched periods, broken refs, hidden/unused totals, duplicate rows, unknown headers, unsupported formulas, invalid dates and negative net.
- [ ] Accept only a defined data schema for import. Never execute arbitrary spreadsheet formulas/macros as server-side payroll code.
- [ ] Preview all writes and keep import hashes, mappings and source references. Prevent repeated imports from creating duplicate inputs/obligations.
- [ ] Keep workbook import optional: normal attendance-based payroll must not depend on Excel or the original file being present.
- [ ] **Files:** proposed management command/import service and an employer preview page only if needed; synthetic fixtures.
- [ ] **Done when:** clean synthetic data reconciles; this workbook's known defects produce explicit review findings, not silently accepted pay.

### WB-10 — Complete UI, guide and rollout verification

- [ ] **Dependencies:** only expose completed modules; preserve existing design conventions.
- [x] Employee pay profile: compensation basis, current rate, dated component assignments, reviewed period inputs, and existing rule assignment. Obligation balances/history remain open with WB-05.
- [ ] Run detail: calculation breakdown, contribution month/cutoff, manual override reasons, proposed repayments, blockers and total reconciliation.
- [ ] Provide pagination, consistent action buttons, compact form controls, field errors/toasts, and confirmations for irreversible actions.
- [x] Update `SHIFTLY_GUIDE_README.md`, relevant Phase 11 entries in `SHIFTLY_PROJECT_TASKS.md`, and verification notes without claiming unimplemented features are complete.
- [ ] Verify the cases in section 10 and use at least two shadow cycles with independently reviewed results before enabling these outputs for live payroll.
- [ ] **Done when:** the payroll owner signs off corrected reference cases and shadow differences; documentation states exactly what is automatic, manual, and unsupported.

## 9. Small-step instructions for GPT 5.5 Luna

1. Read this document and the current code before editing. The code may have changed since `c2b72dd`.
2. Select the first open task whose decisions and dependencies are satisfied. Do not implement every task in one large edit.
3. State the task ID and specific files you will change. Reuse existing rule assignments, run lifecycle, templates, toasts and permissions.
4. Add the smallest model/service change needed. Keep formula methods explicit; never evaluate formula text supplied by a workbook/user.
5. Where schema changes are needed, create migrations and describe compatibility with existing data. Never modify the user's live payroll records to fabricate fixtures.
6. Implement server-side validation before exposing controls. A disabled button or readiness badge is not an authorization or finalization guard.
7. Use only synthetic employees and amounts for automated/reference verification. Run tests when the implementation request authorizes testing/verification; do not mark acceptance complete without its evidence.
8. Mark a checkbox complete only when its behavior and acceptance criteria are actually satisfied. Record unresolved decisions without guessing amounts or exemptions.
9. Report changed files, verified behavior, remaining limits and next task. Commit/push only when requested.

**Do not expand scope implicitly:** fixed monthly salary, annual tax/13th-month calculation, full leave management, bank-account storage, payment transfers and agency filing are separate features. Their absence must remain visible, but they are not all required to reproduce the approved daily-pay process in this workbook.

## 10. Required reference and regression cases

All figures below are synthetic test inputs, **not minimum wages or official statutory amounts**.

### A. Daily basic and allowance without double deductions

Reviewed example inputs: daily basic PHP 500; planned days 22; worked days 20; eight-hour day; 60 undertime minutes not yet subtracted from worked days; daily allowance PHP 100 with the same reviewed undertime policy; no OT/holiday amount.

```text
Planned basic                  500 × 22           = 11,000.00
Unpaid absence                 500 × (22 − 20)    =  1,000.00
Undertime                      500 ÷ 8 ÷ 60 × 60 =     62.50
Basic earned                                      =  9,937.50
Allowance                      100 × 20 − 12.50   =  1,987.50
Gross including allowance                         = 11,925.00
Reviewed sample deductions                        =  1,100.00
Net                                               = 10,825.00
```

Run the same case with undertime already reflected in approved payable quantity: the engine must not subtract PHP 62.50 a second time. Test partial days, zero days and allowance policy differences separately.

### B. Overtime representation

At PHP 100/hour, nine approved paid hours and a reviewed 1.25 ordinary OT multiplier:

- Existing Shiftly representation: base `9 × 100 = 900`; additional premium `1 × 100 × 0.25 = 25`; total PHP 925.
- Alternative register representation: ordinary `8 × 100 = 800`; full OT `1 × 100 × 1.25 = 125`; total PHP 925.
- These are equivalent totals with different line presentation. Do not add full OT PHP 125 on top of base PHP 900.
- Preserve an overnight case such as 22:00–03:00 with a 30-minute unpaid break and reviewed night eligibility. Complex stacking stays blocked until its policy is implemented and reviewed.

### C. Monthly contribution allocation

Use a synthetic monthly EE target PHP 600 and ER target PHP 1,200. If the approved policy allocates half to each of two cutoffs, each cutoff gets EE PHP 300 and ER PHP 600. The second cutoff must account for the first finalized allocation; it must not charge another full PHP 600/1,200.

Also test an explicit manual override, another-cutoff treatment, changed monthly basis, a late correction, missing registration, and a negative reconciliation delta requiring a refund/correction path. ER amounts must not reduce employee net.

### D. Advance repayment

Opening authorized balance PHP 1,000; installment PHP 300. Preview and repeat recalculation leave balance at PHP 1,000. First finalization reduces it to PHP 700 once. Retrying finalization leaves PHP 700. A final installment must not exceed the remaining balance. A voided draft has no repayment posting.

### E. Cash counts and rounding

For PHP 1,234.56 and the workbook's denomination set, a valid result is 1×1000, 1×200, 1×20, 1×10, 4×1, 2×0.25, and 6×0.01. Counts must be nonnegative integers and sum exactly to PHP 1,234.56. Test zero, negative input, unavailable small coins, repeated report generation and group totals.

### F. Security, compatibility and data quality

- Another organization's employee/rate/component/obligation/statement is rejected through UI and direct service calls.
- Effective-date boundaries, assignment changes, and month-end/overnight splits choose the intended version.
- An employee-specific profile override wins over the company default, with source IDs recorded.
- Missing or ambiguous rules block processing; Regular/Probation category does not create an exemption.
- Changed source records invalidate previews/review; finalized historical statements do not change.
- `#REF!`, missing mappings and conflicting periods fail comparison/import clearly.
- Different nonzero allowances detect the payslip row-mapping issue described in section 4.
- Negative net remains blocked; no silently created loan or repayment waiver.
- Recalculation and concurrent finalization do not duplicate components, agency allocations or repayments.
- Existing hourly, statutory-manual-review, CSV security and employee-privacy tests continue to pass.

## 11. Rollout and compatibility

1. Deploy additive schema and services with new calculation modes disabled for existing employees by default.
2. Preserve legacy hourly behavior and all finalized snapshots. Do not backfill guessed daily rates, coverage, loan balances or legal decisions.
3. Configure reviewed synthetic cases, then explicitly configure a pilot group's effective compensation/components.
4. Compare approved reference results and two shadow cycles; explain each difference by basis, input, rounding, mapping or corrected workbook behavior.
5. Enable the daily/component/contribution features only for approved effective periods. Keep manual reviewed mode available where automation is not yet supported.
6. Record operating instructions for opening balances, correction/refund handling, month-end allocation, backups and payroll review.

Historical workbook data can be retained as a reviewed import/reconciliation record; it must not silently become a newly finalized Shiftly run or proof of payment.

## 12. Sources and limits

### Repository sources

- [`../payroll/models.py`](../payroll/models.py)
- [`../payroll/services.py`](../payroll/services.py)
- [`../payroll/statutory.py`](../payroll/statutory.py)
- [`../payroll/forms.py`](../payroll/forms.py)
- [`../payroll/views.py`](../payroll/views.py)
- [`../SHIFTLY_PROJECT_TASKS.md`](../SHIFTLY_PROJECT_TASKS.md), Phase 11
- [`PAYROLL_SCENARIOS.md`](PAYROLL_SCENARIOS.md), earlier synthetic verification; not validation of this workbook
- [`PAYROLL_REFERENCE_CASES.md`](PAYROLL_REFERENCE_CASES.md), synthetic cases for the implemented daily/component slice

### Official references for policy validation

Consulted on 2026-09-27. These are starting references for reviewing the applicable effective period and employee coverage, not a blanket certification of the workbook or future code.

- [SSS employer/employee contribution tables](https://www.sss.gov.ph/sss-contribution-table/) and [business employer Circular 2024-006](https://www.sss.gov.ph/wp-content/uploads/2024/12/CI-2024-006-Publication.pdf): use the appropriate employer/employee table and separate its contribution components.
- [PhilHealth Advisory 2025-0002](https://www.philhealth.gov.ph/advisories/2025/PA2025-0002.pdf): explains the contribution salary basis and exclusions. This is why a post-absence basic-pay helper cannot automatically be accepted as the contribution base.
- [Pag-IBIG Circular 460, reproduced in a DMW advisory](https://dmw.gov.ph/archives/v1/resources/dsms/DMW/ISN-EXT/2025/DMW-ADVISORY-37-2025.pdf): reference for membership-savings rules and effective-date review.
- [BIR RR 11-2018](https://bir-cdn.bir.gov.ph/local/pdf/RR%20No.%2011-2018.pdf): compensation withholding procedures and dated tables; check subsequent issuances before implementing a tax engine.
- [DOLE Workers' Statutory Monetary Benefits Handbook, 2024 edition](https://nwpc.dole.gov.ph/wp-content/uploads/2024/11/Workers-Statutory-Monetary-Benefits-Handbook-2024-Edition.pdf): reference for pay bases, premiums and coverage; verify current wage orders and applicable updates separately.

### What this analysis does not establish

- It does not establish the legal correctness of the workbook's wages, allowances, contribution deductions, charges or loan authorizations.
- It does not prove that a saved workbook amount was paid or remitted.
- It does not certify a complete Philippine payroll product. Scope remains explicit: existing hourly foundation, proposed daily/component extensions, separately reviewed statutory automation, and no money movement.
- The application now contains the first daily-pay/component slice described in the status section. Statutory, loan, cash, and import tasks remain open and are not enabled by this slice.
