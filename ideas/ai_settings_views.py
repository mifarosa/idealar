import os

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from ai.errors import AIError
from ai.providers import KINDS, build_client, specs_from_environment

from . import ai_registry
from .ai_settings_forms import AIModelForm
from .models import AIModel

LIST_URL_NAME = "ideas:ai-models"
MAX_LISTED_MODELS = 200


class StaffRequiredMixin(LoginRequiredMixin):
    """The model list is instance-wide, so only staff may change it."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_staff:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def key_is_set(model: AIModel) -> bool:
    info = KINDS.get(model.kind)
    return not info or not info.needs_key or bool(os.environ.get(model.key_env, "").strip())


class AIModelListView(StaffRequiredMixin, View):
    def get(self, request):
        models = list(AIModel.objects.all())
        for model in models:
            model.kind_label = KINDS[model.kind].label if model.kind in KINDS else model.kind
            model.key_missing = not key_is_set(model)
        return render(request, "ideas/ai_models.html", {"models": models, "env_chain": not models})


class AIModelFormView(StaffRequiredMixin, View):
    def get_instance(self, pk):
        return get_object_or_404(AIModel, pk=pk) if pk else None

    def render_form(self, request, form, instance):
        return render(request, "ideas/ai_model_form.html", {"form": form, "object": instance})

    def get(self, request, pk=None):
        instance = self.get_instance(pk)
        initial = {} if instance else {"kind": request.GET.get("kind", "groq")}
        return self.render_form(request, AIModelForm(instance=instance, initial=initial), instance)

    def post(self, request, pk=None):
        instance = self.get_instance(pk)
        form = AIModelForm(request.POST, instance=instance)
        if not form.is_valid():
            return self.render_form(request, form, instance)
        model = form.save(commit=False)
        if instance is None:
            model.position = (AIModel.objects.aggregate(top=Max("position"))["top"] or 0) + 1
        model.save()
        messages.success(request, f"“{model.label}” kaydedildi.")
        return redirect(LIST_URL_NAME)


class AIModelImportEnvView(StaffRequiredMixin, View):
    """Copies the .env chain into the list so it can be edited; only offered while the list is empty."""

    def post(self, request):
        if AIModel.objects.exists():
            return redirect(LIST_URL_NAME)
        for position, spec in enumerate(specs_from_environment(), start=1):
            AIModel.objects.create(
                kind=spec.kind, label=spec.label, model_name=spec.model, base_url=spec.base_url,
                key_env=spec.key_env, position=position,
            )
        messages.success(request, ".env ayarların listeye aktarıldı. Artık buradan yönetebilirsin.")
        return redirect(LIST_URL_NAME)


class AIModelActionView(StaffRequiredMixin, View):
    """Small one-click changes on a single model."""

    def post(self, request, pk, action):
        model = get_object_or_404(AIModel, pk=pk)
        handler = getattr(self, f"do_{action}", None)
        if handler is None:
            raise Http404
        return handler(request, model) or redirect(LIST_URL_NAME)

    def do_toggle(self, request, model):
        model.enabled = not model.enabled
        model.save(update_fields=["enabled"])

    def do_up(self, request, model):
        self._swap_with_neighbour(model, before=True)

    def do_down(self, request, model):
        self._swap_with_neighbour(model, before=False)

    def do_delete(self, request, model):
        model.delete()
        messages.success(request, f"“{model.label}” silindi.")

    def do_use(self, request, model):
        name = request.POST.get("model_name", "").strip()[: AIModel._meta.get_field("model_name").max_length]
        if name:
            model.model_name = name
            model.save(update_fields=["model_name"])
            messages.success(request, f"“{model.label}” artık {name} modelini kullanıyor.")

    def do_test(self, request, model):
        try:
            client = build_client(ai_registry.spec_for(model))
            client.chat_json('Reply only with the JSON object {"ok": true}.', [{"role": "user", "content": "ping"}])
        except AIError as error:
            messages.error(request, f"“{model.label}” çalışmadı: {error}")
        else:
            messages.success(request, f"“{model.label}” çalışıyor ({model.model_name}).")

    def _swap_with_neighbour(self, model: AIModel, before: bool) -> None:
        ordered = list(AIModel.objects.all())
        index = ordered.index(model)
        other = index - 1 if before else index + 1
        if not 0 <= other < len(ordered):
            return
        ordered[index], ordered[other] = ordered[other], ordered[index]
        # Re-number the whole list so equal or gappy positions can never leave the order ambiguous.
        for position, item in enumerate(ordered, start=1):
            if item.position != position:
                AIModel.objects.filter(pk=item.pk).update(position=position)


class AIModelAvailableView(StaffRequiredMixin, View):
    """Asks the provider which model names the key can use; handy when a model has been retired."""

    def get(self, request, pk):
        model = get_object_or_404(AIModel, pk=pk)
        names, error = [], ""
        try:
            client = build_client(ai_registry.spec_for(model))
            names = client.list_models()[:MAX_LISTED_MODELS]
        except AIError as failure:
            error = str(failure)
        except AttributeError:
            error = "Bu sağlayıcı model listesi vermiyor."
        return render(request, "ideas/ai_model_available.html", {"object": model, "names": names, "error": error})
