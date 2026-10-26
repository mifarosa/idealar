"""Client for the Anthropic Claude API, built on the official SDK.

Claude does not speak the OpenAI protocol, so it gets its own LLMClient; everything above this
file only sees the same chat_json interface.
"""
import anthropic

from .client import LLMClient, parse_json_object
from .errors import AIProviderError, AIRateLimitError, AIResponseError

# Generous: the answer is a small JSON object, but repo reviews and build plans can be long.
MAX_OUTPUT_TOKENS = 8000


class AnthropicClient(LLMClient):
    def __init__(self, name: str, model: str, api_key: str, timeout: float = 60, base_url: str | None = None):
        self.name = name
        self._model = model
        # One retry covers a transient network blip; the fallback chain handles anything longer.
        self._sdk = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1, base_url=base_url)

    def chat_json(self, system: str, messages: list[dict]) -> dict:
        try:
            response = self._sdk.messages.create(
                model=self._model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=messages,
                output_config={"effort": "low"},  # notes and plans do not need deep reasoning; keeps it fast and cheap
            )
        except anthropic.RateLimitError as error:
            raise AIRateLimitError(f"{self.name} rate limit reached") from error
        except anthropic.APIStatusError as error:
            # error.message comes from the API response body and never contains the key.
            raise AIProviderError(f"{self.name} HTTP {error.status_code}: {error.message[:200]}") from error
        except anthropic.APIError as error:
            raise AIProviderError(f"{self.name} unreachable: {type(error).__name__}") from error
        return parse_json_object(self._text_of(response))

    def list_models(self) -> list[str]:
        """Model ids this key can use."""
        try:
            return sorted(model.id for model in self._sdk.models.list(limit=100))
        except anthropic.RateLimitError as error:
            raise AIRateLimitError(f"{self.name} rate limit reached") from error
        except anthropic.APIError as error:
            raise AIProviderError(f"{self.name} model list failed: {type(error).__name__}") from error

    def _text_of(self, response) -> str:
        if response.stop_reason == "refusal":
            raise AIResponseError(f"{self.name} declined to answer")
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text:
            raise AIResponseError(f"{self.name} returned no text")
        return text
