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

from . import ai_registry, key_vault
from .ai_settings_forms import AIModelForm
from .models import AIModel

LIST_URL_NAME = "ideas:ai-models"
MAX_LISTED_MODELS = 200


class StaffRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_staff:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def own_models(user):
    """Every lookup goes through here, so one user can never see or touch another user's models."""
    return AIModel.objects.filter(owner=user)


def get_own(user, pk) -> AIModel:
    model = get_object_or_404(own_models(user), pk=pk)
    if KINDS.get(model.kind, KINDS["custom"]).staff_only and not user.is_staff:
        raise Http404  # a model that points at an arbitrary address is only usable by staff
    return model


def key_is_set(model: AIModel) -> bool:
    info = KINDS.get(model.kind)
    return not info or not info.needs_key or bool(model.api_key_sealed)


class AIModelListView(LoginRequiredMixin, View):
    def get(self, request):
        models = list(own_models(request.user))
        for model in models:
            model.kind_label = KINDS[model.kind].label if model.kind in KINDS else model.kind
            model.key_missing = not key_is_set(model)
        return render(request, "ideas/ai_models.html", {"models": models, "can_import_env": request.user.is_staff and not models})


class AIModelFormView(LoginRequiredMixin, View):
    def get_instance(self, pk):
        return get_object_or_404(own_models(self.request.user), pk=pk) if pk else None

    def render_form(self, request, form, instance):
        return render(request, "ideas/ai_model_form.html", {"form": form, "object": instance})

    def get(self, request, pk=None):
        instance = self.get_instance(pk)
        initial = {} if instance else {"kind": request.GET.get("kind", "groq")}
        return self.render_form(request, AIModelForm(instance=instance, initial=initial, user=request.user), instance)

    def post(self, request, pk=None):
        instance = self.get_instance(pk)
        form = AIModelForm(request.POST, instance=instance, user=request.user)
        if not form.is_valid():
            return self.render_form(request, form, instance)
        model = form.save(commit=False)
        if instance is None:
            model.position = (own_models(request.user).aggregate(top=Max("position"))["top"] or 0) + 1
        model.save()
        messages.success(request, f"“{model.label}” kaydedildi.")
        return redirect(LIST_URL_NAME)


class AIModelImportEnvView(StaffRequiredMixin, View):
    """Staff only: copies the server's .env AI chain (with its keys, sealed) into the staff user's own list."""

    def post(self, request):
        if own_models(request.user).exists():
            return redirect(LIST_URL_NAME)
        imported = 0
        for position, spec in enumerate(specs_from_environment(), start=1):
            key = os.environ.get(spec.key_env, "").strip() if spec.key_env else ""
            if KINDS[spec.kind].needs_key and not key:
                continue
            AIModel.objects.create(
                owner=request.user, kind=spec.kind, label=spec.label, model_name=spec.model, base_url=spec.base_url,
                api_key_sealed=key_vault.seal(key) if key else "", key_hint=key_vault.hint(key), position=position,
            )
            imported += 1
        messages.success(request, f".env'den {imported} model aktarıldı. Artık buradan yönetebilirsin.")
        return redirect(LIST_URL_NAME)


class AIModelActionView(LoginRequiredMixin, View):
    """Small one-click changes on a single model."""

    def post(self, request, pk, action):
        model = get_own(request.user, pk)
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
        ordered = list(own_models(model.owner))
        index = ordered.index(model)
        other = index - 1 if before else index + 1
        if not 0 <= other < len(ordered):
            return
        ordered[index], ordered[other] = ordered[other], ordered[index]
        # Re-number the whole list so equal or gappy positions can never leave the order ambiguous.
        for position, item in enumerate(ordered, start=1):
            if item.position != position:
                AIModel.objects.filter(pk=item.pk).update(position=position)


class AIModelAvailableView(LoginRequiredMixin, View):
    """Asks the provider which model names the key can use; handy when a model has been retired."""

    def get(self, request, pk):
        model = get_own(request.user, pk)
        names, error = [], ""
        try:
            client = build_client(ai_registry.spec_for(model))
            names = client.list_models()[:MAX_LISTED_MODELS]
        except AIError as failure:
            error = str(failure)
        except AttributeError:
            error = "Bu sağlayıcı model listesi vermiyor."
        return render(request, "ideas/ai_model_available.html", {"object": model, "names": names, "error": error})
