"""Provider registry: the only file to touch when adding or swapping an AI provider.

The chain order comes from AI_PROVIDERS (default "groq,ollama"): the first is primary, the rest are
fallbacks. A provider whose required key is missing is skipped with a warning.
"""
import logging
import os
from collections.abc import Callable, Mapping

from .client import LLMClient, OpenAICompatibleClient
from .errors import AINotConfiguredError
from .fallback import FallbackClient

logger = logging.getLogger(__name__)

DEFAULT_CHAIN = "groq,ollama"
CLOUD_TIMEOUT_SECONDS = 20
LOCAL_TIMEOUT_SECONDS = 90  # small local models on CPU are slow
# Groq retires models regularly (llama-3.3-70b-versatile was shut down); run `manage.py ai_models` to check.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


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
    # Google AI Studio exposes an OpenAI-compatible endpoint. Model names change often, so none is assumed.
    return OpenAICompatibleClient(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key=_required(environ, "GEMINI_API_KEY"),
        model=_required(environ, "GEMINI_MODEL"),
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
    "openrouter": _openrouter,
    "ollama": _ollama,
}


def build_default_client(environ: Mapping[str, str] | None = None) -> FallbackClient:
    environ = os.environ if environ is None else environ
    names = [name.strip() for name in environ.get("AI_PROVIDERS", DEFAULT_CHAIN).split(",") if name.strip()]
    clients = [client for name in names if (client := _build_or_skip(name, environ)) is not None]
    return FallbackClient(clients)


def _build_or_skip(name: str, environ: Mapping[str, str]) -> LLMClient | None:
    factory = PROVIDER_FACTORIES.get(name)
    if factory is None:
        raise AINotConfiguredError(f"Unknown AI provider '{name}'. Known: {', '.join(PROVIDER_FACTORIES)}")
    try:
        return factory(environ)
    except AINotConfiguredError as error:
        logger.warning("AI provider %s skipped: %s", name, error)
        return None
