from django.contrib import admin
from django.urls import include, path
from .health import health


urlpatterns = [
    path("health/", health, name="health"),
    path("", include("accounts.urls")),
    path("employees/", include("employees.urls")),
    path("schedules/", include("schedules.urls")),
    path("attendance/", include("attendance.urls")),
    path("timesheets/", include("timesheets.urls")),
    path("payroll/", include("payroll.urls")),
    path("reports/", include("reports.urls")),
    path("admin/", admin.site.urls),
]
