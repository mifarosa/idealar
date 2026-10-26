"""Which AI models the app uses: the ones managed in the settings page, or the .env chain until any exist."""
import re

from ai.fallback import FallbackClient
from ai.providers import KINDS, PROVIDER_LABELS, ModelSpec, build_chain, build_default_client, configured_provider_names

from .models import AIModel

CHAIN_NAME = re.compile(r"m(\d+)")


def spec_for(model: AIModel) -> ModelSpec:
    return ModelSpec(model.chain_name, model.label, model.kind, model.model_name, model.base_url, model.key_env)


def enabled_specs() -> list[ModelSpec]:
    return [spec_for(model) for model in AIModel.objects.filter(enabled=True)]


def uses_database() -> bool:
    """Once a model is added in the settings page, the .env chain is no longer consulted."""
    return AIModel.objects.exists()


def build_client(preferred: str | None = None) -> FallbackClient:
    if uses_database():
        return build_chain(enabled_specs(), preferred=preferred)
    return build_default_client(preferred=preferred)


def choices() -> list[tuple[str, str]]:
    """(chain name, label) pairs for the picker, in priority order."""
    if uses_database():
        usable = build_chain(enabled_specs())._clients
        labels = dict(AIModel.objects.values_list("id", "label"))
        return [(client.name, labels[int(CHAIN_NAME.fullmatch(client.name).group(1))]) for client in usable]
    return [(name, PROVIDER_LABELS.get(name, name)) for name in configured_provider_names()]


def label_for(name: str) -> str:
    """Human label of a stored chain name; history survives models that were renamed or deleted."""
    match = CHAIN_NAME.fullmatch(name)
    if match:
        label = AIModel.objects.filter(pk=int(match.group(1))).values_list("label", flat=True).first()
        return label or "silinmiş model"
    return PROVIDER_LABELS.get(name, name)


def kind_choices() -> list[tuple[str, str]]:
    return [(kind, info.label) for kind, info in KINDS.items()]
