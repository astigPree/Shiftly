from django.urls import path

from . import views


app_name = "schedules"

urlpatterns = [
    path("my/", views.my_schedule, name="my_schedule"),
    path("", views.shift_list, name="list"),
    path("new/", views.shift_create, name="create"),
    path("<int:pk>/", views.shift_detail, name="detail"),
    path("<int:pk>/edit/", views.shift_edit, name="edit"),
    path("<int:pk>/cancel/", views.shift_cancel, name="cancel"),
]
