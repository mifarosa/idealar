from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from ai.analysis import IdeaAnalyzer, IdeaInsights
from ai.client import LLMClient
from ai.similarity import SimilarityJudge
from ai.errors import AIProviderError, AllProvidersFailed
from ideas import ai_enrichment
from ideas.models import AI_DONE, AI_FAILED, AI_PENDING, Feature, Idea

INSIGHTS = IdeaInsights(
    title="Habit tracker",
    summary="Tracks daily habits.",
    tags=["health", "mobile"],
    suggested_features=["Streak counter", "Reminders"],
)


class StubAnalyzer(IdeaAnalyzer):
    def __init__(self, insights=INSIGHTS, error=None):
        self._insights, self._error = insights, error
        self.calls = []

    def analyze(self, idea_text, existing_features=()):
        self.calls.append((idea_text, list(existing_features)))
        if self._error:
            raise self._error
        return self._insights


class _NoMatchClient(LLMClient):
    name = "no-match"

    def chat_json(self, system, messages):
        return {"matches": []}


def failing_analyzer():
    return StubAnalyzer(error=AllProvidersFailed([("groq", AIProviderError("down"))]))


def make_user(name="owner"):
    return get_user_model().objects.create_user(name, password="pw-for-tests-123")


class EnrichIdeaTests(TestCase):
    def setUp(self):
        self.idea = Idea.objects.create(owner=make_user(), body="track my habits")

    def test_new_idea_awaits_ai(self):
        self.assertEqual(self.idea.ai_status, AI_PENDING)

    def test_success_fills_all_ai_fields(self):
        self.assertTrue(ai_enrichment.enrich_idea(self.idea, StubAnalyzer()))

        self.idea.refresh_from_db()
        self.assertEqual(
            (self.idea.ai_title, self.idea.ai_summary, self.idea.ai_tags, self.idea.suggested_features, self.idea.ai_status),
            ("Habit tracker", "Tracks daily habits.", ["health", "mobile"], ["Streak counter", "Reminders"], AI_DONE),
        )
        self.assertEqual(self.idea.display_title, "Habit tracker")

    def test_failure_keeps_the_idea_and_marks_it_failed(self):
        with self.assertLogs("ideas.ai_enrichment", level="WARNING"):
            succeeded = ai_enrichment.enrich_idea(self.idea, failing_analyzer())

        self.idea.refresh_from_db()
        self.assertFalse(succeeded)
        self.assertEqual((self.idea.ai_status, self.idea.body, self.idea.ai_title), (AI_FAILED, "track my habits", ""))

    def test_own_title_wins_over_ai_title(self):
        self.idea.title = "My name for it"
        ai_enrichment.enrich_idea(self.idea, StubAnalyzer())

        self.assertEqual(self.idea.display_title, "My name for it")

    def test_existing_features_are_passed_to_the_analyzer(self):
        Feature.objects.create(idea=self.idea, text="Login")
        analyzer = StubAnalyzer()

        ai_enrichment.enrich_idea(self.idea, analyzer)

        self.assertEqual(analyzer.calls[0][1], ["Login"])

    def test_rerun_after_failure_can_succeed(self):
        with self.assertLogs("ideas.ai_enrichment", level="WARNING"):
            ai_enrichment.enrich_idea(self.idea, failing_analyzer())
        ai_enrichment.enrich_idea(self.idea, StubAnalyzer())

        self.idea.refresh_from_db()
        self.assertEqual(self.idea.ai_status, AI_DONE)


