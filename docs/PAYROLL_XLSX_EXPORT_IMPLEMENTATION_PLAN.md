# Finalized payroll Excel workbook implementation plan

**Prepared:** 2026-10-05  
**Status:** Implemented
**Scope:** Expand the finalized payroll Excel workbook so it supports every current employment status. The workbook will contain exactly eight sheets: `Regular`, `Probation`, `Part-time`, `Other`, `Payslip Regular`, `Payslip Probation`, `Payslip Part-time`, and `Payslip Other`.

## 1. Outcome

From a finalized payroll run, an employer can download one `.xlsx` workbook that contains:

1. A payroll register for regular employees.
2. A payroll register for probationary employees.
3. A payroll register for part-time employees.
4. A payroll register for employees classified as Other.
5. Print-ready payslips for regular employees.
6. Print-ready payslips for probationary employees.
7. Print-ready payslips for part-time employees.
8. Print-ready payslips for employees classified as Other.

The workbook is an immutable view of finalized payroll data. It does not recalculate attendance, statutory contributions, loans, tax, or pay rates in Excel. Every displayed amount comes from the finalized statement and line-item snapshots already approved in Shiftly.

The supplied `202604 (1).xls` is a legacy BIFF workbook and is useful as a layout and workflow reference. It also contains inconsistent period labels and known broken formulas, so its formula logic must not be copied into the new export. The new product output will be `.xlsx`.

## 2. Product rules

### 2.1 Finalized-only export

- Show the Excel export only for a `FINALIZED` payroll run.
- Keep the existing server-side status guard. A copied URL must not export a draft, review, or void run.
- Scope every lookup to the current organization and retain the existing employer permission check.
- Downloading a workbook must not change payroll values, create payment instructions, or transfer money.

### 2.2 Classification is historical data

The export must group employees using the classification that applied when the run was calculated, not the employee's current profile.

- Save `employment_status` and its display label inside each `PayrollStatement.snapshot` during both hourly and daily calculation paths.
- Export `REGULAR` statements into `Regular` and `Payslip Regular`.
- Export `PROBATION` statements into `Probation` and `Payslip Probation`.
- Export `PART_TIME` statements into `Part-time` and `Payslip Part-time`.
- Export `OTHER` statements into `Other` and `Payslip Other`.
- Only a missing or unknown historical classification blocks the workbook export. The alert must name the affected employee count and codes. CSV remains available for legacy runs that do not contain a historical classification.
- Do not use the current `EmployeePayProfile.employment_status` as a historical fallback for finalized legacy runs. It could create an inaccurate payroll record after an employee changes status.

| Saved employment status | Register sheet | Payslip sheet |
|---|---|---|
| `REGULAR` | `Regular` | `Payslip Regular` |
| `PROBATION` | `Probation` | `Payslip Probation` |
| `PART_TIME` | `Part-time` | `Payslip Part-time` |
| `OTHER` | `Other` | `Payslip Other` |

`PART_TIME` remains an employment-status classification for export purposes. It does not change the employee's hourly, daily, or monthly pay basis.

This rule keeps workbook totals traceable to the payroll that was actually finalized.

### 2.3 Safe spreadsheet values

- Write user-controlled text as safe text values. Employee codes, names, component labels, and rule names beginning with `=`, `+`, `-`, `@`, tab, or carriage return must be neutralized before being written to a worksheet.
- Write PHP amounts and dates as typed values with Excel number formats, never as formatted strings or formulas.
- Do not export government identifiers, bank-account references, or other sensitive employee master data.
- Do not evaluate uploaded formulas, macros, or the legacy workbook during export.

## 3. Workbook structure

The eight-sheet order is fixed:

1. `Regular`
2. `Probation`
3. `Part-time`
4. `Other`
5. `Payslip Regular`
6. `Payslip Probation`
7. `Payslip Part-time`
8. `Payslip Other`

All eight sheets are created even when a group has no employees. An empty register uses a clear empty-state row; an empty payslip sheet explains that no finalized statements matched the group. No cash-count, agency lookup, raw source, or hidden helper sheet is included in this release.

### 3.1 Register sheets: `Regular`, `Probation`, `Part-time`, and `Other`

Each register should use one row per finalized employee statement, with a compact header that identifies the organization, run reference, period, pay date, currency, and employee count. Freeze the header row, filter the employee table, repeat table headers when printed, use landscape orientation, and keep all monetary columns in PHP with two decimals.

Recommended columns:

