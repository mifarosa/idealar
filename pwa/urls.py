from django.urls import path

from . import views

app_name = "pwa"

urlpatterns = [
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.ServiceWorkerView.as_view(), name="service-worker"),
    path("offline/", views.OfflineView.as_view(), name="offline"),
]
