# Shiftly — Project Description

## Project Name

**Shiftly**

## Product Category

Employee Attendance, Scheduling, and Timesheet Management SaaS

## Tagline

**Simple attendance. Accurate timesheets. Better workforce visibility.**

## One-Line Description

Shiftly is a lightweight workforce attendance and timesheet management system that helps businesses manage employee schedules, clock-ins, breaks, clock-outs, timesheet approvals, and payroll-ready work records.

---

# 1. Product Overview

Shiftly is a web-based employee attendance and timesheet management platform designed for small businesses, remote teams, agencies, outsourcing companies, and distributed workforces.

The system provides employers with a centralized interface for managing employees, assigning schedules, monitoring daily attendance, reviewing work hours, handling exceptions, and approving timesheets.

Employees receive a simple interface where they can:

- View their assigned shift
- Clock in
- Start a break
- End a break
- Clock out
- View weekly work hours
- Review previous timesheets

Shiftly converts raw attendance events into structured timesheets that can later be used for payroll, workforce reporting, client billing, and operational analytics.

---

# 2. Problem Being Solved

Many small and growing companies still track employee attendance using:

- Spreadsheets
- Chat messages
- Manual logs
- Shared forms
- Generic time trackers
- Overly complicated HR systems

These methods create problems such as:

- Missing attendance records
- Incorrect work-hour calculations
- Difficult payroll preparation
- Weak visibility into employee attendance
- Manual checking of late employees
- Missing clock-outs
- Inconsistent timesheets
- Difficult approval workflows
- Lack of audit history

Shiftly solves this by creating one clear workflow:

```text
Schedule
→ Attendance
→ Timesheet
→ Approval
→ Payroll-ready record
```

---

# 3. Primary Users

## Employer / Administrator

The employer needs to:

- Add and manage employees
- Create employee schedules
- Monitor current attendance
- See who is working, late, absent, or on break
- Review attendance exceptions
- Review employee timesheets
- Approve or reject timesheets
- Export attendance records
- Review employee work history

## Employee

The employee needs to:

- View today's schedule
- Clock in
- Start and end breaks
- Clock out
- See current work status
- See current time worked
- Review weekly work hours
- Review timesheet history

---

# 4. MVP Scope

The MVP focuses only on the core attendance workflow.

## Employer Features

- Authentication
- Employer dashboard
- Employee management
- Shift/schedule management
- Daily attendance monitoring
- Attendance status
- Timesheet listing
- Timesheet details
- Approve timesheet
- Reject timesheet
- Attendance reports
- CSV export
- Basic audit records

## Employee Features

- Authentication
- Employee dashboard
- Today's shift
- Clock in
- Start break
- End break
- Clock out
- Live elapsed work timer
- Weekly work-hour summary
- Timesheet history

---

# 5. MVP Workflow

```text
Employer creates employee
        ↓
Employer assigns schedule
        ↓
Employee views today's shift
        ↓
Employee clocks in
        ↓
Employee works
        ↓
Employee starts/ends break
        ↓
Employee clocks out
        ↓
Shiftly calculates worked hours
        ↓
Timesheet is created
        ↓
Employer reviews timesheet
        ↓
Approve / Reject
        ↓
Payroll-ready attendance record
```

---

# 6. Core Business Rules

The server is the source of truth for all attendance data.

See SHIFTLY_MVP_ACCEPTANCE_CRITERIA.md for the resolved MVP rules and acceptance scenarios. It governs account provisioning, organization timezone, shifts, attendance states, breaks, calculations, timesheet review, reports, exports, and audit behavior.

Shiftly must store attendance events such as:

- Clock-in timestamp
- Break start timestamp
- Break end timestamp
- Clock-out timestamp

Shiftly should derive:

- Total elapsed time
- Break duration
- Total worked duration
- Late minutes
- Undertime
- Payable minutes
- Attendance status

The browser may display timers, but all payroll-relevant calculations must be performed and validated by Django.

---

# 7. Core Attendance Statuses

Employee attendance states:

- Scheduled
- Not Clocked In
- Working
- On Break
- Late
- Absent
- Completed

Timesheet states:

- Pending
- Approved
- Rejected
- Needs Review

MVP exception handling:

- Missing Clock Out is shown as a warning on an open session after scheduled end. The employee may still clock out; no final timesheet exists before clock-out, and the employer cannot edit attendance in MVP.

Future exception states:

- Overbreak
- Undertime exception alerts/workflows
- Overtime
- Missing Attendance

---

# 8. Main Employer Pages

```text
/dashboard/

/employees/
/employees/create/
/employees/<id>/
/employees/<id>/edit/

/schedules/
/schedules/create/
/schedules/<id>/edit/

/attendance/
/attendance/<id>/

/timesheets/
/timesheets/<id>/

/reports/

/settings/
```

---

# 9. Main Employee Pages

```text
/me/
/me/schedule/
/me/timesheets/
/me/timesheets/<id>/
/me/profile/
```

---

# 10. Product Positioning

Shiftly should not be positioned as a complete HRIS in the MVP.

The initial positioning is:

> A lightweight attendance and timesheet management platform for growing teams.

The product should compete on:

- Simplicity
- Speed
- Clear attendance visibility
- Reliable timesheet calculation
- Easy approval workflows
- Low operational complexity

---

# 11. Target Market

Initial target customers:

- VA agencies
- Remote teams
- Small BPO companies
- Software agencies
- Marketing agencies
- Service businesses
- Contractors
- Small offices
- Outsourcing companies
- Distributed teams

Ideal early company size:

```text
5–200 employees
```

---

# 12. Future Product Roadmap

## Phase 1 — MVP

- Employees
- Schedules
- Clock in/out
- Breaks
- Timesheets
- Approval
- Reports
- CSV export

## Phase 2 — Smart Attendance

- Grace periods
- Late detection
- Undertime detection
- Missing clock-out detection
- Timesheet corrections
- Automatic approval rules
- Notifications

## Phase 3 — Workforce Management

- Leave management
- Holiday calendar
- Shift templates
- Recurring schedules
- Departments
- Teams
- Supervisors
- Multiple locations

## Phase 4 — Payroll

- Hourly rates
- Salary configuration
- Overtime rates
- Night differential
- Holiday rates
- Payroll periods
- Payroll calculations
- Payslip generation

## Phase 5 — Agency Operations

```text
Employee
→ Attendance
→ Timesheet
→ Employee Cost
→ Client Billable Hours
→ Client Invoice
→ Profit Margin
```

---

# 13. Monetization Direction

Potential pricing:

| Plan | Employees | Example Price |
|---|---:|---:|
| Free | Up to 5 | ₱0 |
| Starter | Up to 20 | ₱499–₱999/month |
| Business | Up to 50 | ₱1,499–₱2,499/month |
| Agency | Up to 150 | ₱4,999+/month |
| Enterprise | Custom | Custom |

Alternative future pricing:

```text
₱40–₱80 per active employee / month
```

---

# 14. Product Principles

Shiftly should remain:

- Easy to understand
- Easy to deploy
- Easy to maintain
- Operationally reliable
- Auditable
- Fast
- Modular
- Scalable without premature complexity

The MVP should avoid becoming a full HR system before the core attendance and timesheet workflow is proven.

---

# 15. Final Product Definition

**Shiftly is a lightweight workforce attendance and timesheet management SaaS that converts employee schedules and attendance events into accurate, reviewable, payroll-ready work records.**

Long-term direction:

**Shiftly becomes a workforce operations platform connecting scheduling, attendance, timesheets, payroll, client billing, and workforce analytics.**