| Group | Columns |
|---|---|
| Identity | Employee code, employee name, pay basis, rule-profile summary |
| Earnings | Basic pay, overtime premium, night differential, holiday/rest-day premium, recurring allowances, other earnings, gross pay |
| Employee deductions | SSS, PhilHealth, Pag-IBIG, withholding tax, other deductions, total deductions |
| Employer cost | SSS employer, PhilHealth employer, Pag-IBIG employer, other employer contributions, total employer contributions |
| Payment | Net pay |

Use a visually distinct total row at the bottom. Totals are calculated by the server and written as final numeric values. They must reconcile to the included statement rows and should not depend on a workbook formula.

### 3.2 Payslip sheets: `Payslip Regular`, `Payslip Probation`, `Payslip Part-time`, and `Payslip Other`

Each employee receives one print-ready payslip block and page, generated from their own finalized statement ID. A payslip must never use another employee's register row as its data source.

Each page includes:

- organization name and payroll run reference;
- employee name and employee code;
- employment classification and pay basis;
- payroll period and pay date;
- earnings line items;
- employee deduction line items;
- employer contributions as an informational section when present;
- gross pay, total employee deductions, and net pay;
- a short footer stating that the document reflects the finalized Shiftly payroll record.

Use a restrained, print-friendly layout: white background, dark text, thin gray dividers, blue section headers, clear totals, generous spacing, and no decorative graphics. Set a print area for each payslip and insert a manual page break after each employee block.

## 4. Data mapping

Create one shared export-data builder. CSV and Excel must consume the same normalized statement data so their categories and totals cannot drift.

| Workbook field | Source of truth |
|---|---|
| Run metadata | `PayrollRun.reference`, period, pay date, frequency, currency, finalized timestamp |
| Employee identity | finalized `PayrollStatement.snapshot["employee"]` with the statement employee as a consistency check |
| Classification | `PayrollStatement.snapshot["employee"]["employment_status"]` |
| Rule profile summary | stored statement snapshot through the existing `_statement_rule_profile_summary()` behavior |
| Basic, overtime, night, holiday | `PayrollLine` codes `REGULAR_PAY`, `OVERTIME_PREMIUM`, `NIGHT_DIFFERENTIAL`, `DAY_PREMIUM` |
| Recurring allowances | calculated component earning lines |
| Other earnings | remaining earning lines after the named earnings categories |
| SSS, PhilHealth, Pag-IBIG, withholding | reviewed `PayrollStatutoryAssessment` links to employee contribution lines; use finalized legacy review snapshots only through a dedicated compatibility resolver |
| Other deductions | statement deduction total less the four statutory employee amounts |
| Employer contribution columns | reviewed statutory assessment employer lines, with the remaining employer total in `Other employer contributions` |
| Gross, deductions, employer contributions, net | `PayrollStatement` totals |

The builder must validate, for every statement:

```text
named earnings + other earnings = gross pay
statutory employee deductions + other deductions = total deductions
statutory employer contributions + other employer contributions = total employer contributions
gross pay - total deductions = net pay
```

If a statement cannot reconcile, abort the export with a clear run-level error and log the exact statement IDs for troubleshooting. Do not hide mismatches by adjusting workbook totals.

## 5. Backend design

### 5.1 New export module

Add `payroll/exports.py` with narrow, testable responsibilities:

- `build_finalized_export_data(run)` returns normalized, reconciled rows plus group totals;
- `csv_export_rows(data)` supplies the existing CSV view from the shared normalized data;
- `build_finalized_workbook(data)` returns an in-memory `.xlsx` document;
- small helpers handle safe text, number formats, line classification, statutory amounts, and print-page construction.

Use `select_related` and `prefetch_related` for statements, lines, statutory assessments, and linked statutory lines. The export must use a bounded query set and must not query once per employee.

### 5.2 Dependency and endpoint

- Add `openpyxl` to the shared application dependencies. It supports `.xlsx` generation, sheet styling, print settings, and page breaks without requiring Microsoft Excel on the server.
- Add `payroll:run_export_xlsx` at `runs/<int:pk>/export.xlsx` beside the existing CSV route.
- Return the official XLSX MIME type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- Use a deterministic filename such as `pay-20260901-20260930-payroll.xlsx`.
- Reuse `PAYROLL_EXPORT_ACCESSED` for audit history with metadata such as `format: "xlsx"`, `export_schema: "v2"`, statement count, and counts for regular, probation, part-time, and other groups. Do not store the generated workbook binary in the database.

