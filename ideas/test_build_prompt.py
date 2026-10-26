from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ai.brief import Brief
from ai.errors import AllProvidersFailed
from ideas import build_prompt
from ideas.models import Feature, Idea, Project


def make_user(name="owner"):
    return get_user_model().objects.create_user(name, password="pw-for-tests-123")


class StubWriter:
    def __init__(self, brief=None, error=None):
        self.brief, self.error, self.calls = brief, error, []

    def write(self, idea_text, platforms, features, extend_existing):
        self.calls.append({"text": idea_text, "platforms": list(platforms), "features": list(features), "extend": extend_existing})
        if self.error:
            raise self.error
        return self.brief


class BuildPromptTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.idea = Idea.objects.create(
            owner=self.user, title="Water reminder", body="Remind me to drink water\nwith smart timing", platforms=["pwa", "ios"],
            ai_summary="Reminds you to drink water.", ai_tags=["health"],
        )
        Feature.objects.create(idea=self.idea, text="Login", is_done=True)
        Feature.objects.create(idea=self.idea, text="Notifications", platform="ios")

    def prompt(self, mode=build_prompt.MODE_NEW, brief=None):
        idea = Idea.objects.prefetch_related("features", "projects").get(pk=self.idea.pk)
        return build_prompt.build_prompt(idea, mode, brief)

    def test_goal_platforms_tags_and_title_are_present(self):
        text = self.prompt()

        for expected in ("# Water reminder", "AMAÇ", "Reminds you to drink water.", "smart timing", "Platformlar: PWA, iOS", "Etiketler: health"):
            self.assertIn(expected, text)

    def test_a_note_that_only_repeats_the_summary_is_not_listed_twice(self):
        Idea.objects.filter(pk=self.idea.pk).update(ai_summary="Remind me to drink water", body="remind me to drink water.")

        text = self.prompt()

        self.assertEqual(text.lower().count("remind me to drink water"), 1)

    def test_features_are_split_into_todo_and_done_with_platforms(self):
        text = self.prompt()

        self.assertIn("Yapılacak:\n- [ ] Notifications (iOS)", text)
        self.assertIn("Yapılmış:\n- [x] Login", text)

    def test_working_rules_carry_the_developers_standing_preferences(self):
        text = self.prompt()

        for expected in ("Türkçe cevap", "İngilizce olsun", "mimari karar", "her aşamanın sonunda dur", "test yaz", ".env"):
            self.assertIn(expected, text)

    def test_new_mode_starts_from_scratch(self):
        text = self.prompt(build_prompt.MODE_NEW)

        self.assertIn("Sıfırdan başlıyoruz", text)
        self.assertNotIn("Önce depoyu incele", text)

    def test_extend_mode_points_at_the_repository(self):
        project = Project.objects.create(owner=self.user, name="Health apps", github_url="https://github.com/octo/health")
        self.idea.projects.add(project)

        text = self.prompt(build_prompt.MODE_EXTEND)

        self.assertIn("https://github.com/octo/health", text)
        self.assertIn("Önce depoyu incele", text)
        self.assertNotIn("Sıfırdan başlıyoruz", text)

    def test_extend_without_a_repository_falls_back_to_a_fresh_start(self):
        self.assertIn("Sıfırdan başlıyoruz", self.prompt(build_prompt.MODE_EXTEND))

    def test_default_mode_depends_on_whether_a_linked_project_has_a_repository(self):
        idea = Idea.objects.prefetch_related("projects").get(pk=self.idea.pk)
        self.assertEqual(build_prompt.default_mode(idea), build_prompt.MODE_NEW)
        self.idea.projects.add(Project.objects.create(owner=self.user, name="P", github_url="https://github.com/octo/p"))
        idea = Idea.objects.prefetch_related("projects").get(pk=self.idea.pk)

        self.assertEqual(build_prompt.default_mode(idea), build_prompt.MODE_EXTEND)

    def test_pending_similar_hints_are_listed_but_dismissed_and_weak_ones_are_not(self):
        base = {"source": "ai", "status": "pending"}
        self.idea.similar = [
            {**base, "kind": "idea", "id": 1, "title": "Hydration tracker", "verdict": "similar", "reason": "same goal"},
            {**base, "kind": "project", "id": 2, "title": "Weak", "verdict": "related", "reason": "adjacent"},
            {**base, "kind": "idea", "id": 3, "title": "Dismissed", "verdict": "same", "reason": "x", "status": "dismissed"},
        ]
        self.idea.save()

        text = self.prompt()

        self.assertIn("Fikir “Hydration tracker”: same goal", text)
        self.assertNotIn("Weak", text)
        self.assertNotIn("Dismissed", text)

    def test_empty_sections_are_omitted(self):
        bare = Idea.objects.create(owner=self.user, body="just a thought")
        bare = Idea.objects.prefetch_related("features", "projects").get(pk=bare.pk)

        text = build_prompt.build_prompt(bare, build_prompt.MODE_NEW)

        for omitted in ("ÖZELLİKLER", "BENZER KAYITLAR", "ÖNERİLEN YAKLAŞIM"):
            self.assertNotIn(omitted, text)
        self.assertIn("# just a thought", text)

    def test_ai_brief_is_appended_when_given(self):
        brief = Brief(mvp=["Reminders"], stack="Django PWA", phases=["Phase one"], risks=["iOS push"])

        text = self.prompt(brief=brief)

        for expected in ("ÖNERİLEN YAKLAŞIM", "Teknoloji: Django PWA", "MVP kapsamı:\n- Reminders", "Önerilen aşamalar:\n- Phase one", "Riskler:\n- iOS push"):
            self.assertIn(expected, text)


class PromptViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.idea = Idea.objects.create(owner=self.user, title="Water reminder", body="x")
        self.url = reverse("ideas:idea-prompt", args=[self.idea.pk])

    def test_page_shows_the_prompt_and_a_copy_button(self):
        response = self.client.get(self.url)

        self.assertContains(response, "# Water reminder")
        self.assertContains(response, 'data-copy-target="#prompt-text"')
        self.assertContains(response, "AI ile detaylandır")

    def test_mode_comes_from_the_query_and_defaults_sensibly(self):
        self.assertEqual(self.client.get(self.url).context["mode"], "yeni")
        self.assertEqual(self.client.get(self.url, {"mod": "ekle"}).context["mode"], "ekle")
        self.assertEqual(self.client.get(self.url, {"mod": "nonsense"}).context["mode"], "yeni")

    def test_idea_text_is_escaped_in_the_textarea(self):
        Idea.objects.filter(pk=self.idea.pk).update(body="</textarea><script>alert(1)</script>")

        response = self.client.get(self.url)

        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_ai_detail_adds_the_plan_to_the_prompt(self):
        writer = StubWriter(Brief(mvp=["Reminders"], stack="Django", phases=["P1"], risks=["R1"]))
        with patch("ideas.prompt_brief.build_writer", return_value=writer):
            response = self.client.post(self.url, {"mod": "yeni"})

        self.assertContains(response, "ÖNERİLEN YAKLAŞIM")
        self.assertContains(response, "AI planını yenile")
        self.assertFalse(writer.calls[0]["extend"])

    def test_extend_mode_is_passed_to_the_ai(self):
        writer = StubWriter(Brief(mvp=["x"]))
        with patch("ideas.prompt_brief.build_writer", return_value=writer):
            self.client.post(self.url, {"mod": "ekle"})

        self.assertTrue(writer.calls[0]["extend"])

    def test_ai_failure_keeps_the_plain_prompt_and_says_so(self):
        writer = StubWriter(error=AllProvidersFailed([]))
        with patch("ideas.prompt_brief.build_writer", return_value=writer), self.assertLogs("ideas.prompt_brief", level="WARNING"):
            response = self.client.post(self.url, {"mod": "yeni"})

        self.assertContains(response, "AI şu an yanıt veremedi")
        self.assertContains(response, "# Water reminder")
        self.assertNotContains(response, "ÖNERİLEN YAKLAŞIM (AI")

    def test_other_users_get_404_and_anonymous_is_redirected(self):
        self.client.force_login(make_user("intruder"))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {}).status_code, 404)
        self.client.logout()

        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_idea_detail_links_to_the_prompt_page(self):
        self.assertContains(self.client.get(reverse("ideas:detail", args=[self.idea.pk])), self.url)
