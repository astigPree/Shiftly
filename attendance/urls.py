from django.urls import path

from . import views


app_name = "attendance"

urlpatterns = [
    path("", views.attendance_list, name="list"),
    path("my/", views.my_attendance, name="my_attendance"),
    path("shifts/<int:shift_pk>/clock-in/", views.clock_in_action, name="clock_in"),
    path("sessions/<int:session_pk>/break/start/", views.start_break_action, name="start_break"),
    path("sessions/<int:session_pk>/break/end/", views.end_break_action, name="end_break"),
    path("sessions/<int:session_pk>/clock-out/", views.clock_out_action, name="clock_out"),
]
