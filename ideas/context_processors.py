from .models import Idea, Project

IDEA_VIEWS = {"list", "detail", "create", "update", "delete", "feature-copy"}
CHAT_VIEWS = {"chat", "idea-chat", "project-chat", "conversation"}


def navigation(request):
    """Which sidebar/tab section is active, plus the counts shown next to its entries."""
    if not request.user.is_authenticated:
        return {}
    name = request.resolver_match.url_name if request.resolver_match else ""
    return {
        "nav_section": _section(name),
        "nav_idea_count": Idea.objects.owned_by(request.user).count(),
        "nav_project_count": Project.objects.filter(owner=request.user).count(),
    }


def _section(url_name: str) -> str:
    if url_name in CHAT_VIEWS:
        return "chat"
    if url_name.startswith("project-"):
        return "projects"
    if url_name == "settings" or url_name.startswith("ai-model"):
        return "settings"
    return "ideas" if url_name in IDEA_VIEWS else ""
