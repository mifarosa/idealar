"""Provider registry: the only file to touch when adding or swapping an AI provider.

The chain order comes from AI_PROVIDERS (default "groq,ollama"): the first is primary, the rest are
fallbacks. A provider whose required key is missing is skipped with a warning.
"""
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .anthropic_client import AnthropicClient
from .client import LLMClient, OpenAICompatibleClient
from .errors import AINotConfiguredError
from .fallback import FallbackClient

logger = logging.getLogger(__name__)

DEFAULT_CHAIN = "groq,ollama"
CLOUD_TIMEOUT_SECONDS = 40  # repo reviews send large prompts
LOCAL_TIMEOUT_SECONDS = 90  # small local models on CPU are slow
# Groq retires models regularly (llama-3.3-70b-versatile was shut down); run `manage.py ai_models` to check.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
# "-latest" aliases follow Google's current model, so the default does not go stale like a pinned version.
DEFAULT_GEMINI_MODEL = "gemini-flash-lite-latest"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"


def _required(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key, "").strip()
    if not value:
        raise AINotConfiguredError(f"{key} is not set")
    return value


def _groq(environ: Mapping[str, str]) -> LLMClient:
    return OpenAICompatibleClient(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key=_required(environ, "GROQ_API_KEY"),
        model=environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL),
        timeout=CLOUD_TIMEOUT_SECONDS,
    )


def _openrouter(environ: Mapping[str, str]) -> LLMClient:
    return OpenAICompatibleClient(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key=_required(environ, "OPENROUTER_API_KEY"),
        model=_required(environ, "OPENROUTER_MODEL"),
        timeout=CLOUD_TIMEOUT_SECONDS,
    )


def _gemini(environ: Mapping[str, str]) -> LLMClient:
    # Google AI Studio exposes an OpenAI-compatible endpoint.
    return OpenAICompatibleClient(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key=_required(environ, "GEMINI_API_KEY"),
        model=environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        timeout=CLOUD_TIMEOUT_SECONDS,
    )


def _anthropic(environ: Mapping[str, str]) -> LLMClient:
    return AnthropicClient(
        name="anthropic",
        api_key=_required(environ, "ANTHROPIC_API_KEY"),
        model=environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL),
        timeout=CLOUD_TIMEOUT_SECONDS,
    )


def _ollama(environ: Mapping[str, str]) -> LLMClient:
    host = environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    return OpenAICompatibleClient(
        name="ollama",
        base_url=f"{host}/v1",
        model=environ.get("OLLAMA_MODEL", "qwen2.5:3b"),
        timeout=LOCAL_TIMEOUT_SECONDS,
    )


PROVIDER_FACTORIES: dict[str, Callable[[Mapping[str, str]], LLMClient]] = {
    "groq": _groq,
    "gemini": _gemini,
    "anthropic": _anthropic,
    "openrouter": _openrouter,
    "ollama": _ollama,
}


PROVIDER_LABELS = {"groq": "Groq", "gemini": "Gemini", "anthropic": "Claude", "openrouter": "OpenRouter", "ollama": "Ollama"}


def _chain_names(environ: Mapping[str, str]) -> list[str]:
    return [name.strip() for name in environ.get("AI_PROVIDERS", DEFAULT_CHAIN).split(",") if name.strip()]


def configured_provider_names(environ: Mapping[str, str] | None = None) -> list[str]:
    """Providers that are usable right now, in priority order (for the UI picker)."""
    environ = os.environ if environ is None else environ
    return [name for name in _chain_names(environ) if _build_or_skip(name, environ, log_skips=False) is not None]


def build_default_client(environ: Mapping[str, str] | None = None, preferred: str | None = None) -> FallbackClient:
    """The fallback chain. A `preferred` provider is tried first; the others follow in configured order."""
    environ = os.environ if environ is None else environ
    names = _chain_names(environ)
    if preferred in names:
        names = [preferred] + [name for name in names if name != preferred]
    clients = [client for name in names if (client := _build_or_skip(name, environ)) is not None]
    return FallbackClient(clients)


def _build_or_skip(name: str, environ: Mapping[str, str], log_skips: bool = True) -> LLMClient | None:
    factory = PROVIDER_FACTORIES.get(name)
    if factory is None:
        raise AINotConfiguredError(f"Unknown AI provider '{name}'. Known: {', '.join(PROVIDER_FACTORIES)}")
    try:
        return factory(environ)
    except AINotConfiguredError as error:
        if log_skips:
            logger.warning("AI provider %s skipped: %s", name, error)
        return None


# ---------- Models defined by the user (stored in the database, see ideas.models.AIModel) ----------


