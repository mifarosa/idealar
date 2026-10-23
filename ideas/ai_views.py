from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views import View

from . import ai_enrichment
from .mixins import idea_panel_url
from .models import Feature, Idea


class OwnedIdeaActionView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def get_idea(self, pk: int) -> Idea:
        return get_object_or_404(Idea.objects.owned_by(self.request.user), pk=pk)


class IdeaEnrichView(OwnedIdeaActionView):
    """Runs the AI on one idea. Called automatically after quick capture and by the manual button."""

    def post(self, request, pk):
        idea = self.get_idea(pk)
        if ai_enrichment.enrich_idea(idea, ai_enrichment.build_analyzer()):
            messages.success(request, "AI başlık, özet, etiket ve özellik önerilerini hazırladı.")
        else:
            messages.error(request, "AI şu an yanıt veremedi. Fikir kaydedildi; sonra tekrar deneyebilirsin.")
        return redirect(idea_panel_url(idea.pk))


class SuggestionResolveView(OwnedIdeaActionView):
    """Accepts a suggested feature (adds it as a feature) or dismisses it; either removes the suggestion."""

    def post(self, request, pk):
        idea = self.get_idea(pk)
        text = request.POST.get("text", "")
        if text in idea.suggested_features:
            if request.POST.get("action") == "accept":
                Feature.objects.create(idea=idea, text=text)
            idea.suggested_features = [item for item in idea.suggested_features if item != text]
            idea.save(update_fields=["suggested_features", "updated_at"])
        return redirect(idea_panel_url(idea.pk))
