"""Reviews a GitHub repository snapshot: what exists, what looks solved, and which checklist items are done."""
from collections.abc import Sequence
from dataclasses import dataclass, field

from .client import LLMClient
from .errors import AIResponseError

STATUS_DONE, STATUS_PARTIAL, STATUS_NOT_FOUND, STATUS_UNCLEAR = "done", "partial", "not_found", "unclear"
MATCH_STATUSES = {STATUS_DONE, STATUS_PARTIAL, STATUS_NOT_FOUND, STATUS_UNCLEAR}
MAX_SUMMARY_CHARS = 800
MAX_LIST_ITEMS = 12
MAX_ITEM_CHARS = 200

SYSTEM_PROMPT = """You are a senior engineer reviewing a PARTIAL snapshot of a GitHub repository (metadata, README,
file tree, a few manifest/source files, recent commit messages). You cannot see all the code.
Be evidence-based: only say something is implemented when the snapshot shows it (a file, code, README, commit).
If you cannot tell, say it is unclear rather than guessing. Reply in Turkish with ONLY this JSON:
{
  "summary": "2-4 sentences: what this project is and how far along it looks",
  "tech": ["languages/frameworks/tools actually evident"],
  "implemented": ["features that the snapshot shows are working, each with its evidence in a few words"],
  "gaps": ["important things missing or unclear: tests, auth, docs, deployment, unfinished areas"],
  "feature_matches": [{"feature_id": <id>, "status": "done|partial|not_found|unclear", "evidence": "file or commit"}]
}
feature_matches covers ONLY the developer's checklist items given below; use "done" only with clear evidence."""


@dataclass(frozen=True)
class FeatureMatch:
    feature_id: int
    status: str
    evidence: str


@dataclass(frozen=True)
class RepoReview:
    summary: str
    tech: list[str] = field(default_factory=list)
    implemented: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    feature_matches: list[FeatureMatch] = field(default_factory=list)


class RepoReviewer:
    def __init__(self, client: LLMClient):
        self._client = client

    @property
    def last_run(self):
        """Which provider answered (when the client is a fallback chain), else None."""
        return getattr(self._client, "last_run", None)

    def review(self, snapshot: str, features: Sequence[tuple[int, str]] = ()) -> RepoReview:
        answer = self._client.complete_json(SYSTEM_PROMPT, _user_message(snapshot, features))
        return _parse_review(answer, {feature_id for feature_id, _ in features})


def _user_message(snapshot: str, features: Sequence[tuple[int, str]]) -> str:
    checklist = "\n".join(f"[{feature_id}] {text}" for feature_id, text in features) or "(none)"
    return f"REPOSITORY SNAPSHOT:\n{snapshot}\n\nDEVELOPER'S CHECKLIST:\n{checklist}"


def _parse_review(answer: dict, known_feature_ids: set[int]) -> RepoReview:
    summary = answer.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise AIResponseError("Model answer has no summary")
    return RepoReview(
        summary=summary.strip()[:MAX_SUMMARY_CHARS],
        tech=_clean_list(answer.get("tech")),
        implemented=_clean_list(answer.get("implemented")),
        gaps=_clean_list(answer.get("gaps")),
        feature_matches=_parse_matches(answer.get("feature_matches"), known_feature_ids),
    )


def _clean_list(value) -> list[str]:
    items = value if isinstance(value, list) else []
    return [item.strip()[:MAX_ITEM_CHARS] for item in items if isinstance(item, str) and item.strip()][:MAX_LIST_ITEMS]


def _parse_matches(value, known_feature_ids: set[int]) -> list[FeatureMatch]:
    matches: dict[int, FeatureMatch] = {}
    for item in value if isinstance(value, list) else []:
        match = _parse_match(item, known_feature_ids)
        if match:
            matches.setdefault(match.feature_id, match)
    return list(matches.values())


def _parse_match(item, known_feature_ids: set[int]) -> FeatureMatch | None:
    if not isinstance(item, dict):
        return None
    feature_id, status, evidence = item.get("feature_id"), item.get("status"), item.get("evidence")
    if isinstance(feature_id, str) and feature_id.strip().isdigit():
        feature_id = int(feature_id)
    if isinstance(feature_id, bool) or feature_id not in known_feature_ids or status not in MATCH_STATUSES:
        return None  # an invented checklist id or status
    return FeatureMatch(feature_id, status, evidence.strip()[:MAX_ITEM_CHARS] if isinstance(evidence, str) else "")
