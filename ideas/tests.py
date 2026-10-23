from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Idea


def make_user(name: str):
    return get_user_model().objects.create_user(name, password="pw-for-tests-123")


class IdeaModelTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner")

    def test_display_title_prefers_explicit_title(self):
        idea = Idea(owner=self.owner, title="Titled", body="body text")

        self.assertEqual(idea.display_title, "Titled")

    def test_display_title_falls_back_to_first_line_of_body(self):
        idea = Idea(owner=self.owner, body="first line\nsecond line")

        self.assertEqual(idea.display_title, "first line")

    def test_display_title_truncates_long_first_line(self):
        idea = Idea(owner=self.owner, body="x" * 200)

        self.assertEqual(len(idea.display_title), 60)
        self.assertTrue(idea.display_title.endswith("…"))

    def test_matching_searches_title_and_body_case_insensitively(self):
        Idea.objects.create(owner=self.owner, title="Budget app", body="track money")
        Idea.objects.create(owner=self.owner, body="Recipe MANAGER")
        Idea.objects.create(owner=self.owner, body="unrelated")

        self.assertEqual(Idea.objects.matching("budget").count(), 1)
        self.assertEqual(Idea.objects.matching("manager").count(), 1)
        self.assertEqual(Idea.objects.matching("   ").count(), 3)


class IdeaCrudTests(TestCase):
    def setUp(self):
        self.user = make_user("owner")
        self.client.force_login(self.user)

    def test_quick_capture_saves_body_only_idea_for_current_user(self):
        response = self.client.post(reverse("ideas:create"), {"body": "A habit tracker"})

        self.assertRedirects(response, reverse("ideas:list"))
        idea = Idea.objects.get()
        self.assertEqual((idea.owner, idea.title, idea.body), (self.user, "", "A habit tracker"))

    def test_full_form_saves_title_and_body(self):
        self.client.post(reverse("ideas:create"), {"title": "Habits", "body": "Track daily habits"})

        idea = Idea.objects.get()
        self.assertEqual((idea.title, idea.body), ("Habits", "Track daily habits"))

    def test_empty_body_is_rejected_and_nothing_saved(self):
        response = self.client.post(reverse("ideas:create"), {"body": "   "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Idea.objects.count(), 0)

    def test_list_shows_only_own_ideas_newest_first(self):
        Idea.objects.create(owner=self.user, body="older idea")
        Idea.objects.create(owner=self.user, body="newer idea")
        Idea.objects.create(owner=make_user("other"), body="secret idea")

        response = self.client.get(reverse("ideas:list"))

        self.assertEqual([i.body for i in response.context["ideas"]], ["newer idea", "older idea"])

    def test_list_search_filters_results(self):
        Idea.objects.create(owner=self.user, body="budget app")
        Idea.objects.create(owner=self.user, body="recipe app")

        response = self.client.get(reverse("ideas:list"), {"q": "budget"})

        self.assertEqual([i.body for i in response.context["ideas"]], ["budget app"])

    def test_update_changes_idea(self):
        idea = Idea.objects.create(owner=self.user, body="old")

        self.client.post(reverse("ideas:update", args=[idea.pk]), {"title": "New title", "body": "new"})

        idea.refresh_from_db()
        self.assertEqual((idea.title, idea.body), ("New title", "new"))

    def test_delete_requires_post_and_removes_idea(self):
        idea = Idea.objects.create(owner=self.user, body="bye")

        self.assertEqual(self.client.get(reverse("ideas:delete", args=[idea.pk])).status_code, 200)
        self.assertTrue(Idea.objects.filter(pk=idea.pk).exists())
        self.client.post(reverse("ideas:delete", args=[idea.pk]))

        self.assertFalse(Idea.objects.filter(pk=idea.pk).exists())


class IdeaIsolationTests(TestCase):
    def setUp(self):
        self.other_idea = Idea.objects.create(owner=make_user("other"), body="private")
        self.client.force_login(make_user("intruder"))

    def test_other_users_idea_cannot_be_viewed_edited_or_deleted(self):
        for name in ("ideas:update", "ideas:delete"):
            url = reverse(name, args=[self.other_idea.pk])
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {"title": "x", "body": "hacked"}).status_code, 404)

        self.other_idea.refresh_from_db()
        self.assertEqual(self.other_idea.body, "private")

    def test_anonymous_cannot_create(self):
        self.client.logout()

        response = self.client.post(reverse("ideas:create"), {"body": "anon"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Idea.objects.filter(body="anon").count(), 0)
