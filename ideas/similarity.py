"""Duplicate detection for ideas.

Two stages: a cheap word-overlap pass picks which existing ideas/projects the AI should compare against
(for small collections: all of them), then the AI judges real overlap by purpose. If the AI is
unavailable, strong word overlap alone is reported and clearly marked as such.
"""
import logging
import re

from ai.errors import AIError
from ai.similarity import (
    KIND_IDEA,
    KIND_PROJECT,
    VERDICT_SIMILAR,
    Candidate,
    SimilarityJudge,
    SimilarMatch,
)
from django.utils.translation import gettext as _

from . import ai_registry
from .errors import ActionNotApplicable
from .models import (
    SIMILARITY_DONE,
    SIMILARITY_WORDS_ONLY,
    SUGGESTION_APPLIED,
    SUGGESTION_DISMISSED,
    SUGGESTION_PENDING,
    Feature,
    Idea,
    Project,
)

logger = logging.getLogger(__name__)

MAX_AI_CANDIDATES = 40  # up to this many existing items are all shown to the AI
SHORTLIST_BY_WORDS = 25
SHORTLIST_RECENT = 15
WORDS_ONLY_THRESHOLD = 0.5
SUMMARY_CHARS = 160
PROJECT_IDEA_TITLES = 5

STOPWORDS = frozenset(
    "ve ile için bir bu şu o da de ki mi mı mu mü gibi çok daha en ama veya olan olarak ya the a an and or of to "
    "for in on with is are be it this that app uygulama uygulaması uygulamasi yap yapmak".split()
)


def tokenize(text: str) -> set[str]:
    """Lowercased Turkish-aware word stems; the 5-letter prefix lets 'hatırlatıcı' match 'hatırlatma'."""
    normalized = text.replace("İ", "i").replace("I", "ı").lower()
    words = re.findall(r"[^\W\d_]{3,}", normalized)
    return {word[:5] for word in words if word not in STOPWORDS}


def word_overlap(first: set[str], second: set[str]) -> float:
    smaller = min(len(first), len(second))
    return len(first & second) / smaller if smaller >= 2 else 0.0


def _idea_candidate(idea: Idea) -> tuple[Candidate, set[str]]:
    summary = idea.ai_summary or idea.body.strip()[:SUMMARY_CHARS]
    words = tokenize(f"{idea.display_title} {idea.ai_summary} {idea.body}")
    return Candidate(KIND_IDEA, idea.pk, idea.display_title, summary), words


def _project_candidate(project: Project) -> tuple[Candidate, set[str]]:
    idea_titles = [i.display_title for i in project.ideas.all()[:PROJECT_IDEA_TITLES]]
    summary = f"{project.description.strip()[:SUMMARY_CHARS]} | ideas: {', '.join(idea_titles)}".strip(" |")
    return Candidate(KIND_PROJECT, project.pk, project.name, summary), tokenize(f"{project.name} {summary}")


def gather_candidates(idea: Idea) -> list[tuple[Candidate, set[str]]]:
    """Everything the idea could duplicate: the owner's other ideas and projects (not ones it is already in)."""
    ideas = Idea.objects.owned_by(idea.owner).exclude(pk=idea.pk)
    linked_project_ids = idea.projects.values_list("pk", flat=True)
    projects = Project.objects.filter(owner=idea.owner).exclude(pk__in=linked_project_ids).prefetch_related("ideas")
    return [_idea_candidate(i) for i in ideas] + [_project_candidate(p) for p in projects]


def _pick_for_ai(idea: Idea, candidates: list[tuple[Candidate, set[str]]]) -> list[Candidate]:
    if len(candidates) <= MAX_AI_CANDIDATES:
        return [candidate for candidate, _ in candidates]
    idea_words = tokenize(f"{idea.display_title} {idea.ai_summary} {idea.body}")
    by_words = sorted(candidates, key=lambda pair: word_overlap(idea_words, pair[1]), reverse=True)[:SHORTLIST_BY_WORDS]
    recent = candidates[:SHORTLIST_RECENT]  # gather_candidates lists newest ideas first
    picked = {pair[0].kind + str(pair[0].id): pair[0] for pair in by_words + recent}
    return list(picked.values())


def build_judge(owner) -> SimilarityJudge:
    return SimilarityJudge(ai_registry.build_client(owner))


def _idea_text(idea: Idea) -> str:
    return f"{idea.display_title}\n{idea.ai_summary}\n{idea.body}".strip()


def _entry(match: SimilarMatch, title: str, source: str) -> dict:
    return {
        "kind": match.kind,
        "id": match.id,
        "title": title,
        "verdict": match.verdict,
        "reason": match.reason,
        "source": source,
        "status": SUGGESTION_PENDING,
    }


def _words_only_matches(idea: Idea, candidates: list[tuple[Candidate, set[str]]]) -> list[dict]:
    idea_words = tokenize(_idea_text(idea))
    entries = []
    for candidate, words in candidates:
        if word_overlap(idea_words, words) >= WORDS_ONLY_THRESHOLD:
            shared = ", ".join(sorted(idea_words & words)[:5])
            match = SimilarMatch(candidate.kind, candidate.id, VERDICT_SIMILAR, _("Ortak kelimeler: {words}").format(words=shared))
            entries.append(_entry(match, candidate.title, "words"))
    return entries


def check_idea(idea: Idea, judge_factory=None) -> None:
    """Fills idea.similar. AI failure degrades to word-based matches instead of losing the check."""
    candidates = gather_candidates(idea)
    titles = {(c.kind, c.id): c.title for c, _ in candidates}
    try:
        judge = judge_factory() if judge_factory else build_judge(idea.owner)
        matches = judge.judge(_idea_text(idea), _pick_for_ai(idea, candidates))
        entries, status = [_entry(m, titles[(m.kind, m.id)], "ai") for m in matches], SIMILARITY_DONE
    except AIError as error:
        logger.warning("AI similarity check failed for idea %s: %s", idea.pk, error)
        entries, status = _words_only_matches(idea, candidates), SIMILARITY_WORDS_ONLY
    idea.similar, idea.similarity_status = entries, status
    idea.save(update_fields=["similar", "similarity_status", "updated_at"])


def decide_similar(idea: Idea, index: int, apply: bool) -> None:
    """Applies (link to the project / add as a feature of the idea) or dismisses one duplicate hint."""
    entry = idea.similar[index]
    if entry["status"] != SUGGESTION_PENDING:
        return
    if apply:
        _apply_similar(idea, entry)
    entry["status"] = SUGGESTION_APPLIED if apply else SUGGESTION_DISMISSED
    idea.save(update_fields=["similar", "updated_at"])


def _apply_similar(idea: Idea, entry: dict) -> None:
    if entry["kind"] == KIND_PROJECT:
        project = Project.objects.filter(pk=entry["id"], owner=idea.owner).first()
        if project is None:
            raise ActionNotApplicable("Project no longer exists")
        idea.projects.add(project)
        return
    target = Idea.objects.owned_by(idea.owner).filter(pk=entry["id"]).first()
    if target is None:
        raise ActionNotApplicable("Idea no longer exists")
    Feature.objects.create(idea=target, text=idea.display_title[:300])