class EnrichViewTests(TestCase):
    def setUp(self):
        judge_patcher = patch("ideas.similarity.build_judge", return_value=SimilarityJudge(_NoMatchClient()))
        judge_patcher.start()
        self.addCleanup(judge_patcher.stop)
        self.user = make_user()
        self.client.force_login(self.user)
        self.idea = Idea.objects.create(owner=self.user, body="track my habits")
        self.url = reverse("ideas:idea-enrich", args=[self.idea.pk])

    def test_quick_capture_redirects_to_list_with_enrich_marker(self):
        response = self.client.post(reverse("ideas:create"), {"body": "brand new"})

        new_idea = Idea.objects.get(body="brand new")
        self.assertRedirects(response, f"{reverse('ideas:list')}?enrich={new_idea.pk}", fetch_redirect_response=False)

    def test_list_marks_the_new_idea_for_background_enrichment(self):
        response = self.client.get(reverse("ideas:list"), {"enrich": self.idea.pk})

        self.assertContains(response, f'data-enrich-url="{self.url}"')

    def test_list_does_not_re_enrich_an_idea_that_is_done(self):
        ai_enrichment.enrich_idea(self.idea, StubAnalyzer())

        response = self.client.get(reverse("ideas:list"), {"enrich": self.idea.pk})

        self.assertNotContains(response, "data-enrich-url")

    def test_enrich_endpoint_fills_idea(self):
        with patch("ideas.ai_views.ai_enrichment.build_analyzer", return_value=StubAnalyzer()):
            response = self.client.post(self.url)

        self.idea.refresh_from_db()
        self.assertEqual(self.idea.ai_status, AI_DONE)
        self.assertEqual(response.status_code, 302)

    def test_enrich_endpoint_survives_ai_failure_with_a_message(self):
        with patch("ideas.ai_views.ai_enrichment.build_analyzer", return_value=failing_analyzer()):
            with self.assertLogs("ideas.ai_enrichment", level="WARNING"):
                response = self.client.post(self.url, follow=True)

        self.assertContains(response, "AI şu an yanıt veremedi")
        self.assertTrue(Idea.objects.filter(pk=self.idea.pk).exists())

    def test_card_shows_summary_tags_and_suggestions_after_enrichment(self):
        ai_enrichment.enrich_idea(self.idea, StubAnalyzer())

        response = self.client.get(reverse("ideas:list"), {"open": self.idea.pk})

        for expected in ("Tracks daily habits.", "#health", "Streak counter"):
            self.assertContains(response, expected)

    def test_enrich_requires_post_and_ownership(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.force_login(make_user("intruder"))
        self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_ai_title_and_summary_are_searchable(self):
        ai_enrichment.enrich_idea(self.idea, StubAnalyzer())

        response = self.client.get(reverse("ideas:list"), {"q": "daily habits"})

        self.assertEqual(list(response.context["ideas"]), [self.idea])


class SuggestionTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.idea = Idea.objects.create(owner=self.user, body="x", suggested_features=["Streaks", "Reminders"])
        self.url = reverse("ideas:suggestion-resolve", args=[self.idea.pk])

    def test_accept_adds_a_feature_and_removes_the_suggestion(self):
        self.client.post(self.url, {"text": "Streaks", "action": "accept"})

        self.idea.refresh_from_db()
        self.assertEqual(list(self.idea.features.values_list("text", "is_done")), [("Streaks", False)])
        self.assertEqual(self.idea.suggested_features, ["Reminders"])

    def test_dismiss_removes_the_suggestion_without_adding_a_feature(self):
        self.client.post(self.url, {"text": "Streaks", "action": "dismiss"})

        self.idea.refresh_from_db()
        self.assertEqual(self.idea.features.count(), 0)
        self.assertEqual(self.idea.suggested_features, ["Reminders"])

    def test_text_that_was_never_suggested_is_ignored(self):
        self.client.post(self.url, {"text": "Injected", "action": "accept"})

        self.assertEqual(self.idea.features.count(), 0)

    def test_other_users_idea_is_404(self):
        self.client.force_login(make_user("intruder"))

        self.assertEqual(self.client.post(self.url, {"text": "Streaks", "action": "accept"}).status_code, 404)


class EnrichIdeasCommandTests(TestCase):
    def run_command(self, analyzer):
        out = StringIO()
        with patch("ideas.management.commands.enrich_ideas.ai_enrichment.build_analyzer", return_value=analyzer):
            call_command("enrich_ideas", stdout=out)
        return out.getvalue()

    def test_fills_only_ideas_still_awaiting_ai(self):
        owner = make_user()
        waiting = Idea.objects.create(owner=owner, body="waiting")
        done = Idea.objects.create(owner=owner, body="done", ai_status=AI_DONE, ai_title="kept")

        output = self.run_command(StubAnalyzer())

        waiting.refresh_from_db()
        done.refresh_from_db()
        self.assertIn("filled 1 of 1", output)
        self.assertEqual((waiting.ai_status, done.ai_title), (AI_DONE, "kept"))

    def test_reports_failures_without_crashing(self):
        Idea.objects.create(owner=make_user(), body="waiting")

        with self.assertLogs("ideas.ai_enrichment", level="WARNING"):
            output = self.run_command(failing_analyzer())

        self.assertIn("filled 0 of 1", output)
        self.assertEqual(Idea.objects.get().ai_status, AI_FAILED)


class AiModelsCommandTests(TestCase):
    def test_prints_models_and_marks_the_configured_one(self):
        from ai.client import OpenAICompatibleClient
        from ai.fallback import FallbackClient

        class FakeModelsClient(OpenAICompatibleClient):
            def list_models(self):
                return ["other-model", "wanted-model"]

        client = FakeModelsClient("fake", "http://unused/v1", "wanted-model")
        out = StringIO()
        with patch("ideas.management.commands.ai_models.build_default_client", return_value=FallbackClient([client])):
            call_command("ai_models", stdout=out)

        self.assertIn("[fake] configured model: wanted-model", out.getvalue())
        self.assertIn("wanted-model  <- in use", out.getvalue())
        self.assertIn("other-model", out.getvalue())

    def test_reports_listing_failure_instead_of_crashing(self):
        from ai.client import OpenAICompatibleClient
        from ai.fallback import FallbackClient

        class BrokenClient(OpenAICompatibleClient):
            def list_models(self):
                raise AIProviderError("down")

        out = StringIO()
        client = BrokenClient("fake", "http://unused/v1", "m")
        with patch("ideas.management.commands.ai_models.build_default_client", return_value=FallbackClient([client])):
            call_command("ai_models", stdout=out)

        self.assertIn("could not list models: down", out.getvalue())