@dataclass(frozen=True)
class KindInfo:
    label: str
    base_url: str  # fixed endpoint; empty means the user supplies it
    key_env: str  # suggested env variable holding the key; empty means no key
    needs_key: bool
    local: bool = False  # slow hardware: longer timeout
    default_model: str = ""  # used when the user leaves the model name empty
    send_temperature: bool = True  # OpenAI's newer models reject any value except their default
    staff_only: bool = False  # the user supplies the address, so only trusted users may use it (server-side request risk)


KINDS: dict[str, KindInfo] = {
    "groq": KindInfo("Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", True, default_model=DEFAULT_GROQ_MODEL),
    "gemini": KindInfo("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", True, default_model=DEFAULT_GEMINI_MODEL),
    "anthropic": KindInfo("Claude", "", "ANTHROPIC_API_KEY", True, default_model=DEFAULT_ANTHROPIC_MODEL),
    "openai": KindInfo("ChatGPT (OpenAI)", "https://api.openai.com/v1", "OPENAI_API_KEY", True, send_temperature=False),
    "openrouter": KindInfo("OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", True),
    "mistral": KindInfo("Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", True),
    "deepseek": KindInfo("DeepSeek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", True),
    "xai": KindInfo("Grok (xAI)", "https://api.x.ai/v1", "XAI_API_KEY", True),
    "together": KindInfo("Together AI", "https://api.together.xyz/v1", "TOGETHER_API_KEY", True),
    "cerebras": KindInfo("Cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", True),
    "fireworks": KindInfo("Fireworks AI", "https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY", True),
    "ollama": KindInfo("Ollama", "", "", False, local=True, staff_only=True),
    "custom": KindInfo("Diğer (OpenAI uyumlu)", "", "", False, local=True, staff_only=True),
}


@dataclass(frozen=True)
class ModelSpec:
    """One configured model. `api_key` is kept out of repr so it cannot leak into logs or tracebacks."""

    name: str
    label: str
    kind: str
    model: str
    base_url: str = ""
    key_env: str = ""  # name of an env variable holding the key, used by the .env chain
    api_key: str = field(default="", repr=False)


def build_client(spec: ModelSpec, environ: Mapping[str, str] | None = None) -> LLMClient:
    environ = os.environ if environ is None else environ
    info = KINDS.get(spec.kind)
    if info is None:
        raise AINotConfiguredError(f"Unknown AI kind '{spec.kind}'")
    api_key = spec.api_key or (environ.get(spec.key_env, "").strip() if spec.key_env else "")
    if info.needs_key and not api_key:
        raise AINotConfiguredError(f"{spec.label} has no API key")
    timeout = LOCAL_TIMEOUT_SECONDS if info.local else CLOUD_TIMEOUT_SECONDS
    if spec.kind == "anthropic":
        return AnthropicClient(spec.name, spec.model, api_key, timeout=timeout)
    base_url = info.base_url or spec.base_url.rstrip("/")
    if not base_url:
        raise AINotConfiguredError(f"{spec.label} has no address")
    if spec.kind == "ollama":
        base_url += "/v1"
    temperature = 0.3 if info.send_temperature else None
    return OpenAICompatibleClient(spec.name, base_url, spec.model, api_key=api_key, timeout=timeout, temperature=temperature)


def build_chain(specs: list[ModelSpec], environ: Mapping[str, str] | None = None, preferred: str | None = None) -> FallbackClient:
    """Fallback chain from user-defined models in the given order; a model whose key is missing is skipped."""
    ordered = sorted(specs, key=lambda spec: spec.name != preferred)  # stable: only the preferred one moves up
    clients = []
    for spec in ordered:
        try:
            clients.append(build_client(spec, environ))
        except AINotConfiguredError as error:
            logger.warning("AI model %s skipped: %s", spec.label, error)
    return FallbackClient(clients)


_ENV_MODELS = {
    "groq": ("GROQ_MODEL", DEFAULT_GROQ_MODEL),
    "gemini": ("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
    "anthropic": ("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL),
    "openrouter": ("OPENROUTER_MODEL", ""),
    "ollama": ("OLLAMA_MODEL", "qwen2.5:3b"),
}


def specs_from_environment(environ: Mapping[str, str] | None = None) -> list[ModelSpec]:
    """The current .env chain expressed as model definitions, used to seed the settings page."""
    environ = os.environ if environ is None else environ
    specs = []
    for position, kind in enumerate(_chain_names(environ), start=1):
        if kind not in _ENV_MODELS:
            continue
        model_var, default = _ENV_MODELS[kind]
        base_url = environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") if kind == "ollama" else ""
        specs.append(ModelSpec(f"m{position}", KINDS[kind].label, kind, environ.get(model_var, default), base_url, KINDS[kind].key_env))
    return specs
