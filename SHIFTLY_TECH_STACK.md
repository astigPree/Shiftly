# Shiftly — Project Tech Stack

## Purpose

This file defines the official technical stack and implementation architecture for the Shiftly MVP.

The stack is intentionally simple.

Shiftly is a server-rendered Django website.

There is no Django REST Framework, SPA framework, or frontend JavaScript framework in the MVP.

---

# 1. Official MVP Stack

## Backend

```text
Python
Django
```

## Frontend

```text
HTML5
Django Templates
Vanilla CSS
Vanilla JavaScript
```

## Database

```text
PostgreSQL
```

## Production

```text
Ubuntu
Nginx
Gunicorn
systemd
```

## Version Control

```text
Git
GitHub
```

---

## Pinned Runtime Versions

Selected on 2026-09-19 and pinned in the repository:

- Python 3.14.7 in .python-version. Django officially supports the latest micro release in each supported Python series; 3.14.7 is the current Python 3.14 maintenance release.
- Django 5.2.17 in requirements/base.txt. Django 5.2 is the LTS series and supports Python 3.14 from 5.2.8; its extended security support runs through April 2028.
- Psycopg 3.3.6 with its binary extra in requirements/base.txt for PostgreSQL connections across Windows development and Ubuntu production.
- Gunicorn 26.2.0 in requirements/production.txt for the Ubuntu WSGI deployment. Keep this production-only dependency out of the Windows development install.

Install shared dependencies with pip install -r requirements/base.txt. Production environments install pip install -r requirements/production.txt. Update exact pins deliberately after checking upstream support and security releases.

