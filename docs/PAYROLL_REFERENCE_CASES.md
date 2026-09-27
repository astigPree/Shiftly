# Payroll synthetic reference cases

**Purpose:** deterministic, non-production cases for checking the workbook-compatible payroll slice. These figures are synthetic and are not Philippine minimum wages or statutory rates.

## Case A: daily pay, absence, undertime, and allowance

Period: 1–30 September 2026. Employee is daily paid at PHP 500/day. Planned units: 22. Worked units: 20. Regular day: 480 minutes. Undertime: 60 minutes. No overtime or holiday premium. Daily allowance: PHP 100, with the same undertime policy.

```text
planned basic        500 × 22                  = 11,000.00
absence explanation  500 × (22 − 20)           =  1,000.00
undertime            500 ÷ 480 × 60            =     62.50
basic earned                                    =  9,937.50
allowance            100 × 20 − (100 ÷ 480×60)  =  1,987.50
gross including allowance                       = 11,925.00
sample deductions                               =  1,100.00
net                                              = 10,825.00
```

The engine must not subtract the PHP 62.50 undertime twice when the approved worked quantity already includes the time deduction. Repeat with zero, fractional, and partial-day quantities.

## Case B: overtime and overnight work

At PHP 100/hour, nine approved paid hours and a 1.25 overtime multiplier, the current representation is PHP 900 base plus PHP 25 overtime premium, for PHP 925 total. Do not add a full PHP 125 overtime amount on top of the PHP 900 base.

Use a 10:00 PM–3:00 AM shift with a 30-minute unpaid break. Configure the employee work timezone and night eligibility. Verify local-date splitting, payable minutes, night minutes, and the effective rule/rate snapshot.

## Case C: dated components

Create one shared `cola` earning component at PHP 50 per worked day, assign it through 21 September, then assign PHP 75 from 22 September. Two worked dates must produce two generated lines with separate assignment IDs and no duplicates after recalculation.

## Case D: review and compatibility

Run one legacy hourly employee and one daily employee in the same period. The hourly employee must continue using approved attendance and the legacy rate fallback. The daily employee must be discovered from reviewed period inputs and must be blocked if an attendance record exists for the same local date.

## Deliberately open cases

SSS, PhilHealth, Pag-IBIG, withholding tax, loans, cash advances, cash denomination preparation, and workbook import/comparison are not automatic in this release. They require policy decisions and authoritative review before test amounts are added.
