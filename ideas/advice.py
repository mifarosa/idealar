"""Connects the note advisor to ideas: gathers the whole notebook, stores the advice, applies accepted items."""
import logging

from ai.advice import (
    KIND_BORROW,
    KIND_MERGE,
    KIND_NEW_IDEA,
    KIND_PROJECT,
    KIND_RELATED,
    KIND_TAG,
    MAX_TAG_CHARS,
    Note,
    NoteAdvisor,
    ProjectRef,
)
from ai.errors import AIError

from . import ai_registry
from .errors import ActionNotApplicable
from .models import SUGGESTION_APPLIED, SUGGESTION_DISMISSED, SUGGESTION_PENDING, Feature, Idea, Project

logger = logging.getLogger(__name__)

ADVICE_DONE, ADVICE_FAILED = "done", "failed"
MAX_TAGS_PER_IDEA = 8
INFO_KINDS = {KIND_RELATED, KIND_MERGE}  # nothing to apply: the user opens the other note and decides


def build_advisor(owner) -> NoteAdvisor:
    return NoteAdvisor(ai_registry.build_client(owner))


def _note_text(idea: Idea) -> str:
    return idea.ai_summary or idea.body


def _notebook(idea: Idea) -> tuple[list[Note], list[ProjectRef], list[str]]:
    others = (
        Idea.objects.owned_by(idea.owner).exclude(pk=idea.pk).prefetch_related("projects", "features").order_by("-created_at", "-id")
    )
    notes = [
        Note(
            id=other.pk,
            title=other.display_title,
            text=_note_text(other),
            tags=tuple(other.ai_tags),
            projects=tuple(project.name for project in other.projects.all()),
            open_features=tuple(f.text for f in other.features.all() if not f.is_done),
        )
        for other in others
    ]
    projects = [ProjectRef(p.pk, p.name, p.description) for p in Project.objects.filter(owner=idea.owner)]
    tags = sorted({tag for note in notes for tag in note.tags}, key=str.lower)
    return notes, projects, tags


def advise_idea(idea: Idea, advisor_factory=None) -> bool:
    """Reads the whole notebook and stores advice on the idea. A failure keeps the previous advice."""
    notes, projects, tags = _notebook(idea)
    note_titles = {note.id: note.title for note in notes}
    project_names = {project.id: project.name for project in projects}
    try:
        advisor = advisor_factory() if advisor_factory else build_advisor(idea.owner)
        advice = advisor.advise(f"{idea.display_title}\n{idea.body}".strip(), notes, projects, tags)
    except AIError as error:
        logger.warning("AI advice failed for idea %s: %s", idea.pk, error)
        idea.advice_status = ADVICE_FAILED
        idea.save(update_fields=["advice_status", "updated_at"])
        return False
    idea.advice = [_entry(item, note_titles, project_names) for item in advice.items]
    idea.advice_status = ADVICE_DONE
    idea.save(update_fields=["advice", "advice_status", "updated_at"])
    return True


def _entry(item, note_titles: dict[int, str], project_names: dict[int, str]) -> dict:
    names = project_names if item.kind == KIND_PROJECT else note_titles
    return {
        "kind": item.kind,
        "text": item.text,
        "target": item.target,
        "target_title": names.get(item.target, ""),
        "reason": item.reason,
        "status": SUGGESTION_PENDING,
    }


def decide_advice(idea: Idea, index: int, apply: bool) -> None:
    """Applies (or dismisses) one advice card. Applying never touches anything the user did not confirm."""
    entry = idea.advice[index]
    if entry["status"] != SUGGESTION_PENDING:
        return
    if apply:
        _apply(idea, entry)
    entry["status"] = SUGGESTION_APPLIED if apply else SUGGESTION_DISMISSED
    idea.save(update_fields=["advice", "updated_at"])


def _apply(idea: Idea, entry: dict) -> None:
    kind = entry["kind"]
    if kind in INFO_KINDS:
        return
    if kind == KIND_BORROW:
        Feature.objects.create(idea=idea, text=entry["text"][:300])
    elif kind == KIND_PROJECT:
        project = Project.objects.filter(pk=entry["target"], owner=idea.owner).first()
        if project is None:
            raise ActionNotApplicable("Project no longer exists")
        idea.projects.add(project)
    elif kind == KIND_TAG:
        tag = entry["text"][:MAX_TAG_CHARS]
        if tag.lower() not in {existing.lower() for existing in idea.ai_tags} and len(idea.ai_tags) < MAX_TAGS_PER_IDEA:
            idea.ai_tags = [*idea.ai_tags, tag]
            idea.save(update_fields=["ai_tags", "updated_at"])
    elif kind == KIND_NEW_IDEA:
        Idea.objects.create(owner=idea.owner, body=entry["text"])
