import logging
from dataclasses import dataclass, field

from .client import LLMClient
from .errors import AIError, AINotConfiguredError, AllProvidersFailed

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunInfo:
    served_by: str
    failed: list[str] = field(default_factory=list)


class FallbackClient(LLMClient):
    """Tries providers in order; any AIError (rate limit, outage, bad output) moves on to the next."""

    name = "fallback"

    def __init__(self, clients: list[LLMClient]):
        self._clients = clients
        # Set after each successful call; clients are built per request, so this is not shared state.
        self.last_run: RunInfo | None = None

    def chat_json(self, system: str, messages: list[dict]) -> dict:
        if not self._clients:
            raise AINotConfiguredError("No AI provider is configured. See AI_PROVIDERS in .env.example.")
        failures: list[tuple[str, AIError]] = []
        for client in self._clients:
            try:
                answer = client.chat_json(system, messages)
                self.last_run = RunInfo(served_by=client.name, failed=[name for name, _ in failures])
                return answer
            except AIError as error:
                logger.warning("AI provider %s failed: %s", client.name, error)
                failures.append((client.name, error))
        raise AllProvidersFailed(failures)
