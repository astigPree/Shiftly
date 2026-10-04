# Shiftly UI state audit and professional design recommendations

Date: October 4, 2026  
Design reference: `SHIFTLY_PROJECT_DESIGN_SKILL.md`  
Test workspace: Shiftly Payroll Scenario Workspace, 200 synthetic employees

## Purpose

This review checks how each employer payroll surface behaves across meaningful UI states: empty and populated collections, filtered results, incomplete and complete setup, valid and invalid forms, open and closed dialogs, workflow statuses, and desktop and mobile layouts. It separates live browser observations from states inferred from server templates and validation paths.

## Verification method

- Live browser review at 1265 × 720 and 390 × 844.
- Seeded employer account with 200 synthetic employees and 25,900 approved timesheets.
- DOM measurements for page height, horizontal overflow, table density, dialog size, and body scroll locking.
- Static review for states that the current seed does not contain, such as a finalized run and a populated component catalog.
- Django system check after the implementation changes: no issues reported.

## Executive findings

1. The design system is visually consistent, but several workspaces are too long to scan. The draft payroll run measured 15,402 px on desktop and 19,473 px on mobile.
2. Large data sets are presented with functional pagination, but some pages still render too many independent workflows together. Statutory review, exception resolution, manual lines, statements, and audit history should be separate views or drawers.
3. Empty states are generally clear. Filtered empty states need different copy from first-use empty states so employers know whether to clear a filter or create data.
4. Dialogs now lock background scrolling and contain their own scrolling. The longest dialogs still need sticky headers and action footers inside the dialog.
5. Status copy must describe what the user can do next. “Ready,” “Needs review,” and “Complete” should always include the specific remaining requirement when action is needed.
6. High volume employee controls should use search and paginated pickers. A native select containing 200 employees is not acceptable for routine employer use.

## Page and state matrix

### `/payroll/` — payroll overview and run list

| State | Current behavior | Recommendation |
| --- | --- | --- |
| Setup incomplete | Live: 2 of 3 setup areas complete; 50 monthly employees are identified as unsupported | Keep the progress card, but add one primary “Resolve next issue” action that opens the filtered employee list for the exact blocker |
| Setup complete | Create run becomes available | Replace the full readiness card with a compact success banner after completion so the run table starts higher |
| Runs populated | Live: three runs in an eight-column table | Keep pagination; make reference/date the primary cell and move less-used metadata into a details drawer on narrow screens |
| No runs | First-run empty state | Include a short three-step explanation and one Create payroll run button |
| Filters return no results | Should not reuse the first-run message | Show “No runs match these filters,” preserve entered values, and provide Clear filters |
| Mobile | No body overflow observed | Convert each run row into a compact card below 700 px instead of relying on horizontal table scrolling |

### `/payroll/setup/` — settings and rule profiles

| State | Current behavior | Recommendation |
| --- | --- | --- |
| One default profile | Live: correctly shows 200 employees using the default, including inherited assignments | Keep the explicit inherited count; add “Default for unassigned employees” helper copy |
| Multiple profiles | Profile selector grows horizontally | Use a searchable left rail or select control when more than five profiles exist |
| No rule version | Large form appears immediately | Add an onboarding card explaining effective dates and source evidence before the first version |
| Existing reviewed version | History table plus new-version form creates a long page | Collapse history to the latest three versions with a dedicated View history page |
| Create profile dialog, blank | Live: 648 px high in a 720 px viewport | Keep internal scroll; add sticky dialog title and action footer so Create profile remains visible |
| Create profile dialog, invalid | Errors currently appear inside the form | Add an error summary at the top with links/focus to each invalid field; retain all entered values |
| Critical save | Confirmation exists for rule version changes | Confirmation copy should name the effective date and affected employee count |

### `/payroll/holidays/` — holiday calendar

| State | Current behavior | Recommendation |
| --- | --- | --- |
| Populated | Live: one reviewed holiday in a seven-column table | Good density; place source and reviewer in a details drawer rather than adding more columns |
| Empty year | Empty state should explain that payroll can still be drafted but holiday work may not calculate safely | Add Import official calendar as a future secondary action |
| Filtered empty | Must distinguish from no configured holidays | Show the active year/query and a Clear filters action |
| Add dialog, blank | Live: 626 px high | Group classification and multipliers under “Pay treatment”; keep source evidence in a separate section |
| Add dialog, invalid | Preserve values and auto-open | Add field-level examples for multipliers and official source links |

### `/payroll/employees/` — employee pay profile list

