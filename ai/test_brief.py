from django.test import SimpleTestCase

from ai.brief import MAX_ITEMS, BriefWriter
from ai.client import LLMClient
from ai.errors import AIResponseError


class CannedClient(LLMClient):
    name = "canned"

    def __init__(self, answer):
        self.answer = answer
        self.last_user = ""

    def chat_json(self, system, messages):
        self.last_user = messages[-1]["content"]
        return self.answer


def write(answer, extend=False, features=("Login",), platforms=("PWA",)):
    client = CannedClient(answer)
    return BriefWriter(client).write("Water reminder", platforms, features, extend), client


class BriefWriterTests(SimpleTestCase):
    def test_full_answer_is_parsed_and_trimmed(self):
        brief, _ = write({"mvp": [" Giriş "], "stack": " Django + PWA ", "phases": ["1. temel"], "risks": ["iOS bildirimleri"]})

        self.assertEqual((brief.mvp, brief.stack, brief.phases, brief.risks), (["Giriş"], "Django + PWA", ["1. temel"], ["iOS bildirimleri"]))

    def test_wrong_types_and_empty_items_are_dropped_and_lists_capped(self):
        brief, _ = write({"mvp": ["a", "", 5, None] + [f"item {n}" for n in range(20)], "stack": 7, "phases": "nope", "risks": {"a": 1}})

        self.assertEqual(len(brief.mvp), MAX_ITEMS)
        self.assertEqual((brief.stack, brief.phases, brief.risks), ("", [], []))

    def test_an_answer_with_nothing_usable_is_a_response_error(self):
        for answer in ({}, {"mvp": [], "stack": "  "}, {"phases": 3}):
            with self.assertRaises(AIResponseError):
                write(answer)

    def test_prompt_states_mode_platforms_idea_and_open_features(self):
        _, client = write({"mvp": ["x"]}, extend=True, features=("Login", "Charts"), platforms=("PWA", "iOS"))

        for expected in ("MODE: extend", "PWA, iOS", "Water reminder", "- Login", "- Charts"):
            self.assertIn(expected, client.last_user)

    def test_new_mode_is_labelled_new(self):
        _, client = write({"mvp": ["x"]}, extend=False)

        self.assertIn("MODE: new", client.last_user)
