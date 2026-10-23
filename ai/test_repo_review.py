from django.test import SimpleTestCase

from ai.client import LLMClient
from ai.errors import AIResponseError
from ai.repo_review import RepoReviewer


class CannedClient(LLMClient):
    name = "canned"

    def __init__(self, answer):
        self.answer = answer
        self.last_user = ""

    def chat_json(self, system, messages):
        self.last_user = messages[-1]["content"]
        return self.answer


def review(answer, features=((1, "Login"), (2, "Charts"))):
    client = CannedClient(answer)
    return RepoReviewer(client).review("README: hello", features), client


class RepoReviewerTests(SimpleTestCase):
    def test_full_answer_is_parsed(self):
        result, _ = review(
            {
                "summary": " A habit tracker. ",
                "tech": ["Django", "SQLite"],
                "implemented": ["Login (auth/views.py)"],
                "gaps": ["No tests"],
                "feature_matches": [{"feature_id": 1, "status": "done", "evidence": "auth/views.py"}],
            }
        )

        self.assertEqual(result.summary, "A habit tracker.")
        self.assertEqual((result.tech, result.implemented, result.gaps), (["Django", "SQLite"], ["Login (auth/views.py)"], ["No tests"]))
        self.assertEqual([(m.feature_id, m.status) for m in result.feature_matches], [(1, "done")])

    def test_missing_summary_is_a_response_error(self):
        with self.assertRaises(AIResponseError):
            review({"tech": ["x"]})

    def test_invented_feature_ids_and_bad_statuses_are_dropped(self):
        result, _ = review(
            {
                "summary": "s",
                "feature_matches": [
                    {"feature_id": 99, "status": "done", "evidence": "x"},
                    {"feature_id": 2, "status": "finished", "evidence": "x"},
                    {"feature_id": "2", "status": "partial", "evidence": "x"},
                    {"feature_id": True, "status": "done"},
                    {"feature_id": 2, "status": "done", "evidence": "duplicate of id 2"},
                ],
            }
        )

        self.assertEqual([(m.feature_id, m.status) for m in result.feature_matches], [(2, "partial")])

    def test_wrong_types_degrade_to_empty_lists(self):
        result, _ = review({"summary": "s", "tech": "python", "implemented": {"a": 1}, "gaps": None, "feature_matches": "x"})

        self.assertEqual((result.tech, result.implemented, result.gaps, result.feature_matches), ([], [], [], []))

    def test_lists_are_capped(self):
        result, _ = review({"summary": "s", "implemented": [f"item {n}" for n in range(40)]})

        self.assertEqual(len(result.implemented), 12)

    def test_prompt_contains_snapshot_and_checklist_with_ids(self):
        _, client = review({"summary": "s"})

        for expected in ("README: hello", "[1] Login", "[2] Charts"):
            self.assertIn(expected, client.last_user)

    def test_last_run_is_none_for_a_plain_client(self):
        self.assertIsNone(RepoReviewer(CannedClient({})).last_run)
