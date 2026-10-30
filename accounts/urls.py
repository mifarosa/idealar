from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("google/", views.GoogleStartView.as_view(), name="google-start"),
    path("google/callback/", views.GoogleCallbackView.as_view(), name="google-callback"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    # Django 5 only accepts POST for logout, which also prevents logout via prefetch/CSRF links.
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
