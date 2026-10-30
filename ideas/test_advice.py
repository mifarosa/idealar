from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ai.advice import Advice, AdviceItem, NoteAdvisor
from ai.errors import AIProviderError, AllProvidersFailed
from ideas import advice
from ideas.key_vault import seal
from ideas.models import AIModel, Feature, Idea, Project


def make_user(name="owner"):
    return get_user_model().objects.create_user(name, password="pw-for-tests-123")


class StubAdvisor(NoteAdvisor):
    def __init__(self, items=(), error=None):
        self._items, self._error, self.seen = list(items), error, []

    def advise(self, new_note, notes, projects, known_tags):
        self.seen.append((new_note, list(notes), list(projects), list(known_tags)))
        if self._error:
            raise self._error
        return Advice(self._items)


class AdviseIdeaTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.idea = Idea.objects.create(owner=self.user, title="New", body="a note")
        self.other = Idea.objects.create(owner=self.user, title="Other", body="b", ai_tags=["health"])
        self.project = Project.objects.create(owner=self.user, name="Life")
        Feature.objects.create(idea=self.other, text="Streaks")
        Idea.objects.create(owner=make_user("stranger"), title="Secret", body="not yours")

    def run_advice(self, advisor):
        return advice.advise_idea(self.idea, lambda: advisor)

    def test_advisor_sees_every_other_note_of_the_owner_and_nobody_elses(self):
        advisor = StubAdvisor()

        self.run_advice(advisor)

        text, notes, projects, tags = advisor.seen[0]
        self.assertIn("New", text)
        self.assertEqual([n.title for n in notes], ["Other"])
        self.assertEqual(notes[0].open_features, ("Streaks",))
        self.assertEqual(([p.name for p in projects], tags), (["Life"], ["health"]))

    def test_items_are_stored_pending_with_the_target_titles(self):
        items = [AdviceItem("related", "same domain", target=self.other.pk),
                 AdviceItem("add_to_project", "fits", target=self.project.pk)]

        self.assertTrue(self.run_advice(StubAdvisor(items)))

        self.idea.refresh_from_db()
        self.assertEqual(self.idea.advice_status, "done")
        self.assertEqual([(e["kind"], e["target_title"], e["status"]) for e in self.idea.advice],
                         [("related", "Other", "pending"), ("add_to_project", "Life", "pending")])

    def test_failure_keeps_the_previous_advice_and_marks_the_status(self):
        self.run_advice(StubAdvisor([AdviceItem("new_idea", "gap", text="Something")]))

        with self.assertLogs("ideas.advice", level="WARNING"):
            ok = self.run_advice(StubAdvisor(error=AllProvidersFailed([("x", AIProviderError("down"))])))

        self.idea.refresh_from_db()
        self.assertFalse(ok)
        self.assertEqual((self.idea.advice_status, len(self.idea.advice)), ("failed", 1))


class DecideAdviceTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.idea = Idea.objects.create(owner=self.user, title="New", body="a note")
        self.project = Project.objects.create(owner=self.user, name="Life")

    def store(self, **entry):
        base = {"kind": "tag", "text": "", "target": None, "target_title": "", "reason": "r", "status": "pending"}
        self.idea.advice = [base | entry]
        self.idea.save()

    def test_borrowed_feature_becomes_a_feature(self):
        self.store(kind="borrow_feature", text="Streaks")

        advice.decide_advice(self.idea, 0, apply=True)

        self.assertEqual(list(self.idea.features.values_list("text", flat=True)), ["Streaks"])
        self.assertEqual(self.idea.advice[0]["status"], "applied")

    def test_project_suggestion_links_only_the_owners_project(self):
        self.store(kind="add_to_project", target=self.project.pk)
        advice.decide_advice(self.idea, 0, apply=True)
        self.assertEqual(list(self.idea.projects.all()), [self.project])

        foreign = Project.objects.create(owner=make_user("other"), name="Theirs")
        self.store(kind="add_to_project", target=foreign.pk)
        with self.assertRaises(advice.ActionNotApplicable):
            advice.decide_advice(self.idea, 0, apply=True)
        self.assertEqual(self.idea.advice[0]["status"], "pending")

    def test_tag_is_added_once_and_capped(self):
        self.store(kind="tag", text="health")
        advice.decide_advice(self.idea, 0, apply=True)
        self.store(kind="tag", text="Health")
        advice.decide_advice(self.idea, 0, apply=True)

        self.assertEqual(self.idea.ai_tags, ["health"])

    def test_new_idea_creates_a_note_for_the_owner(self):
        self.store(kind="new_idea", text="Sleep and habits combined")

        advice.decide_advice(self.idea, 0, apply=True)

        created = Idea.objects.get(body="Sleep and habits combined")
        self.assertEqual(created.owner, self.user)

    def test_related_and_merge_change_nothing_and_dismiss_only_hides(self):
        self.store(kind="merge", target=self.idea.pk)

        advice.decide_advice(self.idea, 0, apply=False)

        self.assertEqual(Idea.objects.count(), 1)
        self.assertEqual(self.idea.advice[0]["status"], "dismissed")

    def test_a_decided_card_cannot_be_applied_again(self):
        self.store(kind="borrow_feature", text="Streaks", status="applied")

        advice.decide_advice(self.idea, 0, apply=True)

        self.assertEqual(self.idea.features.count(), 0)


class AdviceViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.idea = Idea.objects.create(owner=self.user, title="New", body="a note")

    def test_button_runs_the_advisor_and_cards_render(self):
        items = [AdviceItem("new_idea", "gap", text="Combine things"), AdviceItem("tag", "consistent", text="health")]
        from unittest.mock import patch

        with patch("ideas.advice.build_advisor", return_value=StubAdvisor(items)):
            response = self.client.post(reverse("ideas:idea-advice", args=[self.idea.pk]), follow=True)

        self.assertContains(response, "2 öneri hazır")
        self.assertContains(response, "Combine things")
        self.assertContains(response, "Yeni fikir olarak kaydet")

    def test_decide_view_applies_and_other_users_get_404(self):
        self.idea.advice = [{"kind": "borrow_feature", "text": "Streaks", "target": None, "target_title": "", "reason": "r", "status": "pending"}]
        self.idea.save()
        url = reverse("ideas:idea-advice-decide", args=[self.idea.pk, 0])

        self.client.post(url, {"decision": "apply"})
        self.assertEqual(self.idea.features.count(), 1)

        self.client.force_login(make_user("intruder"))
        self.assertEqual(self.client.post(url, {"decision": "apply"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("ideas:idea-advice", args=[self.idea.pk])).status_code, 404)

    def test_out_of_range_index_is_ignored(self):
        response = self.client.post(reverse("ideas:idea-advice-decide", args=[self.idea.pk, 5]), {"decision": "apply"})

        self.assertEqual(response.status_code, 302)

    def test_enrich_runs_advice_only_when_the_user_has_a_model(self):
        from unittest.mock import patch

        with patch("ideas.ai_views.advice.advise_idea") as run, patch("ideas.ai_views.ai_enrichment.enrich_idea", return_value=True), \
                patch("ideas.ai_views.similarity.check_idea"):
            self.client.post(reverse("ideas:idea-enrich", args=[self.idea.pk]))
            run.assert_not_called()
            AIModel.objects.create(owner=self.user, kind="groq", label="G", model_name="m", api_key_sealed=seal("k"))
            self.client.post(reverse("ideas:idea-enrich", args=[self.idea.pk]))
            run.assert_called_once()
