"""Advice on a freshly written note, based on ALL the writer's other notes.

The whole notebook is sent in a compact form (one line per note). Only a notebook too large for the budget is
shortened, oldest notes first and note texts before titles, so the model still sees that every note exists.
"""
from collections.abc import Sequence
from dataclasses import dataclass, field

from .client import LLMClient

KIND_RELATED, KIND_MERGE, KIND_BORROW = "related", "merge", "borrow_feature"
KIND_PROJECT, KIND_TAG, KIND_NEW_IDEA = "add_to_project", "tag", "new_idea"
NOTE_TARGET_KINDS = {KIND_RELATED, KIND_MERGE, KIND_BORROW}
KINDS = NOTE_TARGET_KINDS | {KIND_PROJECT, KIND_TAG, KIND_NEW_IDEA}

MAX_PER_KIND = 4
MAX_ITEMS = 14
MAX_TEXT_CHARS = 300
MAX_REASON_CHARS = 300
MAX_TAG_CHARS = 30
MAX_NEW_NOTE_CHARS = 3000
NOTES_BUDGET_CHARS = 120_000
TEXT_CAPS = (500, 250, 120, 60, 0)  # tried in order until the notebook fits the budget
MAX_OPEN_FEATURES = 6

SYSTEM_PROMPT = """You are the thinking partner inside a personal idea notebook. The user just wrote a NEW NOTE.
You can see ALL their other notes, their projects and the tags they already use. Read everything, then give many
concrete, specific suggestions that only make sense because you know the whole notebook. Item kinds:
- "related": an existing note that connects to the new one (explain the connection). target = note id.
- "merge": an existing note that says nearly the same thing, so the two should be merged. target = note id.
- "borrow_feature": a feature that an existing note has (or implies) that would also fit the new note. target = note id
  of the source, text = the feature as a short phrase.
- "add_to_project": one of the listed projects the new note belongs to. target = project id.
- "tag": a short tag for the new note; strongly prefer tags the user already uses. text = the tag.
- "new_idea": a NEW idea that appears when you combine the new note with existing ones, or a gap you notice.
  text = one or two sentences describing it.
Quality rules: be specific and name the notes you mean; skip anything generic ("add a login", "make it mobile");
never repeat the new note back; at most 4 items per kind; return fewer (or none) rather than padding.
Use only ids that appear in the lists. Write in the language of the new note (usually Turkish).
Reply with ONLY JSON:
{"items": [{"kind": "...", "target": <id or null>, "text": "...", "reason": "one sentence why"}]}"""


@dataclass(frozen=True)
class Note:
    id: int
    title: str
    text: str  # summary or body, whichever is more useful
    tags: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    open_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectRef:
    id: int
    name: str
    description: str = ""


@dataclass(frozen=True)
class AdviceItem:
    kind: str
    reason: str
    target: int | None = None
    text: str = ""


@dataclass(frozen=True)
class Advice:
    items: list[AdviceItem] = field(default_factory=list)


class NoteAdvisor:
    def __init__(self, client: LLMClient):
        self._client = client

    @property
    def last_run(self):
        return getattr(self._client, "last_run", None)

    def advise(self, new_note: str, notes: Sequence[Note], projects: Sequence[ProjectRef], known_tags: Sequence[str]) -> Advice:
        message = _user_message(new_note, notes, projects, known_tags)
        answer = self._client.complete_json(SYSTEM_PROMPT, message)
        return Advice(_parse_items(answer, {n.id for n in notes}, {p.id for p in projects}))


def render_notes(notes: Sequence[Note], budget: int = NOTES_BUDGET_CHARS) -> str:
    """One line per note, newest first as given. Shrinks note texts, then drops the oldest, until it fits."""
    for cap in TEXT_CAPS:
        lines = [_note_line(note, cap) for note in notes]
        if sum(len(line) + 1 for line in lines) <= budget:
            return "\n".join(lines)
    kept, used = [], 0
    for note in notes:
        line = _note_line(note, 0)
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept)


def _note_line(note: Note, text_cap: int) -> str:
    parts = [f"[{note.id}] {note.title}"]
    text = " ".join(note.text.split())[:text_cap] if text_cap else ""
    if text and text != note.title:
        parts.append(text)
    if note.tags:
        parts.append("tags: " + ", ".join(note.tags))
    if note.projects:
        parts.append("projects: " + ", ".join(note.projects))
    if note.open_features and text_cap:
        parts.append("open features: " + "; ".join(note.open_features[:MAX_OPEN_FEATURES]))
    return " | ".join(parts)


def _user_message(new_note: str, notes: Sequence[Note], projects: Sequence[ProjectRef], known_tags: Sequence[str]) -> str:
    project_lines = "\n".join(f"[{p.id}] {p.name} — {' '.join(p.description.split())[:160]}" for p in projects) or "(none)"
    return (
        f"NEW NOTE:\n{new_note[:MAX_NEW_NOTE_CHARS]}\n\n"
        f"ALL OTHER NOTES ({len(notes)}):\n{render_notes(notes) or '(none)'}\n\n"
        f"PROJECTS:\n{project_lines}\n\n"
        f"TAGS ALREADY IN USE: {', '.join(known_tags) or '(none)'}"
    )


def _parse_items(answer: dict, note_ids: set[int], project_ids: set[int]) -> list[AdviceItem]:
    raw = answer.get("items")
    per_kind: dict[str, int] = {}
    seen: set[tuple] = set()
    items: list[AdviceItem] = []
    for entry in raw if isinstance(raw, list) else []:
        item = _parse_item(entry, note_ids, project_ids)
        if item is None or per_kind.get(item.kind, 0) >= MAX_PER_KIND:
            continue
        identity = (item.kind, item.target, item.text.lower())
        if identity in seen:
            continue
        seen.add(identity)
        per_kind[item.kind] = per_kind.get(item.kind, 0) + 1
        items.append(item)
    return items[:MAX_ITEMS]


def _parse_item(entry, note_ids: set[int], project_ids: set[int]) -> AdviceItem | None:
    if not isinstance(entry, dict) or entry.get("kind") not in KINDS:
        return None
    kind = entry["kind"]
    target = _as_int(entry.get("target"))
    text = entry["text"].strip() if isinstance(entry.get("text"), str) else ""
    reason = entry["reason"].strip()[:MAX_REASON_CHARS] if isinstance(entry.get("reason"), str) else ""
    if kind in NOTE_TARGET_KINDS and target not in note_ids:
        return None  # the model invented a note
    if kind == KIND_PROJECT and target not in project_ids:
        return None
    if kind in (KIND_BORROW, KIND_TAG, KIND_NEW_IDEA) and not text:
        return None
    if kind == KIND_TAG:
        text = text.lstrip("#").strip()[:MAX_TAG_CHARS]
        if not text:
            return None
    elif kind in (KIND_BORROW, KIND_NEW_IDEA):
        text = text[:MAX_TEXT_CHARS]
    else:
        text = ""
        if not reason:
            return None  # without the reason the card says nothing useful
    return AdviceItem(kind=kind, reason=reason, target=target if kind in NOTE_TARGET_KINDS | {KIND_PROJECT} else None, text=text)


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.strip().isdigit() else None
