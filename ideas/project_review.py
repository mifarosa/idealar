"""AI review of a project's GitHub repository, stored on the project and applied only on confirmation."""
import logging
from django.utils.translation import gettext as _
import os

from django.utils import timezone

from ai.errors import AIError
from ai.repo_review import RepoReview, RepoReviewer

from . import ai_registry
from .errors import ActionNotApplicable
from .github_repo import (
    DEFAULT_API_URL,
    DEFAULT_MAX_CHARS,
    GitHubClient,
    GitHubError,
    build_snapshot,
    parse_repo_url,
)
from .models import SUGGESTION_APPLIED, SUGGESTION_DISMISSED, SUGGESTION_PENDING, Feature, Project

logger = logging.getLogger(__name__)

REVIEW_PROVIDER = "gemini"  # large context; falls back to the rest of the chain
MAX_ERROR_CHARS = 300


def build_github_client() -> GitHubClient:
    return GitHubClient(api_url=os.environ.get("GITHUB_API_URL", DEFAULT_API_URL), token=os.environ.get("GITHUB_TOKEN", ""))


def build_reviewer(owner) -> RepoReviewer:
    return RepoReviewer(ai_registry.build_client(owner, preferred=REVIEW_PROVIDER))


def _max_chars() -> int:
    raw = os.environ.get("REPO_ANALYSIS_MAX_CHARS", "")
    return int(raw) if raw.isdigit() else DEFAULT_MAX_CHARS


def _checklist(project: Project) -> list[Feature]:
    return list(Feature.objects.filter(idea__projects=project, idea__owner=project.owner).order_by("id"))


def _stored_analysis(review: RepoReview, files_read: list[str], checklist: list[Feature]) -> dict:
    states = {feature.pk: feature for feature in checklist}
    return {
        "summary": review.summary,
        "tech": review.tech,
        "implemented": review.implemented,
        "gaps": review.gaps,
        "files_read": files_read,
        "matches": [
            {
                "feature_id": m.feature_id,
                "text": states[m.feature_id].text,
                "status": m.status,
                "evidence": m.evidence,
                "already_done": states[m.feature_id].is_done,
                "decision": SUGGESTION_PENDING,
            }
            for m in review.feature_matches
        ],
    }


def _record_failure(project: Project, message: str) -> None:
    project.repo_analysis_error = message[:MAX_ERROR_CHARS]
    project.save(update_fields=["repo_analysis_error"])


def review_project(project: Project, github_factory=None, reviewer_factory=None) -> bool:
    """Reads the repo and reviews it. On failure the previous review is kept and the error is recorded."""
    try:
        ref = parse_repo_url(project.github_url)
        snapshot = build_snapshot((github_factory or build_github_client)(), ref, _max_chars())
        reviewer = reviewer_factory() if reviewer_factory else build_reviewer(project.owner)
        checklist = _checklist(project)
        review = reviewer.review(snapshot.text, [(f.pk, f.text) for f in checklist])
    except GitHubError as error:
        _record_failure(project, str(error))
        return False
    except AIError as error:
        logger.warning("AI repo review failed for project %s: %s", project.pk, error)
        _record_failure(project, _("AI şu an yanıt veremedi, biraz sonra tekrar dene."))
        return False
    run = reviewer.last_run
    project.repo_analysis = _stored_analysis(review, snapshot.files_read, checklist)
    project.repo_analyzed_at = timezone.now()
    project.repo_analysis_error = ""
    project.repo_analysis_provider = ai_registry.label_for(run.served_by)[:30] if run else ""
    project.save(update_fields=["repo_analysis", "repo_analyzed_at", "repo_analysis_error", "repo_analysis_provider"])
    return True


def decide_match(project: Project, index: int, apply: bool) -> None:
    """Marks the checklist item done (apply) or ignores the AI's finding; decided findings stay untouched."""
    match = project.repo_analysis["matches"][index]
    if match["decision"] != SUGGESTION_PENDING:
        return
    if apply:
        feature = Feature.objects.filter(
            pk=match["feature_id"], idea__projects=project, idea__owner=project.owner
        ).first()
        if feature is None:
            raise ActionNotApplicable("Feature is no longer part of this project")
        feature.is_done = True
        feature.save(update_fields=["is_done"])
    match["decision"] = SUGGESTION_APPLIED if apply else SUGGESTION_DISMISSED
    project.save(update_fields=["repo_analysis"])
