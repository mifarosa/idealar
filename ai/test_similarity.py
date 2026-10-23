from django.test import SimpleTestCase

from ai.client import LLMClient
from ai.similarity import MAX_MATCHES, Candidate, SimilarityJudge


class CannedClient(LLMClient):
    name = "canned"

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0
        self.last_user = ""

    def chat_json(self, system, messages):
        self.calls += 1
        self.last_user = messages[-1]["content"]
        return self.answer


CANDIDATES = [
    Candidate("idea", 1, "Water reminder", "Reminds to drink water"),
    Candidate("project", 7, "Health apps", "Collection | ideas: Water reminder"),
    Candidate("idea", 2, "Budget app", "Tracks money"),
]


def judge(answer, candidates=CANDIDATES):
    client = CannedClient(answer)
    return SimilarityJudge(client).judge("Hydration tracker", candidates), client


class SimilarityJudgeTests(SimpleTestCase):
    def test_matches_are_parsed_and_ranked_by_strength(self):
        matches, _ = judge(
            {
                "matches": [
                    {"kind": "project", "id": 7, "verdict": "related", "reason": "same area"},
                    {"kind": "idea", "id": 1, "verdict": "same", "reason": " both remind to drink "},
                ]
            }
        )

        self.assertEqual([(m.kind, m.id, m.verdict) for m in matches], [("idea", 1, "same"), ("project", 7, "related")])
        self.assertEqual(matches[0].reason, "both remind to drink")

    def test_invented_ids_kinds_and_verdicts_are_dropped(self):
        matches, _ = judge(
            {
                "matches": [
                    {"kind": "idea", "id": 999, "verdict": "same", "reason": "x"},
                    {"kind": "idea", "id": 2, "verdict": "identical", "reason": "x"},
                    {"kind": "project", "id": 1, "verdict": "same", "reason": "wrong kind for that id"},
                    {"kind": "idea", "id": "1", "verdict": "similar", "reason": "string id is accepted"},
                    "not a dict",
                ]
            }
        )

        self.assertEqual([(m.kind, m.id) for m in matches], [("idea", 1)])

    def test_duplicates_are_collapsed_and_result_is_capped(self):
        many = [Candidate("idea", n, f"idea {n}", "s") for n in range(20)]
        answer = {"matches": [{"kind": "idea", "id": n, "verdict": "similar", "reason": "r"} for n in range(20)]}
        answer["matches"].append({"kind": "idea", "id": 0, "verdict": "same", "reason": "dup"})

        matches, _ = judge(answer, many)

        self.assertEqual(len(matches), MAX_MATCHES)
        self.assertEqual(len({(m.kind, m.id) for m in matches}), len(matches))

    def test_malformed_answers_mean_no_matches_not_a_crash(self):
        for answer in ({}, {"matches": "none"}, {"matches": None}):
            self.assertEqual(judge(answer)[0], [])

    def test_no_candidates_means_no_ai_call(self):
        matches, client = judge({"matches": []}, candidates=[])

        self.assertEqual((matches, client.calls), ([], 0))

    def test_prompt_lists_new_idea_and_every_candidate_with_its_id(self):
        _, client = judge({"matches": []})

        for expected in ("Hydration tracker", "[idea:1] Water reminder", "[project:7] Health apps", "[idea:2] Budget app"):
            self.assertIn(expected, client.last_user)
