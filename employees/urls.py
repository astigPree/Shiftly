from django.urls import path

from . import views


app_name = "employees"

urlpatterns = [
    path("", views.employee_list, name="list"),
    path("new/", views.employee_create, name="create"),
    path("<int:pk>/", views.employee_detail, name="detail"),
    path("<int:pk>/edit/", views.employee_edit, name="edit"),
    path("<int:pk>/status/", views.employee_toggle_status, name="toggle_status"),
    path("<int:pk>/invitation/", views.employee_resend_invitation, name="resend_invitation"),
]
