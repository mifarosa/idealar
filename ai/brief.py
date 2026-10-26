"""Drafts a build brief (MVP scope, stack, phases, risks) for an idea; used to enrich the copy-paste build prompt."""
from collections.abc import Sequence
from dataclasses import dataclass, field

from .client import LLMClient
from .errors import AIResponseError

MAX_ITEMS = 8
MAX_ITEM_CHARS = 240
MAX_STACK_CHARS = 400
MAX_IDEA_CHARS = 3000

SYSTEM_PROMPT = """You are a pragmatic senior engineer helping a solo developer turn an app idea into a build plan.
You get the idea, its platforms and its feature checklist. Reply in Turkish with ONLY this JSON:
{
  "mvp": ["the smallest set of features worth shipping first, concrete and testable, at most 6"],
  "stack": "one or two sentences: a sensible technology choice for the stated platforms and why (prefer simple, boring tools)",
  "phases": ["ordered build phases, each one short sentence that names what is demonstrable at its end, 3 to 5"],
  "risks": ["real technical or product risks, not generic advice, at most 4"]
}
Do not invent requirements that the idea does not imply. If the repository already exists (mode "extend"), phrase
phases as additions to the existing project rather than a fresh start."""


@dataclass(frozen=True)
class Brief:
    mvp: list[str] = field(default_factory=list)
    stack: str = ""
    phases: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.mvp or self.stack or self.phases or self.risks)


class BriefWriter:
    def __init__(self, client: LLMClient):
        self._client = client

    def write(self, idea_text: str, platforms: Sequence[str], features: Sequence[str], extend_existing: bool) -> Brief:
        message = _user_message(idea_text, platforms, features, extend_existing)
        brief = _parse(self._client.complete_json(SYSTEM_PROMPT, message))
        if brief.is_empty:
            raise AIResponseError("Model answer contains no usable plan")
        return brief


def _user_message(idea_text: str, platforms: Sequence[str], features: Sequence[str], extend_existing: bool) -> str:
    listed = "\n".join(f"- {feature}" for feature in features) or "(none yet)"
    mode = "extend" if extend_existing else "new"
    return f"MODE: {mode}\nPLATFORMS: {', '.join(platforms) or 'unspecified'}\nIDEA:\n{idea_text[:MAX_IDEA_CHARS]}\n\nFEATURES:\n{listed}"


def _items(value) -> list[str]:
    raw = value if isinstance(value, list) else []
    return [item.strip()[:MAX_ITEM_CHARS] for item in raw if isinstance(item, str) and item.strip()][:MAX_ITEMS]


def _parse(answer: dict) -> Brief:
    stack = answer.get("stack")
    return Brief(
        mvp=_items(answer.get("mvp")),
        stack=stack.strip()[:MAX_STACK_CHARS] if isinstance(stack, str) else "",
        phases=_items(answer.get("phases")),
        risks=_items(answer.get("risks")),
    )
