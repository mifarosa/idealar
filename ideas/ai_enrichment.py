"""Connects the AI layer to Idea records. AI failures never lose the idea; they only mark it."""
import logging

from ai.analysis import IdeaAnalyzer
from ai.errors import AIError

from . import ai_registry
from .models import AI_DONE, AI_FAILED, Idea

logger = logging.getLogger(__name__)


def build_analyzer(owner) -> IdeaAnalyzer:
    return IdeaAnalyzer(ai_registry.build_client(owner))


def _idea_text(idea: Idea) -> str:
    return f"{idea.title}\n{idea.body}".strip()


def enrich_idea(idea: Idea, analyzer: IdeaAnalyzer) -> bool:
    """Fills the AI fields. Returns True on success; on failure marks the idea and returns False."""
    existing_features = list(idea.features.values_list("text", flat=True))
    try:
        insights = analyzer.analyze(_idea_text(idea), existing_features)
    except AIError as error:
        logger.warning("AI enrichment failed for idea %s: %s", idea.pk, error)
        _save_ai_fields(idea, ai_status=AI_FAILED)
        return False
    _save_ai_fields(
        idea,
        ai_title=insights.title,
        ai_summary=insights.summary,
        ai_tags=insights.tags,
        suggested_features=insights.suggested_features,
        ai_status=AI_DONE,
    )
    return True


def _save_ai_fields(idea: Idea, **fields) -> None:
    for name, value in fields.items():
        setattr(idea, name, value)
    idea.save(update_fields=[*fields, "updated_at"])