| State | Current behavior | Recommendation |
| --- | --- | --- |
| 200 employees | Live: 30 rows, seven columns, 4,647 px page height | Add a compact density option and keep the header/tools sticky within the table region |
| Ready employees | Green status is easy to scan | Add an accessible text summary in the filter header, such as “150 ready” |
| Monthly unsupported | Currently separated as its own filter | Rename to “Monthly calculation blocked” so the operational impact is explicit |
| No matching employees | Existing empty state | Include active filters and one Clear filters action |
| Bulk selection empty | Assign dialog can open before rows are selected | Disable Assign rule profile until at least one employee is selected, and show selection count beside the button |
| Bulk dialog populated | Selected employees are represented by hidden inputs | Show the first five names plus “and N more,” with a Review selection action |
| Mobile | Table remains high density | Use employee cards with compensation, status, and one Manage pay action; keep bulk mode as an explicit toggle |

### `/payroll/employees/<id>/` — employee payroll profile

| State | Current behavior | Recommendation |
| --- | --- | --- |
| Payroll ready | Live employee 1: 2,864 px desktop and 4,836 px mobile | Make Overview a true summary and render only the selected section; the current anchor navigation still loads every section |
| Needs setup | Requirements appear near the name | Use a structured checklist with owner, consequence, and direct action for every missing item |
| Monthly compensation | Must not appear payroll ready | Keep the explicit blocker: monthly amount is recordkeeping metadata until a reviewed conversion method exists |
| Excluded/inactive | Status needs to dominate the header | Hide assignment actions that cannot affect a run and explain how to re-enable payroll participation |
| Empty compensation/components/inputs | Empty cards are clear but duplicate top actions | Keep one action per empty card; never render the same action in both the heading and empty state |
| Populated history | Tables are useful but increase page length | Move compensation, components, inputs, and audit history to section routes or tab panels rendered on demand |
| Invalid/non-owned employee | Live `/payroll/employees/201/` produced Django’s debug 404 because the ID is absent in this organization | Add branded `404.html` and `403.html` pages with a Return to employee pay profiles action; production must never expose URL patterns |
| Assignment dialog | Body locking is fixed | Add sticky actions and show the currently resolved profile before the new choice |

### `/payroll/components/` — shared pay components

| State | Current behavior | Recommendation |
| --- | --- | --- |
| Empty | Live: clear explanation and Create first component | Add three lightweight examples: allowance, deduction, employer contribution |
| Populated | Table supports filters and actions | Keep summary cards compact; open create/edit in a dialog and details/history in a dedicated drawer |
| Filtered empty | Should say “No matching components” | Keep Clear filters as the primary recovery action |
| Create dialog, blank | Live: 648 px high | Group Code/Label, Calculation, and Behavior into labeled sections; sticky actions inside dialog |
| Create dialog, invalid | Dialog reopens with values | Put validation summary below the dialog heading and focus the first invalid field |

### `/payroll/runs/new/` — create payroll run

| State | Current behavior | Recommendation |
| --- | --- | --- |
| All active | Live: 200 eligible employees and scope-specific readiness | Add counts for ready, warning, and excluded employees directly in the scope card |
| Selected employees, none | Create draft is disabled | Keep the disabled state and display the reason adjacent to the action, not only in a title attribute |
| Selected employees, populated | Searchable checkbox list | Virtualize or paginate after 100 employees; add Ready/Needs attention filter chips |
| Regular run | Date presets use the configured frequency | Keep live period validation and show the exact required end date |
| Off-cycle without finalized parent | Now disabled with explanatory copy | Good. When enabled, selecting a parent should auto-fill and lock its original period |
| Invalid dates | Server and browser both validate | Put the date error in a single summary above the period fields and avoid duplicate messages |
| Mobile | Sticky action overlap is fixed by making actions part of normal flow | Keep full-width Cancel and Create draft buttons with Create draft first in keyboard order but last visually |

### `/payroll/runs/<id>/` — payroll run workspace

| State | Current behavior | Recommendation |
| --- | --- | --- |
| Draft with exceptions | Live run 3: 200 scoped, 150 statements, 50 exceptions | Split into Overview, Exceptions, Statements, Statutory review, and Audit routes; do not render all sections in one document |
| Draft without exceptions | Submission guidance is clear | Replace the exception card with a compact success row |
| In review | Finalize and Return to draft actions | Make Finalize the only primary action; require evidence in its confirmation dialog |
| Finalized | Read-only with export | Add a permanent “Locked” banner and remove draft-only help copy |
| Void | Now receives a dedicated historical-state banner and no active statutory/exception workflow | Keep statements and audit visible; hide action-oriented queues |
| Statutory queue large | Now server paginated 10 at a time with employee search | Move the full queue to the Statutory review route; overview should show only count and next employee |
| Statement table | 25 rows and eight columns | On mobile show employee, status, net pay, and View details; move other values into the details dialog |
| Statement dialog empty | Placeholder currently possible | Disable View details until template content exists and announce loading/error states |
| Statement dialog filled | Long line and timesheet lists | Group Earnings, Deductions, Employer contributions, and Source time into collapsible sections with subtotals |
| Manual line dialog | Live: 434 px high and well-contained | After save, announce the employee, line label, amount, and updated net pay; keep the statement dialog link in the success toast |
| Mobile | 19,473 px tall; internal table scrolling works, but the run tabs and one inline link caused horizontal pressure | Use real section routes, make tabs horizontally scrollable with edge fade, and keep inline actions content-sized |