Sources: [Django supported releases](https://www.djangoproject.com/download/), [Django Python compatibility](https://docs.djangoproject.com/en/5.2/faq/install/), [Python 3.14 releases](https://www.python.org/doc/versions/), [Psycopg installation](https://www.psycopg.org/psycopg3/docs/basic/install.html), and [Gunicorn 26.2.0](https://pypi.org/project/gunicorn/26.2.0/).

---
# 2. Explicitly Not Used in MVP

The MVP will not use:

```text
Django REST Framework
React
Vue
Angular
HTMX
Alpine.js
Tailwind CSS
Bootstrap
Redis
Celery
Django Channels
WebSockets
GraphQL
Kubernetes
Microservices
```

These may be introduced later only when they solve a proven product requirement.

---

# 3. Architecture Style

Use a modular Django monolith.

```text
Browser
   ↓
Nginx
   ↓
Gunicorn
   ↓
Django
   ↓
PostgreSQL
```

Application flow:

```text
HTML Form / Vanilla JS
        ↓
Django URL
        ↓
Django View
        ↓
Service Layer
        ↓
Model / Database
        ↓
Template Render / Redirect / JsonResponse
```

---

# 4. Project Structure

Recommended:

```text
shiftly/
│
├── manage.py
│
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
│
├── accounts/
│
├── organizations/
│
├── employees/
│
├── schedules/
│
├── attendance/
│
├── timesheets/
│
├── reports/
│
├── audit/
│
├── templates/
│   ├── base.html
│   ├── components/
│   ├── employer/
│   └── employee/
│
├── static/
│   ├── css/
│   ├── js/
│   ├── icons/
│   └── images/
│
└── requirements/
    ├── base.txt
    └── production.txt
```

---

# 5. Django Apps

## accounts

Responsibilities:

- Authentication
- User model
- Login/logout
- Role access

## organizations

Responsibilities:

- Company/organization data
- Tenant ownership
- Company settings
- Timezone

## employees

Responsibilities:

- Employee profiles
- Employee codes
- Employment status
- Employer/employee relationship

## schedules

Responsibilities:

- Shift creation
- Shift assignment
- Scheduled start/end
- Break allowance
- Schedule status

## attendance

Responsibilities:

- Clock in
- Clock out
- Break start
- Break end
- Attendance session
- Attendance events
- Attendance state

## timesheets

Responsibilities:

- Timesheet generation
- Work-hour calculation
- Late minutes
- Undertime
- Payable minutes
- Approvals
- Rejections

## reports

Responsibilities:

- Daily attendance reports
- Weekly work hours
- CSV export
- Basic reporting

## audit

Responsibilities:

- Attendance changes
- Timesheet changes
- Admin modifications
- Audit trail

---

# 6. Authentication

Use Django's authentication system.

Recommended:

```text
Custom User model
```

Define it at the beginning of the project.

Possible fields:

```text
email
first_name
last_name
role
is_active
is_staff
```

Roles:

```text
EMPLOYER
EMPLOYEE
```

Do not build separate login systems.

MVP account and tenancy rules are defined in SHIFTLY_MVP_ACCEPTANCE_CRITERIA.md: one employer owner per organization, one organization and one role per user, employer-created employee invitations, and organization timezone locked after the first shift. Use that document as the behavioral authority for attendance and timesheet calculations.

---

# 7. Authorization

Use server-side authorization.

Examples:

```python
@login_required
def dashboard(request):
    ...
```

Create reusable permission checks for:

- Employer-only pages
- Employee-only pages
- Organization ownership

Every object query must be scoped to the user's organization.

Never trust IDs coming from the browser without organization validation.

---

# 8. Database

Use PostgreSQL from the beginning.

Do not use SQLite for production.

Core entities:

```text
User
Organization
Employee
Shift
AttendanceSession
BreakSession
Timesheet
TimesheetApproval
AuditEvent
```

---

# 9. Suggested Data Model

## Organization

```text
id
owner_id
name
timezone
created_at
updated_at
```

## User

```text
id
email
password
first_name
last_name
role
is_active
created_at
updated_at
```

## Employee

```text
id
organization_id
user_id  # unique, required, EMPLOYEE role
employee_code
status
created_at
updated_at
```

## Shift

```text
id
organization_id
employee_id
local_work_date
scheduled_start  # timezone-aware instant
scheduled_end    # timezone-aware instant; may fall on the next local date
scheduled_break_minutes
status
created_at
updated_at
```

## AttendanceSession

```text
id
organization_id
employee_id
shift_id
clock_in
clock_out
status
created_at
updated_at
```

## BreakSession

```text
id
attendance_session_id
started_at
ended_at
created_at
updated_at
```

## Timesheet

```text
id
organization_id
employee_id
shift_id
scheduled_minutes
worked_minutes
break_minutes
payable_minutes
late_minutes
undertime_minutes
status
created_at
updated_at
```

## TimesheetApproval

```text
id
timesheet_id
reviewed_by_id
action
comment
reviewed_at
```

## AuditEvent

```text
id
organization_id
actor_id
action
target_type
target_id
metadata
created_at
```

---

# 10. Business Logic Architecture

Views should remain thin.

Bad:

```python
def clock_out(request):
    # hundreds of lines of attendance logic
```

Good:

```python
def clock_out(request):
    session = attendance_service.clock_out(
        employee=request.user.employee
    )

    return redirect("employee-dashboard")
```

Use services:

```text
attendance/
    services/
        attendance_service.py
        clock_service.py

timesheets/
    services/
        calculator.py
        approval_service.py
```

---

# 11. Forms

Use Django Forms and ModelForms.

Examples:

```text
EmployeeForm
ShiftForm
TimesheetReviewForm
OrganizationSettingsForm
```

Normal workflow:

```text
POST
→ form.is_valid()
→ service/save
→ redirect
```

Use Post/Redirect/Get to prevent duplicate form submissions.

---

# 12. Templates

Use Django Templates.

Recommended template hierarchy:

```text
templates/

base.html

components/
    button.html
    badge.html
    card.html
    stat_card.html
    modal.html
    pagination.html
    empty_state.html

employer/
    dashboard.html
    employees/
    schedules/
    attendance/
    timesheets/
    reports/

employee/
    dashboard.html
    schedule.html
    timesheets/
    profile.html
```

Use template inheritance.

Example:

```django
{% extends "base.html" %}
```

---

# 13. Vanilla CSS

Use organized vanilla CSS.

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

Use CSS custom properties for design tokens.

---

# 14. Vanilla JavaScript

Use ES modules.

Recommended:

```text
static/js/

core/
    csrf.js
    modal.js
    utils.js

attendance/
    clock.js
    timer.js
    break.js

timesheets/
    approval.js
    filters.js

schedules/
    schedule-form.js

employees/
    employee-form.js

dashboard/
    dashboard.js
```

Use:

```html
<script type="module" src="{% static 'js/attendance/clock.js' %}"></script>
```

Do not create one giant JavaScript file.

---

# 15. JavaScript Responsibilities

JavaScript may handle:

- Live timers
- Confirmation dialogs
- Dropdowns
- Modals
- Small UI state
- Fetch requests
- Dynamic filters
- Client-side convenience

JavaScript must not be the source of truth for:

- Worked hours
- Payable hours
- Attendance state
- Payroll calculations
- Late minutes
- Undertime
- Timesheet status

Django must validate and calculate those values.

---

# 16. AJAX Without DRF

Django REST Framework is not required for JavaScript requests.

Normal Django views may return JSON.

Example:

```python
from django.http import JsonResponse

def clock_in(request):
    session = attendance_service.clock_in(
        employee=request.user.employee
    )

    return JsonResponse({
        "success": True,
        "clock_in": session.clock_in.isoformat(),
    })
```

Frontend:

```javascript
const response = await fetch("/attendance/clock-in/", {
    method: "POST",
    headers: {
        "X-CSRFToken": getCsrfToken()
    }
});

const data = await response.json();
```

Use JSON responses only when they improve UX.

Normal HTML POST + redirect remains the default.

---

# 17. Clocking Architecture

The server stores timestamps.

Example:

```text
clock_in = 2026-09-19 21:03:42
clock_out = 2026-09-20 06:01:12
```

The browser may calculate display time:

```javascript
elapsed = Date.now() - clockInTime
```

But Django calculates final worked duration.

Never store the browser timer as authoritative attendance data.

---

# 18. Timezone Handling

Store datetimes timezone-aware.

Use Django:

```python
USE_TZ = True
```

Store organization timezone.

Display times using the organization's timezone.

Require an IANA timezone at organization creation. Lock it after the first shift is created in MVP. See SHIFTLY_MVP_ACCEPTANCE_CRITERIA.md for daylight-saving validation and local date rules.

Avoid naive datetimes.

Attendance systems become unreliable when timezone rules are inconsistent.

---

# 19. Attendance Transaction Safety

Clock actions should be atomic where necessary.

Use:

```python
transaction.atomic()
```

for critical operations.

Prevent:

- Duplicate active attendance sessions
- Duplicate clock-in
- Multiple open breaks
- Multiple clock-out
- Invalid state transitions

Example state transitions:

```text
NOT_STARTED
→ WORKING
→ ON_BREAK
→ WORKING
→ COMPLETED
```

---

# 20. Idempotency

Critical clock actions should tolerate:

- Double clicking
- Browser retries
- Network retry
- Refresh

A repeated clock-in must not create multiple active sessions.

Enforce correctness server-side.

---

# 21. Validation Rules

Examples:

- Employee may not clock in twice
- Employee may not clock out before clock in
- Employee may not start a second break while one is active
- Employee may not end a break that does not exist
- Employee may not modify another organization's records
- Approved timesheets require controlled modification

---

# 22. Security

Minimum requirements:

- CSRF protection
- Django authentication
- Secure password hashing
- Organization-scoped queries
- Permission checks
- Secure cookies
- HTTPS
- Environment variables for secrets
- Input validation
- File upload restrictions if added later
- Audit logging for sensitive changes

Production:

```python
DEBUG = False
```

Configure:

- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- secure session cookies
- secure CSRF cookies
- HSTS after HTTPS is stable

---

# 23. Database Constraints

Use database constraints where possible.

Examples:

- Unique employee code within an organization
- Valid timesheet status values
- Valid attendance state
- Indexed organization IDs
- Indexed employee IDs
- Indexed shift dates
- Indexed attendance timestamps

Use PostgreSQL indexes for frequently filtered fields.

---

# 24. Reporting

MVP reports:

- Daily attendance
- Weekly employee hours
- Attendance status summary
- Timesheet status

CSV export can use Django's standard `csv` module.

No pandas required for simple exports.

---

# 25. Real-Time Behavior

MVP does not need WebSockets.

Employer attendance screen may use:

```javascript
setInterval(refreshAttendance, 30000);
```

or manual refresh.

Introduce Django Channels only if real customers require near-instant updates.

---

# 26. Background Jobs

Do not add Celery in MVP.

Introduce Celery + Redis later for:

- Scheduled reminders
- Missing clock-out checks
- Automated email
- Large exports
- Payroll generation
- Notification workflows
- Scheduled reports

---

# 27. Deployment

Recommended production topology:

```text
Internet
    ↓
Cloudflare
    ↓
Nginx
    ↓
Gunicorn
    ↓
Django
    ↓
PostgreSQL
```

Server:

```text
Ubuntu LTS
```

Process management:

```text
systemd
```

Static files:

```text
Django collectstatic
→ Nginx
```

Media files:

MVP:

```text
Local media directory
```

Future:

```text
S3-compatible object storage
```

---

# 28. Environment Variables

Use environment variables for:

```text
SECRET_KEY
DEBUG
ALLOWED_HOSTS
DATABASE_URL
EMAIL settings
production domain
```

Do not commit secrets.

Use `.env` locally if desired.

Production secrets should be configured at the server/environment level.

---

# 29. Logging

Configure Django logging for:

- Application errors
- Attendance failures
- Authorization failures
- Background processing later

Do not log:

- Passwords
- Authentication tokens
- Sensitive secrets

Audit events belong in the database where appropriate.

---

# 30. Testing

Minimum automated tests:

## Models

- constraints
- relationships
- statuses

## Services

- clock in
- duplicate clock in
- break start
- duplicate break
- break end
- clock out
- worked duration
- late calculation
- undertime calculation
- timesheet creation

## Permissions

- Employer cannot access another organization
- Employee cannot access employer pages
- Employee cannot access another employee's timesheet

## Views

- login required
- valid form
- invalid form
- correct redirects
- JSON clock actions where used

Business logic services should receive the strongest test coverage.

---

# 31. Recommended Development Order

```text
1. Django project setup
2. Custom User model
3. Organization model
4. Employee model
5. Authentication
6. Employer dashboard shell
7. Employee management
8. Shift/schedule management
9. Attendance models
10. Clock-in/out service
11. Break service
12. Employee clock UI
13. Timesheet calculator
14. Timesheet employer UI
15. Approval workflow
16. Reports
17. CSV export
18. Audit events
19. Production deployment
```

---

# 32. Future API Strategy

Do not build DRF now.

If Shiftly later requires:

- Mobile app
- Public API
- External payroll integration
- Third-party integrations
- SPA frontend

then add DRF.

Because core logic lives in services, future APIs can reuse the same code.

Future:

```text
React / Mobile
    ↓
DRF
    ↓
Services
    ↓
Models
```

Current:

```text
Django Templates
    ↓
Views
    ↓
Services
    ↓
Models
```

This keeps the system future-compatible without premature API complexity.

---

# 33. Final Technical Rule

The architecture should remain:

```text
Simple
Modular
Server-authoritative
Auditable
Secure
Easy to deploy
Easy to maintain
```

For the MVP, every added dependency must justify itself with real business value.

The official Shiftly MVP stack is:

```text
Python
Django
PostgreSQL
Django Templates
HTML5
Vanilla CSS
Vanilla JavaScript
Nginx
Gunicorn
systemd
Ubuntu
Git / GitHub
```
