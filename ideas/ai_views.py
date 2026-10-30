from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.utils.translation import gettext as _, ngettext

from . import advice, ai_enrichment, ai_registry, build_prompt, prompt_brief, similarity
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
        if ai_enrichment.enrich_idea(idea, ai_enrichment.build_analyzer(idea.owner)):
            messages.success(request, _("AI başlık, özet, etiket ve özellik önerilerini hazırladı."))
        else:
            messages.error(request, _("AI şu an yanıt veremedi. Fikir kaydedildi; sonra tekrar deneyebilirsin."))
        similarity.check_idea(idea)  # separate AI call; its failure never undoes the enrichment above
        if ai_registry.has_models(request.user):
            advice.advise_idea(idea)  # reads the whole notebook; likewise independent of the steps above
        return redirect(idea_panel_url(idea.pk))


class AdviceView(OwnedIdeaActionView):
    """Manual "advise me from all my notes" button."""

    def post(self, request, pk):
        idea = self.get_idea(pk)
        if advice.advise_idea(idea):
            count = len([entry for entry in idea.advice if entry["status"] == SUGGESTION_PENDING])
            messages.success(request, ngettext("Tüm notların okundu: {n} öneri hazır.", "Tüm notların okundu: {n} öneri hazır.", count).format(n=count) if count else _("Tüm notların okundu; şimdilik önerecek bir şey bulamadım."))
        else:
            messages.error(request, _("AI şu an yanıt veremedi. Biraz sonra tekrar dene."))
        return redirect(idea_panel_url(idea.pk))


class AdviceDecideView(OwnedIdeaActionView):
    def post(self, request, pk, index):
        idea = self.get_idea(pk)
        if index < len(idea.advice):
            apply = request.POST.get("decision") == "apply"
            try:
                advice.decide_advice(idea, index, apply)
                messages.success(request, _("Uygulandı.") if apply else _("Tamam, öneri gizlendi."))
            except ActionNotApplicable:
                messages.error(request, _("Bu kayıt artık yok (silinmiş olabilir)."))
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
            messages.warning(request, _("AI şu an yanıt veremedi; yalnızca kelime benzerliğine baktım."))
        elif found:
            messages.success(request, ngettext("Benzerlik kontrolü tamamlandı: {n} benzer kayıt bulundu.", "Benzerlik kontrolü tamamlandı: {n} benzer kayıt bulundu.", found).format(n=found))
        else:
            messages.success(request, _("Benzerlik kontrolü tamamlandı: benzer kayıt bulunmadı."))


class SimilarDecideView(OwnedIdeaActionView):
    def post(self, request, pk, index):
        idea = self.get_idea(pk)
        if index < len(idea.similar):
            apply = request.POST.get("decision") == "apply"
            try:
                similarity.decide_similar(idea, index, apply)
                messages.success(request, _("Eklendi.") if apply else _("Tamam, farklı olarak işaretlendi."))
            except ActionNotApplicable:
                messages.error(request, _("Bu kayıt artık yok (silinmiş olabilir)."))
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


class IdeaPromptView(LoginRequiredMixin, View):
    """A ready-to-paste prompt that starts building the idea; the AI can optionally add a build plan to it."""

    template_name = "ideas/idea_prompt.html"

    def get(self, request, pk):
        idea = self._idea(pk)
        return self._render(request, idea, self._mode(request.GET.get("mod"), idea), brief=None)

    def post(self, request, pk):
        idea = self._idea(pk)
        mode = self._mode(request.POST.get("mod"), idea)
        brief = prompt_brief.draft_brief(idea, mode)
        if brief is None:
            messages.error(request, _("AI şu an yanıt veremedi; sade prompt gösteriliyor, biraz sonra tekrar deneyebilirsin."))
        return self._render(request, idea, mode, brief)

    def _idea(self, pk: int) -> Idea:
        owned = Idea.objects.owned_by(self.request.user).prefetch_related("features", "projects")
        return get_object_or_404(owned, pk=pk)

    @staticmethod
    def _mode(requested: str | None, idea: Idea) -> str:
        valid = (build_prompt.MODE_NEW, build_prompt.MODE_EXTEND)
        return requested if requested in valid else build_prompt.default_mode(idea)

    def _render(self, request, idea: Idea, mode: str, brief):
        context = {
            "idea": idea,
            "mode": mode,
            "brief_used": brief is not None,
            "prompt_text": build_prompt.build_prompt(idea, mode, brief),
            "mode_new": build_prompt.MODE_NEW,
            "mode_extend": build_prompt.MODE_EXTEND,
        }
        return render(request, self.template_name, context)
