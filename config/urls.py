from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("", include("accounts.urls")),
    path("employees/", include("employees.urls")),
    path("schedules/", include("schedules.urls")),
    path("admin/", admin.site.urls),
]
