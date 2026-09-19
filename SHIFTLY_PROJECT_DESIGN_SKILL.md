# Shiftly — Project Design Skill

## Purpose

This file defines the visual system, UX rules, component patterns, and design decisions for Shiftly.

The official UI direction is:

> **Modern Minimal SaaS + Operational Dashboard**

The design must feel:

- Professional
- Calm
- Reliable
- Lightweight
- Modern
- Clear
- Trustworthy
- Fast

Shiftly is operational software. Usability is more important than decorative styling.

---

# 1. Design Philosophy

The design should combine:

- Modern Minimal SaaS
- Operational Dashboard UI
- Clear status-driven interfaces
- Compact employer dashboards
- Simple employee clocking screens

The interface should use:

- White surfaces
- Very light gray backgrounds
- Blue primary accents
- Thin borders
- Subtle shadows
- Medium rounded corners
- Strong typography
- Compact spacing
- Clear status badges
- High information clarity

Avoid:

- Heavy gradients
- Glassmorphism
- Neumorphism
- Excessive animations
- Oversized cards
- Decorative dashboards
- Too many charts
- Very large border radii

---

# 2. Core Design Rule

Every screen must answer a specific user question.

Employer:

- Who is working?
- Who is late?
- Who is absent?
- Who is on break?
- Which timesheets need review?
- What requires action?

Employee:

- What is my shift?
- Am I clocked in?
- How long have I worked?
- What action should I take now?

Do not add UI elements that do not help answer those questions.

---

# 3. Visual Identity

## Primary Color

```css
--primary-50: #eff6ff;
--primary-100: #dbeafe;
--primary-200: #bfdbfe;
--primary-500: #3b82f6;
--primary-600: #2563eb;
--primary-700: #1d4ed8;
--primary-900: #1e3a8a;
```

Primary color usage:

- Active navigation
- Primary buttons
- Links
- Focus states
- Selected elements
- Important interactive elements

---

# 4. Neutral Colors

```css
--gray-50: #f8fafc;
--gray-100: #f1f5f9;
--gray-200: #e2e8f0;
--gray-300: #cbd5e1;
--gray-400: #94a3b8;
--gray-500: #64748b;
--gray-600: #475569;
--gray-700: #334155;
--gray-800: #1e293b;
--gray-900: #0f172a;
```

Recommended:

```css
--page-background: #f8fafc;
--surface: #ffffff;
--border: #e2e8f0;
--text-primary: #0f172a;
--text-secondary: #64748b;
```

---

# 5. Status Colors

## Working / Approved

```css
background: #dcfce7;
text: #15803d;
dot: #22c55e;
```

## Break / Informational

```css
background: #dbeafe;
text: #1d4ed8;
dot: #3b82f6;
```

## Late / Pending

```css
background: #fef3c7;
text: #b45309;
dot: #f59e0b;
```

## Absent / Rejected / Error

```css
background: #fee2e2;
text: #b91c1c;
dot: #ef4444;
```

## Neutral / Completed

```css
background: #f1f5f9;
text: #475569;
dot: #94a3b8;
```

Never communicate an important state using color alone.

Always include text.

---

# 6. Typography

Recommended:

**Inter**

Fallback:

```css
font-family:
    Inter,
    ui-sans-serif,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
```

Optional for timers:

**JetBrains Mono**

Use monospace only for:

- Running timers
- Time counters
- Technical identifiers

Suggested scale:

```css
--text-xs: 12px;
--text-sm: 14px;
--text-base: 16px;
--text-lg: 18px;
--text-xl: 20px;
--text-2xl: 24px;
--text-3xl: 30px;
```

---

# 7. Spacing System

Use a 4px-based scale:

```text
4px
8px
12px
16px
20px
24px
32px
40px
48px
```

Recommended:

- Desktop page padding: 24–32px
- Card padding: 20–24px
- Table row padding: 12–16px
- Sidebar item height: 42–46px
- Input height: 40–44px
- Primary button height: 42–48px

---

# 8. Border Radius

```css
--radius-sm: 6px;
--radius-md: 8px;
--radius-lg: 12px;
```

Use:

- Buttons: 8px
- Inputs: 8px
- Cards: 10–12px
- Badges: pill radius when needed

Avoid excessive 20–32px radius.

---

# 9. Shadows

Cards should rely primarily on borders.

Recommended:

