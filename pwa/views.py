import json

from django.http import JsonResponse
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

APP_NAME = "Idealar"
THEME_COLOR = "#4f46e5"
BACKGROUND_COLOR = "#0f172a"


def _icon(size: int, purpose: str = "any") -> dict:
    return {"src": static(f"icons/icon-{size}.png"), "sizes": f"{size}x{size}", "type": "image/png", "purpose": purpose}


def build_manifest() -> dict:
    return {
        "name": APP_NAME,
        "short_name": APP_NAME,
        "description": "Uygulama fikirlerini hızlıca yakala.",
        "lang": "tr",
        "start_url": reverse("ideas:list"),
        "scope": "/",
        "display": "standalone",
        "theme_color": THEME_COLOR,
        "background_color": BACKGROUND_COLOR,
        "icons": [_icon(192), _icon(512), _icon(512, "maskable")],
    }


@never_cache
def manifest(request):
    return JsonResponse(build_manifest(), content_type="application/manifest+json")


class ServiceWorkerView(TemplateView):
    """Served from the site root so its scope covers the whole app."""

    template_name = "pwa/sw.js"
    content_type = "text/javascript"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        precache_urls = [
            reverse("pwa:offline"),
            static("css/app.css"),
            static("js/app.js"),
            static("icons/icon-192.png"),
        ]
        context["precache_json"] = json.dumps(precache_urls)
        context["offline_url"] = reverse("pwa:offline")
        return context

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        # Browsers must always re-check the worker script, otherwise updates never ship.
        response["Cache-Control"] = "no-cache"
        return response


class OfflineView(TemplateView):
    template_name = "pwa/offline.html"
