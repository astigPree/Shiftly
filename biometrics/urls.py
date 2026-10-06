from django.urls import path

from . import views

app_name = "biometrics"

urlpatterns = [
    path("", views.device_list, name="devices"),
    path("issues/", views.issue_list, name="issues"),
    path("issues/<int:issue_pk>/resolve/", views.resolve_issue, name="resolve_issue"),
    path("<int:device_pk>/test/", views.test_device, name="test_device"),
    path("<int:device_pk>/edit/", views.edit_device, name="edit_device"),
    path("<int:device_pk>/sync-users/", views.sync_users, name="sync_users"),
    path("<int:device_pk>/sync-punches/", views.sync_punches, name="sync_punches"),
    path("<int:device_pk>/identities/", views.identity_list, name="identities"),
    path("<int:device_pk>/punches/", views.punch_list, name="punches"),
    path("projections/<int:projection_pk>/", views.projection_detail, name="projection_detail"),
    path("projections/<int:projection_pk>/reprocess/", views.reprocess_projection, name="reprocess_projection"),
    path("projections/<int:projection_pk>/apply/", views.apply_projection, name="apply_projection"),
]
