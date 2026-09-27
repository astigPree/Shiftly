from django.urls import path

from . import views


app_name = "payroll"

urlpatterns = [
    path("", views.run_list, name="run_list"),
    path("setup/", views.setup, name="setup"),
    path("holidays/", views.holiday_calendar, name="holiday_calendar"),
    path("holidays/<int:pk>/edit/", views.holiday_edit, name="holiday_edit"),
    path("employees/", views.employee_payroll_list, name="employee_list"),
    path("employees/<int:pk>/", views.employee_profile, name="employee_profile"),
    path("employees/<int:pk>/rates/new/", views.add_pay_rate, name="add_pay_rate"),
    path("employees/<int:pk>/compensation/new/", views.add_compensation, name="add_compensation"),
    path("employees/<int:pk>/components/new/", views.add_component_assignment, name="add_component_assignment"),
    path("employees/<int:pk>/period-inputs/new/", views.add_period_input, name="add_period_input"),
    path("components/", views.component_definitions, name="component_definitions"),
    path("runs/new/", views.run_create, name="run_create"),
    path("runs/create/", views.run_create_submit, name="run_create_submit"),
    path("runs/<int:pk>/", views.run_detail, name="run_detail"),
    path("runs/<int:pk>/export.csv", views.run_export, name="run_export"),
    path("my/", views.my_statements, name="my_statements"),
    path("my/<int:pk>/", views.my_statement_detail, name="my_statement_detail"),
]