### 5.3 Snapshot compatibility

Adding the employment-status key to `PayrollStatement.snapshot` does not require a database migration because `snapshot` is already JSON. It does require tests for both calculation paths.

For finalized runs created before this feature:

- detect a missing snapshot classification;
- show an actionable message that Excel export requires historical classification captured at calculation time;
- keep CSV available;
- do not retroactively alter a finalized statement or guess from the employee's current profile.

Finalized runs that already contain a historical `PART_TIME` or `OTHER` classification are exportable after this revision. They do not need a backfill because the new workbook has a matching group for each status.

If the business needs historic exports for those runs, add a separate reviewer-authorized backfill workflow later. That workflow must record evidence and create an audit event rather than silently editing finalized snapshots.

## 6. Run-detail user experience

On a finalized run, replace duplicate `Export CSV` links with one compact **Export** control in the page header. Its menu contains:

- **Excel workbook (.xlsx)**
- **CSV register (.csv)**

The control belongs beside the finalized run actions and should not be repeated inside the employee-statements table. It follows the existing Shiftly design system: secondary button styling, 42px target height, concise labels, keyboard navigation, focus state, and a clear disabled reason only when the run has a missing or unknown historical classification.

Before the download begins, the browser follows the normal file-download behavior. No confirmation modal is needed because the action is read-only. If export is blocked, present an inline alert near the control that names the problem, for example:

> Excel export needs historical classification for 3 finalized statements. Use CSV for this legacy run or complete a reviewed historical backfill.

## 7. Delivery sequence

### Phase 1 — Export foundation

1. Add the shared normalized export-data builder.
2. Move the current CSV categorization into that builder without changing CSV columns or behavior.
3. Add statement snapshot classification for hourly and daily calculations.
4. Add reconciliation and legacy-classification validation.

### Phase 2 — Workbook generation

1. Add `openpyxl` and the XLSX response endpoint.
2. Build the four register sheets with typed values, styles, filters, frozen headers, totals, and print settings.
3. Build the four payslip sheets with one statement per printed page.
4. Add safe-text handling and the workbook audit event metadata.

### Phase 3 — UI and verification

1. Replace the duplicated CSV controls with the one Export menu.
2. Show clear export readiness and missing-classification messages.
3. Add regression coverage and render sample workbooks for visual review in Excel or a compatible viewer.
4. Update the payroll guide with the exact download behavior and the historical-data limitation.

## 8. Tests and acceptance criteria

Automated tests should cover:

- employer authorization and organization isolation;
- draft, review, void, and finalized status behavior;
- exact workbook sheet names and order;
- regular, probation, part-time, and other separation based on statement snapshots;
- a run with no employees in one or more groups still produces all eight sheets;
- part-time and other statements export into their matching sheets without changing the finalized run;
- only a legacy missing or unknown classification blocks Excel export without changing the finalized run;
- PHP values are numeric cells, dates are typed dates, and user text cannot become an Excel formula;
- register row totals reconcile to each statement and register totals reconcile to the included statements;
- each payslip includes only its own statement lines and totals;
- grouped statutory columns reconcile to statutory review records and statement totals;
- export audit metadata has `format: "xlsx"` and correct counts;
- existing CSV output remains unchanged after refactoring.

Manual visual acceptance:

- open the workbook in Microsoft Excel and verify no clipped headers, `####` dates, duplicate table headers, or blank payslip pages;
- print or preview a register and several payslips at normal page scale;
- use distinct non-zero earnings and deductions for two employees to prove no payslip or group data is cross-wired;
- verify a payroll with no employees in a group still has understandable empty register and payslip sheets for that group.

## 9. Out of scope for this release

- importing the legacy `.xls` workbook;
- cash count, ATM, bank transfer, or payment release files;
- automatic tax, SSS, PhilHealth, Pag-IBIG, loan, or cash-advance calculations;
- macro-enabled workbooks;
- modifying a finalized run to repair historical classification;
- user-configured employment-status groups or custom sheet names.

Those can be added as separate, reviewed features after the eight-sheet export is stable and reconciled.

## 10. Definition of done

The feature is complete when an authorized employer can download a finalized payroll workbook with exactly the eight requested sheets, every employment-status register total reconciles to finalized statements, every payslip reflects only its own statement, a legacy missing or unknown classification cannot silently disappear, the workbook is visually usable in Excel, and every download is audit logged.
