from django.test import SimpleTestCase

from ai.analysis import MAX_SUGGESTIONS, MAX_TAGS, IdeaAnalyzer
from ai.client import LLMClient
from ai.errors import AIResponseError


class CannedClient(LLMClient):
    name = "canned"

    def __init__(self, answer):
        self.answer = answer
        self.user_messages = []

    def complete_json(self, system, user):
        self.user_messages.append(user)
        return self.answer


def analyze(answer, text="an idea", existing=()):
    return IdeaAnalyzer(CannedClient(answer)).analyze(text, existing)


class IdeaAnalyzerTests(SimpleTestCase):
    def test_well_formed_answer_is_returned(self):
        insights = analyze(
            {"title": " Habit app ", "summary": "Tracks habits.", "tags": ["health"], "suggested_features": ["Streaks"]}
        )

        self.assertEqual(insights.title, "Habit app")
        self.assertEqual(insights.summary, "Tracks habits.")
        self.assertEqual(insights.tags, ["health"])
        self.assertEqual(insights.suggested_features, ["Streaks"])

    def test_missing_title_is_a_response_error(self):
        with self.assertRaises(AIResponseError):
            analyze({"summary": "no title here"})

    def test_tags_are_normalized_deduplicated_and_capped(self):
        raw_tags = ["#Health", "health", " Mobile ", 42, "", "a", "b", "c", "d"]

        insights = analyze({"title": "T", "tags": raw_tags})

        self.assertEqual(insights.tags[:2], ["health", "mobile"])
        self.assertEqual(len(insights.tags), MAX_TAGS)

    def test_suggestions_exclude_existing_features_and_are_capped(self):
        suggested = ["Login", "login ", "Streaks"] + [f"extra {n}" for n in range(10)]

        insights = analyze({"title": "T", "suggested_features": suggested}, existing=["LOGIN"])

        self.assertNotIn("Login", insights.suggested_features)
        self.assertEqual(insights.suggested_features[0], "Streaks")
        self.assertEqual(len(insights.suggested_features), MAX_SUGGESTIONS)

    def test_wrong_types_degrade_to_empty_lists_instead_of_crashing(self):
        insights = analyze({"title": "T", "tags": "not a list", "suggested_features": {"a": 1}, "summary": 5})

        self.assertEqual((insights.tags, insights.suggested_features, insights.summary), ([], [], ""))

    def test_prompt_contains_idea_and_existing_features(self):
        client = CannedClient({"title": "T"})

        IdeaAnalyzer(client).analyze("Build a budget app", ["Login", "Charts"])

        message = client.user_messages[0]
        self.assertIn("Build a budget app", message)
        self.assertIn("- Login", message)
        self.assertIn("- Charts", message)
