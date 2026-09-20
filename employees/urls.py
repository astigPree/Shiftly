from django.urls import path

from . import views


app_name = "employees"

urlpatterns = [
    path("", views.employee_list, name="list"),
    path("new/", views.employee_create, name="create"),
    path("<int:pk>/schedules/", views.employee_schedules, name="schedules"),
    path("<int:pk>/attendance/", views.employee_attendance, name="attendance"),
    path("<int:pk>/timesheets/", views.employee_timesheets, name="timesheets"),
    path("<int:pk>/", views.employee_detail, name="detail"),
    path("<int:pk>/edit/", views.employee_edit, name="edit"),
    path("<int:pk>/status/", views.employee_toggle_status, name="toggle_status"),
    path("<int:pk>/invitation/", views.employee_resend_invitation, name="resend_invitation"),
]
