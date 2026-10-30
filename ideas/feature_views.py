from django.contrib import messages
from django.utils.translation import gettext as _, ngettext
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import FormView

from .forms import CopyFeatureForm, FeatureForm
from .mixins import idea_panel_url
from .models import Feature, Idea


class OwnedFeatureMixin(LoginRequiredMixin):
    def get_feature(self, pk: int) -> Feature:
        return get_object_or_404(Feature.objects.filter(idea__owner=self.request.user), pk=pk)


class FeatureAddView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, idea_pk):
        idea = get_object_or_404(Idea.objects.owned_by(request.user), pk=idea_pk)
        form = FeatureForm(request.POST)
        if form.is_valid():
            form.instance.idea = idea
            form.save()
        else:
            messages.error(request, _("Özellik metni boş olamaz."))
        return redirect(idea_panel_url(idea.pk))


class FeatureToggleView(OwnedFeatureMixin, View):
    """Sets the done state explicitly (idempotent) and reports the idea's new progress as JSON."""

    http_method_names = ["post"]

    def post(self, request, pk):
        feature = self.get_feature(pk)
        feature.is_done = request.POST.get("done") == "true"
        feature.save(update_fields=["is_done"])
        progress = feature.idea.progress
        return JsonResponse({"done": feature.is_done, "done_count": progress.done, "total": progress.total})


class FeatureEditView(OwnedFeatureMixin, View):
    """Renames a feature in place; answers with JSON so the page can update without reloading."""

    http_method_names = ["post"]

    def post(self, request, pk):
        feature = self.get_feature(pk)
        form = FeatureForm({"text": request.POST.get("text", ""), "platform": feature.platform}, instance=feature)
        if not form.is_valid():
            return JsonResponse({"error": _("Özellik metni boş olamaz.")}, status=400)
        form.save()
        return JsonResponse({"text": feature.text})


class FeatureDeleteView(OwnedFeatureMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        feature = self.get_feature(pk)
        idea_pk = feature.idea_id
        feature.delete()
        return redirect(idea_panel_url(idea_pk))


class FeatureCopyView(OwnedFeatureMixin, FormView):
    """Copies a feature into other ideas; each copy is independent and starts unchecked."""

    template_name = "ideas/feature_copy.html"
    form_class = CopyFeatureForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.feature = self.get_feature(kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(user=self.request.user, source_idea=self.feature.idea)
        return kwargs

    def get_context_data(self, **kwargs):
        return super().get_context_data(feature=self.feature, **kwargs)

    def form_valid(self, form):
        targets = form.cleaned_data["ideas"]
        for idea in targets:
            self.feature.copy_to(idea)
        messages.success(self.request, ngettext("{n} fikre kopyalandı.", "{n} fikre kopyalandı.", len(targets)).format(n=len(targets)))
        return redirect(idea_panel_url(self.feature.idea_id))
