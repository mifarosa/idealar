from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class SettingsView(LoginRequiredMixin, TemplateView):
    """Theme and sign-out; the only way to reach them on phones, where the sidebar is hidden."""

    template_name = "accounts/settings.html"
