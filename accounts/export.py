"""Everything the app stores about a user, as plain data (for "download my data"). Secrets are never included."""
from django.utils import timezone


def _iso(value):
    return value.isoformat() if value else None


def export_user_data(user) -> dict:
    ideas = user.ideas.prefetch_related("features", "projects")
    return {
        "exported_at": _iso(timezone.now()),
        "account": {"username": user.get_username(), "email": user.email, "first_name": user.first_name, "joined": _iso(user.date_joined)},
        "ideas": [
            {
                "title": idea.title,
                "ai_title": idea.ai_title,
                "text": idea.body,
                "ai_summary": idea.ai_summary,
                "tags": idea.ai_tags,
                "platforms": idea.platforms,
                "projects": [project.name for project in idea.projects.all()],
                "features": [{"text": f.text, "platform": f.platform, "done": f.is_done} for f in idea.features.all()],
                "created": _iso(idea.created_at),
            }
            for idea in ideas
        ],
        "projects": [
            {"name": p.name, "description": p.description, "github_url": p.github_url, "created": _iso(p.created_at)}
            for p in user.projects.all()
        ],
        "conversations": [
            {
                "title": c.title,
                "idea": c.idea.display_title if c.idea else None,
                "project": c.project.name if c.project else None,
                "messages": [{"role": m.role, "text": m.content, "time": _iso(m.created_at)} for m in c.messages.all()],
            }
            for c in user.conversations.select_related("idea", "project").prefetch_related("messages")
        ],
        "kanban": [
            {"title": t.idea.display_title if t.mirrors_idea and t.idea else t.title, "column": t.status,
             "board": t.project.name if t.project else "personal"}
            for t in user.tasks.select_related("idea", "project")
        ],
        "tickets": [
            {
                "kind": t.kind, "title": t.title, "text": t.body, "status": t.status, "created": _iso(t.created_at),
                "replies": [{"from_support": m.from_admin, "text": m.body, "time": _iso(m.created_at)} for m in t.messages.all()],
            }
            for t in user.tickets.prefetch_related("messages")
        ],
        # Only which models were set up; the API keys are sealed and are never exported.
        "ai_models": [{"label": m.label, "kind": m.kind, "model": m.model_name, "enabled": m.enabled} for m in user.ai_models.all()],
    }
