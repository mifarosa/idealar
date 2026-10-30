from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),  # set_language
    path("accounts/", include("accounts.urls")),
    path("", include("pwa.urls")),
    path("", include("support.urls")),
    path("", include("kanban.urls")),
    path("", include("ideas.urls")),
]
