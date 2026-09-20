from django.urls import path

from . import views


app_name = "timesheets"

urlpatterns = [
    path("", views.timesheet_list, name="list"),
    path("my/", views.my_timesheets, name="my_list"),
    path("my/<int:pk>/", views.my_timesheet_detail, name="my_detail"),
    path("<int:pk>/", views.timesheet_detail, name="detail"),
    path("<int:pk>/approve/", views.approve_timesheet, name="approve"),
    path("<int:pk>/reject/", views.reject_timesheet, name="reject"),
]
