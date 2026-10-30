"""Connects the AI brief writer to ideas; a failing AI only means the prompt stays plain."""
import logging

from ai.brief import Brief, BriefWriter
from ai.errors import AIError

from . import ai_registry
from .build_prompt import MODE_EXTEND
from .models import Idea

logger = logging.getLogger(__name__)


def build_writer(owner) -> BriefWriter:
    return BriefWriter(ai_registry.build_client(owner))


def draft_brief(idea: Idea, mode: str, writer_factory=None) -> Brief | None:
    """Asks the AI for a build plan. Returns None when no AI could answer."""
    idea_text = f"{idea.display_title}\n{idea.ai_summary}\n{idea.body}".strip()
    features = [feature.text for feature in idea.features.all() if not feature.is_done]
    try:
        writer = writer_factory() if writer_factory else build_writer(idea.owner)
        return writer.write(idea_text, idea.platform_labels, features, extend_existing=mode == MODE_EXTEND)
    except AIError as error:
        logger.warning("AI brief failed for idea %s: %s", idea.pk, error)
        return None
