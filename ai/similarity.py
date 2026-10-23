"""Decides whether a new idea duplicates something the developer already has (an idea or a project)."""
from collections.abc import Sequence
from dataclasses import dataclass

from .client import LLMClient

KIND_IDEA, KIND_PROJECT = "idea", "project"
VERDICT_SAME, VERDICT_SIMILAR, VERDICT_RELATED = "same", "similar", "related"
VERDICT_ORDER = {VERDICT_SAME: 0, VERDICT_SIMILAR: 1, VERDICT_RELATED: 2}
MAX_MATCHES = 5
MAX_REASON_CHARS = 300
MAX_NEW_IDEA_CHARS = 2000

SYSTEM_PROMPT = """You compare a NEW app idea against the developer's EXISTING ideas and projects to find duplicates.
Be strict and literal. Verdicts:
- "same": the same product goal, building both would be building one thing twice.
- "similar": the core purpose clearly overlaps, so the new idea should probably be added to the existing one.
- "related": adjacent topic only (weak).
Never match just because both are mobile apps, use AI, or share generic words. Judge the purpose, not the wording
(a Turkish and an English description of the same product are a match). If nothing overlaps, return an empty list.
Reply with ONLY JSON, with reasons in the language of the new idea (usually Turkish):
{"matches": [{"kind": "idea" or "project", "id": <id from the list>, "verdict": "same|similar|related",
 "reason": "one sentence naming what overlaps"}]}"""


@dataclass(frozen=True)
class Candidate:
    kind: str  # KIND_IDEA or KIND_PROJECT
    id: int
    title: str
    summary: str


@dataclass(frozen=True)
class SimilarMatch:
    kind: str
    id: int
    verdict: str
    reason: str


class SimilarityJudge:
    def __init__(self, client: LLMClient):
        self._client = client

    def judge(self, new_idea: str, candidates: Sequence[Candidate]) -> list[SimilarMatch]:
        if not candidates:
            return []
        answer = self._client.complete_json(SYSTEM_PROMPT, _user_message(new_idea, candidates))
        return _parse_matches(answer, candidates)


def _user_message(new_idea: str, candidates: Sequence[Candidate]) -> str:
    listed = "\n".join(f"[{c.kind}:{c.id}] {c.title} — {c.summary}" for c in candidates)
    return f"NEW IDEA:\n{new_idea[:MAX_NEW_IDEA_CHARS]}\n\nEXISTING:\n{listed}"


def _parse_matches(answer: dict, candidates: Sequence[Candidate]) -> list[SimilarMatch]:
    known = {(c.kind, c.id) for c in candidates}
    raw = answer.get("matches")
    parsed = (_parse_match(item, known) for item in (raw if isinstance(raw, list) else []))
    unique: dict[tuple[str, int], SimilarMatch] = {}
    for match in filter(None, parsed):
        unique.setdefault((match.kind, match.id), match)
    ranked = sorted(unique.values(), key=lambda m: VERDICT_ORDER[m.verdict])
    return ranked[:MAX_MATCHES]


def _parse_match(item, known: set[tuple[str, int]]) -> SimilarMatch | None:
    if not isinstance(item, dict):
        return None
    kind, verdict, reason = item.get("kind"), item.get("verdict"), item.get("reason")
    target_id = _as_int(item.get("id"))
    if (kind, target_id) not in known or verdict not in VERDICT_ORDER:
        return None  # the model invented an id or a verdict
    return SimilarMatch(kind, target_id, verdict, reason.strip()[:MAX_REASON_CHARS] if isinstance(reason, str) else "")


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.strip().isdigit() else None