### `/attendance/` and attendance edit states

| State | Current behavior | Recommendation |
| --- | --- | --- |
| No shifts | Live: clear “No shifts scheduled” empty state | Good; keep Schedule a shift as the sole primary action |
| Shift without punch | New Record attendance action opens a dedicated page | Show “Employer entry” in the resulting attendance row and timesheet audit history |
| Working/open clock-out | Employer cannot use the completed correction form | Add a dedicated Close attendance action requiring time and reason rather than overloading Edit attendance |
| Completed session | Edit attendance opens the correction page | Good separation; retain original punch and show correction history |
| Record attendance, blank | Scheduled values are prefilled and clearly labeled as reference | Add a visible source/evidence field when paper timecard support is implemented |
| Record attendance, invalid | Field and non-field errors remain on the page | Focus the first invalid field and announce the error summary |
| Confirmation | Separate confirmation explains timesheet and audit effects | Keep; confirmation must show employee and entered time range |

### `/timesheets/` — high volume review

| State | Current behavior | Recommendation |
| --- | --- | --- |
| 25,900 records | Live: 30 rows per page but a native 200-employee select and hundreds of pages | Replace employee select with autocomplete; use first/previous/next/last plus direct page input instead of every page number |
| Pending review | Summary card links to filter | Add bulk review only after a safe selection workflow with explicit totals |
| Empty/filter no result | Needs distinct messages | Explain whether there are no completed shifts or simply no matches |
| Mobile | Seven-column table is expensive to scan | Use timesheet cards with employee, work date, duration, status, and Review action |

## Cross-page recommendations

### 1. Use route-level workspaces for large tasks

Tabs should load one operational section at a time. Anchor links do not reduce DOM size, page height, or cognitive load. Apply this first to payroll run detail and employee payroll profile.

### 2. Standardize state components

Create reusable components for:

- First-use empty state: explanation plus one creation action.
- Filtered empty state: active filters plus Clear filters.
- Success state: compact confirmation and next action.
- Blocking state: exact requirement, consequence, and direct resolution action.
- Read-only terminal state: Finalized or Void banner with audit/export actions only.

### 3. Standardize dialog anatomy

Every dialog should have:

1. Sticky title and close button.
2. Scrollable form body.
3. Sticky Cancel and primary action footer.
4. Top validation summary and field errors.
5. Retained field values after validation.
6. Focus restoration to the button that opened it.

### 4. Make high volume selection searchable

Use server-backed autocomplete for employee, component, run, and timesheet filters. Checkbox lists can remain for a focused result set but should not render hundreds of options at once.

### 5. Reduce mobile data density

Below 700 px, replace wide operational tables with summary cards. Keep no more than three primary facts and one action visible; open the rest in a drawer or dedicated detail page.

### 6. Add branded error pages

Create 403, 404, and 500 pages using the employer shell where safe. Never expose Django route patterns. Include a single recovery action appropriate to the area the user attempted to open.

## Recommended implementation order

### P0 — workflow correctness and trust

1. Finish route-level separation for payroll run sections.
2. Add branded 403/404/500 pages.
3. Mark employer-entered attendance distinctly in attendance, timesheet, and audit UI.
4. Add missing employee statutory coverage and payment workflows before presenting statutory setup as complete.

### P1 — scale and mobile

1. Replace high volume employee selects with autocomplete.
2. Convert employee and statement tables to mobile cards.
3. Add sticky internal dialog headers and footers.
4. Render employee payroll profile tabs on demand.

### P2 — polish

1. Add examples and educational copy to first-use empty states.
2. Standardize success toasts with changed values and next actions.
3. Add density controls and saved filters to high volume tables.
4. Add skeleton and error states for any future asynchronous drawers.

## Retest checklist

- [ ] Payroll overview: no runs, populated runs, no filter matches, setup incomplete, setup complete.
- [ ] Settings: no profile, default profile, multiple profiles, blank modal, invalid modal, reviewed version history.
- [ ] Holidays: empty year, populated year, no filter matches, blank modal, invalid modal.
- [ ] Employees: ready, missing setup, monthly blocked, excluded, no search matches, bulk selection empty/populated.
- [ ] Employee profile: every readiness status, empty and populated history cards, assignment modal blank/invalid.
- [ ] Components: empty, populated, filtered empty, create/edit modal blank/invalid.
- [ ] Run creation: all active, selected none/some/all, regular, off-cycle unavailable/available, invalid dates, mobile.
- [ ] Run detail: Draft blocked/ready, Review, Finalized, Void, empty/populated statements, empty/large statutory queue, dialogs.
- [ ] Attendance: no shifts, no punch, working, open clock-out, completed, corrected, employer-entered, locked after payroll.
- [ ] Timesheets: empty, populated, pending, approved, rejected, filtered empty, high volume, mobile.

