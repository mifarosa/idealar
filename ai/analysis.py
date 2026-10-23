"""Turns a raw idea into a title, summary, tags and suggested features via an LLMClient."""
from collections.abc import Sequence
from dataclasses import dataclass

from .client import LLMClient
from .errors import AIResponseError

MAX_IDEA_CHARS = 4000
MAX_TITLE_CHARS = 80
MAX_SUMMARY_CHARS = 400
MAX_TAGS = 5
MAX_TAG_CHARS = 30
MAX_SUGGESTIONS = 6
MAX_SUGGESTION_CHARS = 120

SYSTEM_PROMPT = """You help a solo developer organize app ideas. You receive one raw idea note.
Answer in the same language as the note (usually Turkish). Reply with ONLY a JSON object:
{
  "title": "short, concrete app name or headline, max 60 characters",
  "summary": "one or two plain sentences: what it is and who it helps",
  "tags": ["2 to 5 short lowercase tags such as a domain or platform"],
  "suggested_features": ["3 to 6 concrete, buildable features for a first version, each under 12 words"]
}
Do not repeat features the developer already listed. Do not invent facts beyond the note."""


@dataclass(frozen=True)
class IdeaInsights:
    title: str
    summary: str
    tags: list[str]
    suggested_features: list[str]


class IdeaAnalyzer:
    def __init__(self, client: LLMClient):
        self._client = client

    def analyze(self, idea_text: str, existing_features: Sequence[str] = ()) -> IdeaInsights:
        answer = self._client.complete_json(SYSTEM_PROMPT, _build_user_message(idea_text, existing_features))
        return _parse_insights(answer, existing_features)


def _build_user_message(idea_text: str, existing_features: Sequence[str]) -> str:
    message = f"Idea note:\n{idea_text[:MAX_IDEA_CHARS]}"
    if existing_features:
        listed = "\n".join(f"- {feature}" for feature in existing_features)
        message += f"\n\nFeatures already listed:\n{listed}"
    return message


def _parse_insights(answer: dict, existing_features: Sequence[str]) -> IdeaInsights:
    title = _clean_text(answer.get("title"), MAX_TITLE_CHARS)
    summary = _clean_text(answer.get("summary"), MAX_SUMMARY_CHARS)
    if not title:
        raise AIResponseError("Model answer has no title")
    return IdeaInsights(
        title=title,
        summary=summary,
        tags=_clean_tags(answer.get("tags")),
        suggested_features=_clean_features(answer.get("suggested_features"), existing_features),
    )


def _clean_text(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _string_items(value) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _unique(items: list[str], limit: int, taken: Sequence[str] = ()) -> list[str]:
    seen = {item.casefold() for item in taken}
    result: list[str] = []
    for item in items:
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            result.append(item)
    return result[:limit]


def _clean_tags(value) -> list[str]:
    tags = [tag.strip().lstrip("#").strip().lower()[:MAX_TAG_CHARS] for tag in _string_items(value)]
    return _unique(tags, MAX_TAGS)


def _clean_features(value, existing_features: Sequence[str]) -> list[str]:
    features = [feature.strip()[:MAX_SUGGESTION_CHARS] for feature in _string_items(value)]
    return _unique(features, MAX_SUGGESTIONS, taken=existing_features)
