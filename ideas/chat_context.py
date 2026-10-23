"""Describes what the AI may see in a conversation, and which ideas it may touch."""
from dataclasses import dataclass

from .models import ChatMessage, Idea, Project

MAX_CONTEXT_CHARS = 6000
MAX_GENERAL_IDEAS = 60
MAX_BODY_CHARS = 800


@dataclass(frozen=True)
class ChatScope:
    owner: object
    idea: Idea | None = None
    project: Project | None = None

    @property
    def kind(self) -> str:
        if self.idea:
            return "idea"
        return "project" if self.project else "general"

    @property
    def title(self) -> str:
        if self.idea:
            return self.idea.display_title
        return self.project.name if self.project else "Genel sohbet"

    def messages(self):
        return ChatMessage.objects.filter(owner=self.owner, idea=self.idea, project=self.project)

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
    elif scope.kind == "project":
        text = _describe_project(scope.project, ideas)
    else:
        text = "The developer's ideas:\n" + "\n".join(_describe_idea(idea, detailed=False) for idea in ideas)
    return text[:MAX_CONTEXT_CHARS]


def _describe_project(project: Project, ideas: list[Idea]) -> str:
    header = f"Project: {project.name}\n{project.description.strip()}".strip()
    if not ideas:
        return f"{header}\n(No ideas are linked to this project yet.)"
    return f"{header}\nIdeas in this project:\n" + "\n".join(_describe_idea(idea, detailed=True) for idea in ideas)


def _describe_idea(idea: Idea, detailed: bool) -> str:
    line = f"[id={idea.pk}] {idea.display_title}"
    if not detailed:
        summary = _one_line_summary(idea)
        return f"{line} — {summary}" if summary else line
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
