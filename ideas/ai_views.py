from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views import View

from . import ai_enrichment, similarity
from .errors import ActionNotApplicable
from .mixins import idea_panel_url
from .models import SUGGESTION_PENDING, Feature, Idea


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
        similarity.check_idea(idea)  # separate AI call; its failure never undoes the enrichment above
        return redirect(idea_panel_url(idea.pk))


class SimilarCheckView(OwnedIdeaActionView):
    """Manual "look for duplicates" button."""

    def post(self, request, pk):
        idea = self.get_idea(pk)
        similarity.check_idea(idea)
        self._report(request, idea)
        return redirect(idea_panel_url(idea.pk))

    @staticmethod
    def _report(request, idea):
        found = len([hint for hint in idea.similar if hint["status"] == SUGGESTION_PENDING])
        if idea.similarity_status == similarity.SIMILARITY_WORDS_ONLY:
            messages.warning(request, "AI şu an yanıt veremedi; yalnızca kelime benzerliğine baktım.")
        elif found:
            messages.success(request, f"Benzerlik kontrolü tamamlandı: {found} benzer kayıt bulundu.")
        else:
            messages.success(request, "Benzerlik kontrolü tamamlandı: benzer kayıt bulunmadı.")


class SimilarDecideView(OwnedIdeaActionView):
    def post(self, request, pk, index):
        idea = self.get_idea(pk)
        if index < len(idea.similar):
            apply = request.POST.get("decision") == "apply"
            try:
                similarity.decide_similar(idea, index, apply)
                messages.success(request, "Eklendi." if apply else "Tamam, farklı olarak işaretlendi.")
            except ActionNotApplicable:
                messages.error(request, "Bu kayıt artık yok (silinmiş olabilir).")
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
