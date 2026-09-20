from django.urls import path

from . import views


app_name = "reports"

urlpatterns = [
    path("", views.report_home, name="home"),
    path("timesheets.csv", views.timesheet_csv, name="timesheet_csv"),
]
