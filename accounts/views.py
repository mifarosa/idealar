import logging
from django.utils.translation import gettext as _

from authlib.integrations.base_client.errors import OAuthError
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from . import google
from .timeline import TIMELINE

logger = logging.getLogger(__name__)
NEXT_SESSION_KEY = "login_next"


class SettingsView(LoginRequiredMixin, TemplateView):
    """Theme and sign-out; the only way to reach them on phones, where the sidebar is hidden."""

    template_name = "accounts/settings.html"


class LoginView(View):
    """The only way in is Google; the Django admin keeps its own password login for the site owner."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("ideas:list")
        return render(request, "accounts/login.html", {"google_ready": google.is_configured(), "next": request.GET.get("next", ""), "timeline": TIMELINE})


class GoogleStartView(View):
    def get(self, request):
        if not google.is_configured():
            messages.error(request, _("Google girişi bu sunucuda ayarlanmamış."))
            return redirect("accounts:login")
        next_url = request.GET.get("next", "")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            request.session[NEXT_SESSION_KEY] = next_url
        return google.oauth_client().authorize_redirect(request, request.build_absolute_uri(reverse("accounts:google-callback")))


class GoogleCallbackView(View):
    def get(self, request):
        try:
            token = google.oauth_client().authorize_access_token(request)
            user = google.user_for(token["userinfo"])
        except google.SignInRefused as refusal:
            messages.error(request, str(refusal))
            return redirect("accounts:login")
        except (OAuthError, KeyError) as error:
            logger.warning("Google sign-in failed: %s", error)
            messages.error(request, _("Google ile giriş tamamlanamadı. Tekrar dene."))
            return redirect("accounts:login")
        next_url = request.session.pop(NEXT_SESSION_KEY, "")
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect("ideas:list")
