from django.test import SimpleTestCase

from ai.advice import (
    MAX_PER_KIND,
    NOTES_BUDGET_CHARS,
    Note,
    NoteAdvisor,
    ProjectRef,
    render_notes,
)
from ai.client import LLMClient

NOTES = [Note(1, "Habit tracker", "Tracks daily habits", tags=("health",), projects=("Life",), open_features=("Streaks",)),
         Note(2, "Sleep log", "Logs sleep")]
PROJECTS = [ProjectRef(7, "Life", "personal apps")]


class StubClient(LLMClient):
    name = "stub"

    def __init__(self, answer):
        self._answer, self.seen = answer, []

    def chat_json(self, system, messages):
        self.seen.append((system, messages[-1]["content"]))
        return self._answer


def advise(items, notes=NOTES):
    client = StubClient({"items": items})
    return NoteAdvisor(client).advise("new note", notes, PROJECTS, ["health"]), client


class PromptTests(SimpleTestCase):
    def test_every_note_project_and_tag_is_sent(self):
        _, client = advise([])

        message = client.seen[0][1]
        for expected in ("NEW NOTE:\nnew note", "[1] Habit tracker", "tags: health", "projects: Life", "open features: Streaks",
                         "[2] Sleep log", "[7] Life", "TAGS ALREADY IN USE: health"):
            self.assertIn(expected, message)


class RenderNotesTests(SimpleTestCase):
    def many(self, count, text_size):
        return [Note(i, f"Title {i}", "x" * text_size) for i in range(1, count + 1)]

    def test_small_notebooks_are_sent_in_full(self):
        text = render_notes(self.many(3, 400))

        self.assertEqual(text.count("\n"), 2)
        self.assertIn("x" * 400, text)

    def test_large_notebooks_shrink_note_texts_but_keep_every_note(self):
        notes = self.many(500, 2000)

        text = render_notes(notes, budget=60_000)

        self.assertLessEqual(len(text), 60_000)
        self.assertEqual(text.count("\n") + 1, 500)

    def test_an_enormous_notebook_keeps_titles_of_the_newest_notes_within_budget(self):
        notes = self.many(5000, 100)

        text = render_notes(notes, budget=20_000)

        self.assertLessEqual(len(text), 20_000)
        self.assertTrue(text.startswith("[1] Title 1"))

    def test_default_budget_is_generous(self):
        self.assertGreaterEqual(NOTES_BUDGET_CHARS, 100_000)


class ParseTests(SimpleTestCase):
    def test_valid_items_of_every_kind_are_kept(self):
        advice, _ = advise([
            {"kind": "related", "target": 1, "reason": "same domain"},
            {"kind": "merge", "target": "2", "reason": "duplicate"},
            {"kind": "borrow_feature", "target": 1, "text": "Streaks", "reason": "fits"},
            {"kind": "add_to_project", "target": 7, "reason": "personal app"},
            {"kind": "tag", "text": "#health", "reason": "consistent"},
            {"kind": "new_idea", "text": "Combine sleep and habits", "reason": "gap"},
        ])

        self.assertEqual([i.kind for i in advice.items],
                         ["related", "merge", "borrow_feature", "add_to_project", "tag", "new_idea"])
        self.assertEqual(advice.items[4].text, "health")
        self.assertEqual(advice.items[1].target, 2)

    def test_invented_ids_unknown_kinds_and_empty_content_are_dropped(self):
        advice, _ = advise([
            {"kind": "related", "target": 99, "reason": "x"},
            {"kind": "add_to_project", "target": 1, "reason": "note id used as project id"},
            {"kind": "hack", "target": 1, "reason": "x"},
            {"kind": "tag", "text": "  ", "reason": "x"},
            {"kind": "related", "target": 1, "reason": ""},
            {"kind": "new_idea", "text": "", "reason": "x"},
            "not a dict",
            {"kind": "related", "target": True, "reason": "bool is not an id"},
        ])

        self.assertEqual(advice.items, [])

    def test_duplicates_and_per_kind_limits(self):
        items = [{"kind": "new_idea", "text": f"idea {n}", "reason": "r"} for n in range(10)]
        items += [{"kind": "related", "target": 1, "reason": "a"}, {"kind": "related", "target": 1, "reason": "b"}]

        advice, _ = advise(items)

        self.assertEqual(len([i for i in advice.items if i.kind == "new_idea"]), MAX_PER_KIND)
        self.assertEqual(len([i for i in advice.items if i.kind == "related"]), 1)

    def test_non_list_answer_gives_no_items(self):
        client = StubClient({"items": "nothing"})

        self.assertEqual(NoteAdvisor(client).advise("n", NOTES, PROJECTS, []).items, [])

    def test_long_text_is_capped(self):
        advice, _ = advise([{"kind": "new_idea", "text": "y" * 5000, "reason": "r" * 5000}])

        self.assertLessEqual(len(advice.items[0].text), 300)
        self.assertLessEqual(len(advice.items[0].reason), 300)