```css
box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 1px 3px rgba(15, 23, 42, 0.06);
```

Avoid heavy floating shadows.

---

# 10. App Shell

Employer layout:

```text
┌────────────────────────────────────────────┐
│ Sidebar │ Topbar                           │
│         ├──────────────────────────────────┤
│         │ Main Content                     │
│         │                                  │
└─────────┴──────────────────────────────────┘
```

Recommended dimensions:

- Sidebar: 240–260px
- Collapsed sidebar: 72–80px
- Topbar: 64–72px

---

# 11. Employer Navigation

MVP navigation:

```text
Overview
Employees
Schedules
Attendance
Timesheets
Reports
Settings
```

Future grouped navigation:

```text
Overview

WORKFORCE
Employees
Schedules
Attendance
Timesheets

OPERATIONS
Approvals
Reports

ADMIN
Organization
Settings
```

Active item:

- Pale blue background
- Blue icon
- Stronger text
- No heavy visual effects

---

# 12. Employer Dashboard

Recommended structure:

```text
Greeting + Date

[ Employees ] [ Working ] [ Late ] [ Absent ]

Today's Attendance

Employee | Shift | Status | Last Activity | Actions
```

Optional later:

- Attendance Exceptions
- Pending Timesheets
- Weekly attendance trend

Keep MVP dashboard focused.

---

# 13. KPI Cards

Use 3–5 cards maximum.

Structure:

```text
[ icon ]

24
Employees

Total team members
```

Cards should not contain decorative charts unless they communicate useful information.

---

# 14. Attendance Table

Recommended columns:

```text
Employee
Shift
Status
Clock In
Clock Out
Worked
Last Activity
Actions
```

MVP:

```text
Employee
Shift
Status
Last Activity
Actions
```

Employee cell:

```text
[Avatar] Ericson Guanzon
         Customer Support
```

Actions should use an overflow menu.

---

# 15. Employee Dashboard

Employee UI must be simpler than employer UI.

Recommended:

```text
Good evening, Ericson

TODAY'S SHIFT
9:00 PM – 6:00 AM

CURRENT STATUS
Working

02:41:32

[ START BREAK ]

Clock Out

THIS WEEK
32h 14m / 40h

RECENT TIMESHEETS
```

The current attendance action must be the strongest visual element.

---

# 16. Attendance Clock

Reusable visual component:

```text
AttendanceClock
```

States:

## Not Started

```text
Today's Shift
9:00 AM – 6:00 PM

[ CLOCK IN ]
```

## Working

```text
Working

02:41:32

[ START BREAK ]
Clock Out
```

## On Break

```text
On Break

00:18:22

[ END BREAK ]
```

## Completed

```text
Shift Completed

Worked
8h 03m
```

Use tabular numerals for timers.

---

# 17. Attendance Timeline

Use a reusable timeline:

```text
09:01       12:03       13:01       18:02
  ●──────────●------------●──────────●
Clock In   Break Start   Resume     Clock Out
```

Use on:

- Attendance detail
- Timesheet detail
- Employer review

This should become one of Shiftly's signature components.

---

# 18. Timesheet Design

Recommended table:

```text
Employee
Date
Scheduled
Clock In
Clock Out
Break
Worked
Payable
Status
Actions
```

MVP:

```text
Employee
Date
Worked
Status
Actions
```

Status badges:

- Pending
- Approved
- Rejected
- Needs Review

---

# 19. Timesheet Review

Use a modal, side panel, or dedicated detail page.

Show:

```text
Employee
Date
Scheduled Shift
Clock In
Break
Clock Out
Worked Hours
Late Minutes
Undertime
Notes
```

Actions:

```text
[ Reject ] [ Approve ]
```

Approval must show enough information for the employer to make a correct decision.

---

# 20. Forms

Form structure:

```text
Label
Input
Helper text / Error
```

Rules:

- Do not use placeholders instead of labels
- Keep forms compact
- Use clear validation messages
- Keep primary action obvious

Example:

```text
Cancel     Save Employee
```

---

# 21. Search and Filters

Employer pages may use:

```text
[ Search employees... ] [ Status ▼ ] [ Date ▼ ] [ Export ]
```

Use compact controls.

Do not place filters inside oversized containers.

---

# 22. Charts

Charts are secondary.

Recommended only for:

- Weekly attendance trend
- Work-hour trend
- Late rate trend

Avoid:

- Decorative donut charts
- Radar charts
- Multiple graphs on every screen

Tables and status cards are more important for MVP.

---

# 23. Empty States

Bad:

```text
No data.
```

Good:

```text
No employees yet

Add your first employee to begin scheduling and tracking attendance.

[ Add Employee ]
```

---

# 24. Loading States

Use:

- Skeleton rows
- Skeleton cards
- Button loading states

Avoid full-screen spinners unless necessary.

---

# 25. Error States

Attendance actions are critical.

Example:

```text
Clock-in failed

Your attendance was not recorded.
Check your connection and try again.

[ Try Again ]
```

Never show attendance success before Django confirms it.

---

# 26. Confirmation Rules

Require confirmation for:

- Delete employee
- Delete schedule
- Reject timesheet
- Override attendance
- Reset attendance

Do not require unnecessary confirmation for normal clock actions.

---

# 27. Audit UI

Admin changes should show history.

Example:

```text
Original Clock In
9:12 AM

Changed To
9:00 AM

Changed By
Miguel Tan

Reason
Forgot to clock in

Changed At
Sep 19, 2026 10:42 AM
```

Corrections should always be auditable.

---

# 28. Responsive Design

## Desktop

Primary employer experience.

Target:

- 1366×768
- 1440×900
- 1920×1080

## Tablet

- Collapsed sidebar
- Horizontal table scrolling when needed
- Hide secondary columns

## Mobile

Employee experience must work well.

Recommended employee navigation:

```text
Home
Schedule
Timesheets
Profile
```

Minimum tap target:

```text
44×44px
```

---

# 29. Accessibility

Requirements:

- Good contrast
- Visible keyboard focus
- Semantic HTML
- Proper labels
- Correct heading order
- Status text in addition to color
- Buttons must be `<button>`
- Links must be `<a>`
- Tables must use semantic table markup

---

# 30. Icons

Recommended:

**Lucide**

Alternatives:

- Heroicons
- Phosphor

Use one icon family only.

Typical sizes:

```text
16px
18px
20px
```

---

# 31. Core UI Components

```text
Button
IconButton
Input
Select
Badge
Card
StatCard
Table
Dropdown
Modal
Drawer
Tabs
Toast
Tooltip
Pagination
EmptyState
Avatar
Skeleton
```

Shiftly-specific components:

```text
EmployeeStatusBadge
TimesheetStatusBadge
ShiftCard
AttendanceClock
AttendanceTimeline
WeeklyHoursCard
AttendanceException
TimesheetRow
ApprovalPanel
HoursSummary
```

---

# 32. CSS Architecture

Use vanilla CSS organized by purpose.

Recommended:

```text
static/css/

base/
    reset.css
    variables.css
    typography.css

layout/
    app-shell.css
    sidebar.css
    topbar.css
    grid.css

components/
    buttons.css
    cards.css
    badges.css
    forms.css
    tables.css
    modal.css
    dropdown.css
    pagination.css

pages/
    dashboard.css
    attendance.css
    schedules.css
    timesheets.css
    employees.css

utilities.css
main.css
```

---

# 33. Design Tokens

Use CSS custom properties.

Example:

```css
:root {
    --color-primary: #2563eb;
    --color-primary-hover: #1d4ed8;

    --color-bg: #f8fafc;
    --color-surface: #ffffff;

    --color-text: #0f172a;
    --color-text-muted: #64748b;

    --color-border: #e2e8f0;

    --color-success: #16a34a;
    --color-warning: #d97706;
    --color-danger: #dc2626;

    --radius-sm: 6px;
    --radius-md: 8px;
    --radius-lg: 12px;

    --sidebar-width: 250px;
    --topbar-height: 68px;
}
```

---

# 34. Design Anti-Patterns

Do not use:

- Heavy glassmorphism
- Neumorphism
- Strong gradients everywhere
- Huge hero illustrations in the app
- Very large cards
- Excessive graphs
- Multiple competing accent colors
- Excessive animation
- Giant pill-shaped controls
- 24px+ radius everywhere
- Dense mobile tables
- Deep navigation hierarchies

---

# 35. Final Design Rule

When deciding between:

```text
More visual
```

and:

```text
More understandable
```

choose:

```text
More understandable
```

Shiftly's UI exists to make this workflow clear:

```text
Schedule
→ Attendance
→ Timesheet
→ Approval
→ Payroll-ready record
```
