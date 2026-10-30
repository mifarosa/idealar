"""Which AI models a user has brought: their own list, with keys unsealed only for the moment of a call."""
import logging
import re

from ai.fallback import FallbackClient
from ai.providers import KINDS, PROVIDER_LABELS, ModelSpec, build_chain

from .key_vault import KeyUnreadable, unseal
from .models import AIModel

logger = logging.getLogger(__name__)
CHAIN_NAME = re.compile(r"m(\d+)")


def usable_models(user) -> list[AIModel]:
    """Enabled, fully set up models of this user. A model of a staff-only kind is ignored once its owner is no longer staff."""
    models = AIModel.objects.filter(owner=user, enabled=True)
    return [m for m in models if m.model_name and (user.is_staff or not KINDS.get(m.kind, KINDS["custom"]).staff_only)]


def spec_for(model: AIModel) -> ModelSpec:
    try:
        key = unseal(model.api_key_sealed, model.owner_id) if model.api_key_sealed else ""
    except KeyUnreadable:
        logger.warning("Stored key of AI model %s cannot be decrypted; the owner must enter it again", model.pk)
        key = ""
    return ModelSpec(model.chain_name, model.label, model.kind, model.model_name, model.base_url, api_key=key)


def problem(model: AIModel, user) -> str:
    """Why this model cannot be used right now, or "" when it can."""
    info = KINDS.get(model.kind)
    if not model.enabled:
        return "kapalı"
    if info is None or (info.staff_only and not user.is_staff):
        return "bu tür yalnızca yönetici hesabında çalışır"
    if not model.model_name:
        return "model seçilmedi (\"Modeller\" tuşuna bas)"
    if info.needs_key and not model.api_key_sealed:
        return "anahtar kayıtlı değil"
    if model.api_key_sealed and not _readable(model):
        return "kayıtlı anahtar okunamıyor (şifreleme anahtarı değişmiş); modeli düzenleyip anahtarı yeniden gir"
    return ""


def diagnose(user) -> list[tuple[str, str]]:
    """(label, why) for every model of the user that cannot be used right now, in list order."""
    return [(model.label, why) for model in AIModel.objects.filter(owner=user) if (why := problem(model, user))]


def _readable(model: AIModel) -> bool:
    try:
        unseal(model.api_key_sealed, model.owner_id)
    except KeyUnreadable:
        return False
    return True


def has_models(user) -> bool:
    return bool(usable_models(user))


def build_client(user, preferred: str | None = None) -> FallbackClient:
    """The user's fallback chain. `preferred` is a chain name (m12) or a provider kind (gemini) to try first."""
    models = usable_models(user)
    if preferred in KINDS:
        preferred = next((m.chain_name for m in models if m.kind == preferred), None)
    return build_chain([spec_for(model) for model in models], preferred=preferred)


def choices(user) -> list[tuple[str, str]]:
    """(chain name, label) pairs for the picker, in priority order; models without a key are left out."""
    labels = {model.chain_name: model.label for model in usable_models(user)}
    return [(client.name, labels[client.name]) for client in build_client(user)._clients]


def label_for(name: str) -> str:
    """Human label of a stored chain name; history survives models that were renamed or deleted."""
    match = CHAIN_NAME.fullmatch(name)
    if match:
        label = AIModel.objects.filter(pk=int(match.group(1))).values_list("label", flat=True).first()
        return label or "silinmiş model"
    return PROVIDER_LABELS.get(name, name)
