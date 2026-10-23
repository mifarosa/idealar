import logging

from .client import LLMClient
from .errors import AIError, AINotConfiguredError, AllProvidersFailed

logger = logging.getLogger(__name__)


class FallbackClient(LLMClient):
    """Tries providers in order; any AIError (rate limit, outage, bad output) moves on to the next."""

    name = "fallback"

    def __init__(self, clients: list[LLMClient]):
        self._clients = clients

    def complete_json(self, system: str, user: str) -> dict:
        if not self._clients:
            raise AINotConfiguredError("No AI provider is configured. See AI_PROVIDERS in .env.example.")
        failures: list[tuple[str, AIError]] = []
        for client in self._clients:
            try:
                return client.complete_json(system, user)
            except AIError as error:
                logger.warning("AI provider %s failed: %s", client.name, error)
                failures.append((client.name, error))
        raise AllProvidersFailed(failures)
