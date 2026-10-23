"""The one interface every AI call goes through, plus a client for OpenAI-compatible APIs.

Groq, OpenRouter, Gemini's compatibility endpoint and Ollama all speak this protocol, so a single
class covers them; only the base URL, key and model differ (see providers.py).
"""
import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from .errors import AIProviderError, AIRateLimitError, AIResponseError

ERROR_BODY_PREVIEW_CHARS = 200
# Cloudflare-fronted APIs (e.g. Groq) reject urllib's default "Python-urllib" agent with HTTP 403 / code 1010.
USER_AGENT = "idealar/1.0"


class LLMClient(ABC):
    name: str

    @abstractmethod
    def chat_json(self, system: str, messages: list[dict]) -> dict:
        """Answers a conversation ({"role", "content"} messages) as a parsed JSON object, or raises an AIError."""

    def complete_json(self, system: str, user: str) -> dict:
        """Single-turn convenience over chat_json."""
        return self.chat_json(system, [{"role": "user", "content": user}])


def parse_json_object(text: str) -> dict:
    """Parses model output, tolerating markdown fences or chatter around the JSON object."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise AIResponseError("Model answer contains no JSON object")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise AIResponseError(f"Model answer is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise AIResponseError("Model answer is not a JSON object")
    return parsed


class OpenAICompatibleClient(LLMClient):
    def __init__(self, name: str, base_url: str, model: str, api_key: str = "", timeout: float = 20):
        self.name = name
        self._chat_url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    def chat_json(self, system: str, messages: list[dict]) -> dict:
        payload = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }
        return parse_json_object(self._extract_content(self._post(payload)))

    def _post(self, payload: dict) -> dict:
        request = urllib.request.Request(self._chat_url, data=json.dumps(payload).encode(), headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise self._error_for_status(error) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AIProviderError(f"{self.name} unreachable: {error}") from error
        except json.JSONDecodeError as error:
            raise AIResponseError(f"{self.name} returned a non-JSON HTTP body") from error

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _error_for_status(self, error: urllib.error.HTTPError):
        preview = error.read(ERROR_BODY_PREVIEW_CHARS).decode(errors="replace")
        if error.code == 429:
            return AIRateLimitError(f"{self.name} rate limit reached")
        return AIProviderError(f"{self.name} HTTP {error.code}: {preview}")

    def _extract_content(self, body: dict) -> str:
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise AIResponseError(f"{self.name} response has an unexpected shape") from error
