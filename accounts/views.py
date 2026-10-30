import logging

from authlib.integrations.base_client.errors import OAuthError
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView
from django.utils.translation import gettext as _

from . import google
from .export import export_user_data
from .timeline import TIMELINE, TIMELINE_PREVIEW

logger = logging.getLogger(__name__)
NEXT_SESSION_KEY = "login_next"


class SettingsView(LoginRequiredMixin, TemplateView):
    """Theme and sign-out; the only way to reach them on phones, where the sidebar is hidden."""

    template_name = "accounts/settings.html"


class ExportView(LoginRequiredMixin, View):
    """Downloads everything stored about the signed-in user as a JSON file."""

    def get(self, request):
        response = JsonResponse(export_user_data(request.user), json_dumps_params={"ensure_ascii": False, "indent": 2})
        response["Content-Disposition"] = 'attachment; filename="idealar-export.json"'
        response["Cache-Control"] = "no-store"
        return response


class DeleteAccountView(LoginRequiredMixin, View):
    """Deletes the account and, through cascading deletes, every idea, project, chat, board, ticket and model of the user."""

    http_method_names = ["post"]

    def post(self, request):
        user = request.user
        if user.is_superuser:
            messages.error(request, _("Yönetici hesabı buradan silinemez."))
            return redirect("accounts:settings")
        logout(request)
        user.delete()
        messages.success(request, _("Hesabın ve tüm verilerin silindi."))
        return redirect("accounts:login")


class PrivacyView(TemplateView):
    template_name = "accounts/privacy.html"


class LoginView(View):
    """The only way in is Google; the Django admin keeps its own password login for the site owner."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("ideas:list")
        return render(request, "accounts/login.html", {"google_ready": google.is_configured(), "next": request.GET.get("next", ""), "timeline": TIMELINE, "timeline_preview": TIMELINE[:TIMELINE_PREVIEW], "timeline_more": max(len(TIMELINE) - TIMELINE_PREVIEW, 0)})


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
