from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ai.errors import AIProviderError, AllProvidersFailed
from ai.repo_review import FeatureMatch, RepoReview, RepoReviewer
from ideas import project_review
from ideas.errors import ActionNotApplicable
from ideas.forms import ProjectForm
from ideas.github_repo import GitHubClient
from ideas.models import SUGGESTION_APPLIED, SUGGESTION_DISMISSED, SUGGESTION_PENDING, Feature, Idea, Project
from ideas.test_github_repo import FakeGitHub, repo_routes

REPO_URL = "https://github.com/octo/habits"


def make_user(name="owner"):
    return get_user_model().objects.create_user(name, password="pw-for-tests-123")


class StubReviewer(RepoReviewer):
    def __init__(self, review=None, error=None):
        self._client = None  # no real client behind this stub
        self._review, self._error, self.calls = review, error, []

    def review(self, snapshot, features=()):
        self.calls.append((snapshot, list(features)))
        if self._error:
            raise self._error
        return self._review


class ReviewProjectTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.project = Project.objects.create(owner=self.user, name="Habits", github_url=REPO_URL)
        idea = Idea.objects.create(owner=self.user, body="habit app")
        idea.projects.add(self.project)
        self.login = Feature.objects.create(idea=idea, text="Login")
        self.charts = Feature.objects.create(idea=idea, text="Charts", is_done=True)
        self.server = FakeGitHub(repo_routes())
        self.addCleanup(self.server.close)

    def github(self):
        return GitHubClient(api_url=self.server.url, timeout=5)

    def run_review(self, reviewer):
        return project_review.review_project(self.project, lambda: self.github(), lambda: reviewer)

    def good_review(self):
        return RepoReview(
            summary="A habit tracker in Django.",
            tech=["Django"],
            implemented=["Login (app/views.py)"],
            gaps=["No tests"],
            feature_matches=[FeatureMatch(self.login.pk, "done", "app/views.py"), FeatureMatch(self.charts.pk, "done", "templates")],
        )

    def test_success_stores_analysis_matches_and_timestamp(self):
        reviewer = StubReviewer(self.good_review())

        self.assertTrue(self.run_review(reviewer))

        self.project.refresh_from_db()
        analysis = self.project.repo_analysis
        self.assertEqual((analysis["summary"], analysis["tech"], analysis["gaps"]), ("A habit tracker in Django.", ["Django"], ["No tests"]))
        self.assertIn("app/views.py", analysis["files_read"])
        self.assertEqual(
            [(m["text"], m["status"], m["already_done"], m["decision"]) for m in analysis["matches"]],
            [("Login", "done", False, SUGGESTION_PENDING), ("Charts", "done", True, SUGGESTION_PENDING)],
        )
        self.assertIsNotNone(self.project.repo_analyzed_at)
        self.assertEqual(self.project.repo_analysis_error, "")

    def test_reviewer_receives_the_snapshot_and_the_projects_checklist(self):
        reviewer = StubReviewer(self.good_review())

        self.run_review(reviewer)

        snapshot, features = reviewer.calls[0]
        self.assertIn("Track your habits daily.", snapshot)
        self.assertEqual(features, [(self.login.pk, "Login"), (self.charts.pk, "Charts")])

    def test_checklist_excludes_other_projects_and_other_users(self):
        other_project_idea = Idea.objects.create(owner=self.user, body="unlinked")
        Feature.objects.create(idea=other_project_idea, text="Not in this project")
        reviewer = StubReviewer(self.good_review())

        self.run_review(reviewer)

        self.assertEqual([text for _, text in reviewer.calls[0][1]], ["Login", "Charts"])

    def test_github_failure_is_recorded_and_the_previous_review_is_kept(self):
        self.run_review(StubReviewer(self.good_review()))
        self.server.routes.clear()  # every GitHub call now answers 404

        self.assertFalse(self.run_review(StubReviewer(self.good_review())))

        self.project.refresh_from_db()
        self.assertIn("Depo bulunamadı", self.project.repo_analysis_error)
        self.assertEqual(self.project.repo_analysis["summary"], "A habit tracker in Django.")

    def test_ai_failure_is_recorded_with_a_friendly_message(self):
        reviewer = StubReviewer(error=AllProvidersFailed([("gemini", AIProviderError("down"))]))

        with self.assertLogs("ideas.project_review", level="WARNING"):
            self.assertFalse(self.run_review(reviewer))

        self.project.refresh_from_db()
        self.assertIn("AI şu an yanıt veremedi", self.project.repo_analysis_error)

    def test_invalid_url_is_recorded_not_raised(self):
        self.project.github_url = "https://gitlab.com/a/b"

        self.assertFalse(self.run_review(StubReviewer(self.good_review())))

        self.project.refresh_from_db()
        self.assertIn("github.com", self.project.repo_analysis_error)

    def test_reviewer_factory_errors_are_handled(self):
        def broken_factory():
            raise AllProvidersFailed([])

        with self.assertLogs("ideas.project_review", level="WARNING"):
            self.assertFalse(project_review.review_project(self.project, lambda: self.github(), broken_factory))

    def test_gemini_is_the_preferred_reviewer(self):
        with patch("ideas.project_review.build_default_client") as build:
            project_review.build_reviewer()

        build.assert_called_once_with(preferred="gemini")


class DecideMatchTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.project = Project.objects.create(owner=self.user, name="Habits", github_url=REPO_URL)
        self.idea = Idea.objects.create(owner=self.user, body="x")
        self.idea.projects.add(self.project)
        self.feature = Feature.objects.create(idea=self.idea, text="Login")
        self.project.repo_analysis = {"matches": [{"feature_id": self.feature.pk, "text": "Login", "status": "done", "evidence": "e", "already_done": False, "decision": SUGGESTION_PENDING}]}
        self.project.save()

    def test_apply_marks_the_feature_done(self):
        project_review.decide_match(self.project, 0, apply=True)

        self.feature.refresh_from_db()
        self.assertTrue(self.feature.is_done)
        self.assertEqual(self.project.repo_analysis["matches"][0]["decision"], SUGGESTION_APPLIED)

    def test_dismiss_leaves_the_feature_alone(self):
        project_review.decide_match(self.project, 0, apply=False)

        self.feature.refresh_from_db()
        self.assertFalse(self.feature.is_done)
        self.assertEqual(self.project.repo_analysis["matches"][0]["decision"], SUGGESTION_DISMISSED)

    def test_a_decided_match_is_not_applied_again(self):
        project_review.decide_match(self.project, 0, apply=False)
        project_review.decide_match(self.project, 0, apply=True)

        self.feature.refresh_from_db()
        self.assertFalse(self.feature.is_done)

    def test_feature_that_left_the_project_cannot_be_marked(self):
        self.idea.projects.remove(self.project)

        with self.assertRaises(ActionNotApplicable):
            project_review.decide_match(self.project, 0, apply=True)

        self.feature.refresh_from_db()
        self.assertFalse(self.feature.is_done)


class ProjectReviewViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.project = Project.objects.create(owner=self.user, name="Habits", github_url=REPO_URL)
        idea = Idea.objects.create(owner=self.user, body="x")
        idea.projects.add(self.project)
        self.feature = Feature.objects.create(idea=idea, text="Login")
        self.server = FakeGitHub(repo_routes())
        self.addCleanup(self.server.close)
        review = RepoReview("Looks like a habit tracker.", ["Django"], ["Login works"], ["No tests"], [FeatureMatch(self.feature.pk, "done", "views.py")])
        for target, value in (("build_github_client", GitHubClient(api_url=self.server.url, timeout=5)), ("build_reviewer", StubReviewer(review))):
            patcher = patch(f"ideas.project_review.{target}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_inspect_button_runs_the_review_and_the_page_shows_the_result(self):
        response = self.client.post(reverse("ideas:project-inspect", args=[self.project.pk]), follow=True)

        self.assertContains(response, "Proje incelendi")
        self.assertContains(response, "Looks like a habit tracker.")
        self.assertContains(response, "Login works")
        self.assertContains(response, "No tests")
        self.assertContains(response, "Yapıldı olarak işaretle")

    def test_mark_done_button_checks_the_feature(self):
        self.client.post(reverse("ideas:project-inspect", args=[self.project.pk]))

        self.client.post(reverse("ideas:project-match-decide", args=[self.project.pk, 0]), {"decision": "apply"})

        self.feature.refresh_from_db()
        self.assertTrue(self.feature.is_done)

    def test_inspecting_without_a_github_url_explains_what_to_do(self):
        self.project.github_url = ""
        self.project.save()

        response = self.client.post(reverse("ideas:project-inspect", args=[self.project.pk]), follow=True)

        self.assertContains(response, "GitHub adresi ekle")

    def test_failed_review_shows_the_error_on_the_page(self):
        self.server.routes.clear()

        response = self.client.post(reverse("ideas:project-inspect", args=[self.project.pk]), follow=True)

        self.assertContains(response, "Depo bulunamadı")

    def test_page_without_url_offers_to_add_one(self):
        self.project.github_url = ""
        self.project.save()

        self.assertContains(self.client.get(reverse("ideas:project-detail", args=[self.project.pk])), "Adres ekle")

    def test_out_of_range_match_index_is_ignored(self):
        response = self.client.post(reverse("ideas:project-match-decide", args=[self.project.pk, 5]), {"decision": "apply"})

        self.assertEqual(response.status_code, 302)

    def test_other_users_cannot_inspect_or_decide(self):
        self.client.force_login(make_user("intruder"))

        self.assertEqual(self.client.post(reverse("ideas:project-inspect", args=[self.project.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("ideas:project-match-decide", args=[self.project.pk, 0])).status_code, 404)


class ProjectFormGithubUrlTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def form(self, url):
        return ProjectForm({"name": "P", "description": "", "github_url": url}, user=self.user)

    def test_valid_and_empty_urls_are_accepted(self):
        self.assertTrue(self.form(REPO_URL).is_valid())
        self.assertTrue(self.form("").is_valid())

    def test_other_hosts_and_deep_links_are_rejected(self):
        for url in ("https://gitlab.com/a/b", "https://github.com/a/b/issues/1", "https://evil.io/github.com/a/b"):
            form = self.form(url)
            self.assertFalse(form.is_valid(), url)
            self.assertIn("github_url", form.errors)
