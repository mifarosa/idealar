"""Describes what the AI may see in a conversation, and which ideas it may touch."""
from dataclasses import dataclass
from django.utils.translation import gettext as _

from .models import Conversation, Idea, Project

MAX_CONTEXT_CHARS = 16000
MAX_GENERAL_IDEAS = 120
MAX_PROJECTS = 40
MAX_LINKABLE_IDEAS = 60
MAX_BODY_CHARS = 800


@dataclass(frozen=True)
class ChatScope:
    owner: object
    idea: Idea | None = None
    project: Project | None = None

    @classmethod
    def of(cls, conversation: Conversation) -> "ChatScope":
        return cls(conversation.owner, conversation.idea, conversation.project)

    @property
    def kind(self) -> str:
        if self.idea:
            return "idea"
        return "project" if self.project else "general"

    @property
    def title(self) -> str:
        if self.idea:
            return self.idea.display_title
        return self.project.name if self.project else _("Genel sohbet")

    def conversations(self):
        return Conversation.objects.filter(owner=self.owner, idea=self.idea, project=self.project)

    def visible_ideas(self):
        """The ideas the AI is told about and may add features to."""
        if self.idea:
            return Idea.objects.filter(pk=self.idea.pk)
        if self.project:
            return self.project.ideas.owned_by(self.owner)
        return Idea.objects.owned_by(self.owner)


def build_context(scope: ChatScope) -> str:
    ideas = list(scope.visible_ideas().prefetch_related("features", "projects")[:MAX_GENERAL_IDEAS])
    if scope.kind == "idea":
        text = _describe_idea(ideas[0], detailed=True)
        extra = _project_list(scope)
    elif scope.kind == "project":
        text = _describe_project(scope.project, ideas)
        extra = _linkable_ideas(scope)
    else:
        text = "The developer's ideas:\n" + "\n".join(_describe_idea(idea, detailed=False) for idea in ideas)
        extra = _project_list(scope)
    # Ids the AI may use in link_project/new_idea go first so a long idea list can never push them out of the limit.
    return (extra + text)[:MAX_CONTEXT_CHARS]


def _project_list(scope: ChatScope) -> str:
    projects = Project.objects.filter(owner=scope.owner)[:MAX_PROJECTS]
    lines = [f"[project id={p.pk}] {p.name}" + (f" — {_first_line(p.description)}" if p.description.strip() else "") for p in projects]
    return "The developer's projects (an idea can be linked to one):\n" + ("\n".join(lines) if lines else "(none yet)") + "\n\n"


def _linkable_ideas(scope: ChatScope) -> str:
    """Ideas that are not in this project yet, so the AI can propose linking them."""
    linked = scope.project.ideas.values_list("pk", flat=True)
    others = Idea.objects.owned_by(scope.owner).exclude(pk__in=linked)[:MAX_LINKABLE_IDEAS]
    lines = [f"[id={idea.pk}] {idea.display_title}" for idea in others]
    if not lines:
        return ""
    return f"Other ideas not in project \"{scope.project.name}\" yet (project id={scope.project.pk}, can be linked):\n" + "\n".join(lines) + "\n\n"


def _first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0][:120] if lines else ""


def _describe_project(project: Project, ideas: list[Idea]) -> str:
    header = f"Project: {project.name}\n{project.description.strip()}".strip()
    if not ideas:
        return f"{header}\n(No ideas are linked to this project yet.)"
    return f"{header}\nIdeas in this project:\n" + "\n".join(_describe_idea(idea, detailed=True) for idea in ideas)


def _describe_idea(idea: Idea, detailed: bool) -> str:
    line = f"[id={idea.pk}] {idea.display_title}"
    if not detailed:
        summary = _one_line_summary(idea)
        line = f"{line} — {summary}" if summary else line
        names = ", ".join(project.name for project in idea.projects.all())
        return f"{line} (in project: {names})" if names else line
    lines = [line, f"  note: {idea.body.strip()[:MAX_BODY_CHARS]}"]
    if idea.platform_labels:
        lines.append(f"  platforms: {', '.join(idea.platform_labels)}")
    features = idea.features.all()
    if features:
        lines.append("  features: " + "; ".join(f"[{'x' if f.is_done else ' '}] {f.text}" for f in features))
    else:
        lines.append("  features: (none yet)")
    return "\n".join(lines)


def _one_line_summary(idea: Idea) -> str:
    if idea.ai_summary:
        return idea.ai_summary
    lines = idea.body.strip().splitlines()
    return lines[0] if lines else ""
