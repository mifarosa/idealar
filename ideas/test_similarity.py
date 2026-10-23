from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from ai.errors import AIProviderError, AllProvidersFailed
from ai.similarity import Candidate, SimilarityJudge, SimilarMatch
from ideas import similarity
from ideas.errors import ActionNotApplicable
from ideas.models import SIMILARITY_DONE, SIMILARITY_WORDS_ONLY, SUGGESTION_APPLIED, SUGGESTION_DISMISSED, SUGGESTION_PENDING, Feature, Idea, Project


def make_user(name="owner"):
    return get_user_model().objects.create_user(name, password="pw-for-tests-123")


class StubJudge(SimilarityJudge):
    def __init__(self, matches=(), error=None):
        self._matches, self._error, self.seen = list(matches), error, []

    def judge(self, new_idea, candidates):
        self.seen.append((new_idea, list(candidates)))
        if self._error:
            raise self._error
        return self._matches


def down_judge():
    return StubJudge(error=AllProvidersFailed([("groq", AIProviderError("down"))]))


class TokenizeTests(SimpleTestCase):
    def test_turkish_forms_of_the_same_word_share_a_stem(self):
        self.assertEqual(similarity.tokenize("hatırlatıcı") & similarity.tokenize("hatırlatma"), {"hatır"})

    def test_stopwords_digits_and_short_words_are_ignored(self):
        self.assertEqual(similarity.tokenize("bir uygulama ve 2024 ile ab the"), set())

    def test_turkish_capital_i_is_lowercased_correctly(self):
        self.assertEqual(similarity.tokenize("IŞIK İÇME"), similarity.tokenize("ışık içme"))

    def test_overlap_is_relative_to_the_smaller_text_and_needs_two_words(self):
        self.assertEqual(similarity.word_overlap({"a", "b"}, {"a", "b", "c", "d"}), 1.0)
        self.assertEqual(similarity.word_overlap({"a"}, {"a", "b"}), 0.0)
        self.assertEqual(similarity.word_overlap(set(), {"a", "b"}), 0.0)


class GatherCandidatesTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.idea = Idea.objects.create(owner=self.user, body="new idea")

    def test_excludes_itself_other_users_things_and_projects_it_already_belongs_to(self):
        other = Idea.objects.create(owner=self.user, body="other idea")
        stranger = make_user("stranger")
        Idea.objects.create(owner=stranger, body="theirs")
        Project.objects.create(owner=stranger, name="Theirs")
        joined = Project.objects.create(owner=self.user, name="Joined")
        free = Project.objects.create(owner=self.user, name="Free")
        self.idea.projects.add(joined)

        candidates = [c for c, _ in similarity.gather_candidates(self.idea)]

        self.assertEqual({(c.kind, c.id) for c in candidates}, {("idea", other.pk), ("project", free.pk)})

    def test_project_candidate_mentions_its_ideas(self):
        project = Project.objects.create(owner=self.user, name="Health", description="health tools")
        member = Idea.objects.create(owner=self.user, title="Water reminder", body="x")
        member.projects.add(project)

        candidate = next(c for c, _ in similarity.gather_candidates(self.idea) if c.kind == "project")

        self.assertIn("Water reminder", candidate.summary)


class PickForAiTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.idea = Idea.objects.create(owner=self.user, title="Water reminder", body="drink water reminder app")

    def test_small_collections_are_sent_to_the_ai_in_full(self):
        for n in range(10):
            Idea.objects.create(owner=self.user, body=f"unrelated topic number {n}")

        picked = similarity._pick_for_ai(self.idea, similarity.gather_candidates(self.idea))

        self.assertEqual(len(picked), 10)

    def test_large_collections_are_shortlisted_by_words_and_recency(self):
        old_match = Idea.objects.create(owner=self.user, title="Hydration water reminder", body="drink water reminder")
        for n in range(60):
            Idea.objects.create(owner=self.user, body=f"completely different thing {n} zebra {n}")

        picked = similarity._pick_for_ai(self.idea, similarity.gather_candidates(self.idea))

        self.assertLessEqual(len(picked), similarity.MAX_AI_CANDIDATES)
        self.assertIn(("idea", old_match.pk), {(c.kind, c.id) for c in picked})  # found by words although old


class CheckIdeaTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.existing = Idea.objects.create(owner=self.user, title="Water reminder", body="remind me to drink water")
        self.idea = Idea.objects.create(owner=self.user, title="Hydration tracker", body="reminder to drink water")

    def judge_with(self, *matches):
        return lambda: StubJudge(matches)

    def test_ai_matches_are_stored_with_titles_and_pending_status(self):
        match = SimilarMatch("idea", self.existing.pk, "similar", "both remind about water")

        similarity.check_idea(self.idea, self.judge_with(match))

        self.idea.refresh_from_db()
        self.assertEqual(self.idea.similarity_status, SIMILARITY_DONE)
        self.assertEqual(
            self.idea.similar,
            [{"kind": "idea", "id": self.existing.pk, "title": "Water reminder", "verdict": "similar", "reason": "both remind about water", "source": "ai", "status": SUGGESTION_PENDING}],
        )

    def test_no_match_is_a_clean_result_not_an_error(self):
        similarity.check_idea(self.idea, self.judge_with())

        self.idea.refresh_from_db()
        self.assertEqual((self.idea.similar, self.idea.similarity_status), ([], SIMILARITY_DONE))

    def test_the_ai_sees_the_idea_and_all_other_ideas(self):
        judge = StubJudge()

        similarity.check_idea(self.idea, lambda: judge)

        new_text, candidates = judge.seen[0]
        self.assertIn("reminder to drink water", new_text)
        self.assertEqual([(c.kind, c.id) for c in candidates], [("idea", self.existing.pk)])

    def test_ai_failure_falls_back_to_strong_word_overlap_and_says_so(self):
        with self.assertLogs("ideas.similarity", level="WARNING"):
            similarity.check_idea(self.idea, down_judge)

        self.idea.refresh_from_db()
        self.assertEqual(self.idea.similarity_status, SIMILARITY_WORDS_ONLY)
        self.assertEqual([(h["id"], h["source"]) for h in self.idea.similar], [(self.existing.pk, "words")])
        self.assertIn("Ortak kelimeler", self.idea.similar[0]["reason"])

    def test_ai_failure_with_no_shared_words_reports_nothing_but_still_flags_the_fallback(self):
        Idea.objects.filter(pk=self.existing.pk).update(title="Budget planner", body="track monthly expenses carefully")

        with self.assertLogs("ideas.similarity", level="WARNING"):
            similarity.check_idea(self.idea, down_judge)

        self.idea.refresh_from_db()
        self.assertEqual((self.idea.similar, self.idea.similarity_status), ([], SIMILARITY_WORDS_ONLY))

    def test_factory_configuration_errors_are_handled_like_ai_failures(self):
        def broken_factory():
            raise AllProvidersFailed([])

        with self.assertLogs("ideas.similarity", level="WARNING"):
            similarity.check_idea(self.idea, broken_factory)

        self.idea.refresh_from_db()
        self.assertEqual(self.idea.similarity_status, SIMILARITY_WORDS_ONLY)

    def test_rerun_replaces_the_previous_result(self):
        similarity.check_idea(self.idea, self.judge_with(SimilarMatch("idea", self.existing.pk, "same", "r")))
        similarity.check_idea(self.idea, self.judge_with())

        self.idea.refresh_from_db()
        self.assertEqual(self.idea.similar, [])


class DecideSimilarTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.project = Project.objects.create(owner=self.user, name="Health")
        self.target = Idea.objects.create(owner=self.user, title="Water reminder", body="x")
        self.idea = Idea.objects.create(owner=self.user, title="Hydration tracker", body="y")

    def hint(self, kind, target_id):
        self.idea.similar = [{"kind": kind, "id": target_id, "title": "t", "verdict": "similar", "reason": "r", "source": "ai", "status": SUGGESTION_PENDING}]
        self.idea.save()

    def test_apply_for_a_project_links_the_idea_to_it(self):
        self.hint("project", self.project.pk)

        similarity.decide_similar(self.idea, 0, apply=True)

        self.assertEqual(list(self.idea.projects.all()), [self.project])
        self.assertEqual(self.idea.similar[0]["status"], SUGGESTION_APPLIED)

    def test_apply_for_an_idea_adds_this_idea_as_a_feature_of_the_target(self):
        self.hint("idea", self.target.pk)

        similarity.decide_similar(self.idea, 0, apply=True)

        self.assertEqual(list(self.target.features.values_list("text", flat=True)), ["Hydration tracker"])

    def test_apply_twice_adds_only_once(self):
        self.hint("idea", self.target.pk)

        similarity.decide_similar(self.idea, 0, apply=True)
        similarity.decide_similar(self.idea, 0, apply=True)

        self.assertEqual(self.target.features.count(), 1)

    def test_dismiss_changes_only_the_status(self):
        self.hint("project", self.project.pk)

        similarity.decide_similar(self.idea, 0, apply=False)

        self.assertEqual(self.idea.projects.count(), 0)
        self.assertEqual(self.idea.similar[0]["status"], SUGGESTION_DISMISSED)

    def test_deleted_target_raises_and_keeps_the_hint_pending(self):
        self.hint("idea", self.target.pk)
        self.target.delete()

        with self.assertRaises(ActionNotApplicable):
            similarity.decide_similar(self.idea, 0, apply=True)

        self.idea.refresh_from_db()
        self.assertEqual(self.idea.similar[0]["status"], SUGGESTION_PENDING)

    def test_other_users_project_cannot_be_linked(self):
        foreign = Project.objects.create(owner=make_user("stranger"), name="Foreign")
        self.hint("project", foreign.pk)

        with self.assertRaises(ActionNotApplicable):
            similarity.decide_similar(self.idea, 0, apply=True)

        self.assertEqual(self.idea.projects.count(), 0)


class SimilarityViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.target = Idea.objects.create(owner=self.user, title="Water reminder", body="x")
        self.idea = Idea.objects.create(owner=self.user, title="Hydration tracker", body="y")

    def patch_judge(self, judge):
        patcher = patch("ideas.similarity.build_judge", return_value=judge)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_manual_check_stores_and_card_warns_with_action_buttons(self):
        self.patch_judge(StubJudge([SimilarMatch("idea", self.target.pk, "same", "ikisi de su içmeyi hatırlatıyor")]))

        self.client.post(reverse("ideas:idea-similar-check", args=[self.idea.pk]))
        response = self.client.get(reverse("ideas:list"), {"open": self.idea.pk})

        self.assertContains(response, "Buna benzer bir fikrin var")
        self.assertContains(response, "Water reminder")
        self.assertContains(response, "ikisi de su içmeyi hatırlatıyor")
        self.assertContains(response, "O fikre özellik olarak ekle")

    def test_clean_result_is_shown_after_a_check(self):
        self.patch_judge(StubJudge([]))

        self.client.post(reverse("ideas:idea-similar-check", args=[self.idea.pk]))

        self.assertContains(self.client.get(reverse("ideas:list"), {"open": self.idea.pk}), "Benzer bir kayıt bulunmadı")

    def test_ai_outage_tells_the_user_only_words_were_checked(self):
        self.patch_judge(down_judge())

        with self.assertLogs("ideas.similarity", level="WARNING"):
            response = self.client.post(reverse("ideas:idea-similar-check", args=[self.idea.pk]), follow=True)

        self.assertContains(response, "yalnızca kelime benzerliğine baktım")

    def test_decide_endpoint_applies_the_hint(self):
        self.patch_judge(StubJudge([SimilarMatch("idea", self.target.pk, "similar", "r")]))
        self.client.post(reverse("ideas:idea-similar-check", args=[self.idea.pk]))

        self.client.post(reverse("ideas:idea-similar-decide", args=[self.idea.pk, 0]), {"decision": "apply"})

        self.assertEqual(self.target.features.count(), 1)

    def test_decide_with_out_of_range_index_is_ignored(self):
        response = self.client.post(reverse("ideas:idea-similar-decide", args=[self.idea.pk, 9]), {"decision": "apply"})

        self.assertEqual(response.status_code, 302)

    def test_other_users_cannot_check_or_decide(self):
        self.client.force_login(make_user("intruder"))

        for name, args in (("idea-similar-check", [self.idea.pk]), ("idea-similar-decide", [self.idea.pk, 0])):
            self.assertEqual(self.client.post(reverse(f"ideas:{name}", args=args)).status_code, 404)

    def test_enrich_endpoint_also_runs_the_duplicate_check(self):
        self.patch_judge(StubJudge([SimilarMatch("idea", self.target.pk, "same", "r")]))
        with patch("ideas.ai_views.ai_enrichment.build_analyzer") as analyzer:
            analyzer.return_value.analyze.side_effect = AllProvidersFailed([])  # enrichment fails, check still runs
            with self.assertLogs("ideas.ai_enrichment", level="WARNING"):
                self.client.post(reverse("ideas:idea-enrich", args=[self.idea.pk]))

        self.idea.refresh_from_db()
        self.assertEqual(len(self.idea.similar), 1)

    def test_feature_of_target_is_a_plain_feature_row(self):
        self.patch_judge(StubJudge([SimilarMatch("idea", self.target.pk, "similar", "r")]))
        self.client.post(reverse("ideas:idea-similar-check", args=[self.idea.pk]))
        self.client.post(reverse("ideas:idea-similar-decide", args=[self.idea.pk, 0]), {"decision": "apply"})

        self.assertEqual(Feature.objects.get().is_done, False)
