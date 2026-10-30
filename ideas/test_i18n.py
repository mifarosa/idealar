import re
from pathlib import Path

import polib
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from ideas.models import Feature, Idea, Project
from kanban import services as kanban
from support.models import Ticket

CATALOG = Path(settings.BASE_DIR) / "locale" / "en" / "LC_MESSAGES"
PLACEHOLDER = re.compile(r"\{[a-z_]+\}|%\([a-z_]+\)s")
TURKISH_LETTERS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")


class CatalogTests(TestCase):
    def setUp(self):
        self.po = polib.pofile(str(CATALOG / "django.po"))

    def test_every_message_is_translated_and_none_is_fuzzy(self):
        for entry in self.po:
            self.assertNotIn("fuzzy", entry.flags, entry.msgid)
            strings = list(entry.msgstr_plural.values()) if entry.msgid_plural else [entry.msgstr]
            for text in strings:
                self.assertTrue(text.strip(), f"untranslated: {entry.msgid!r}")

    def test_translations_keep_the_placeholders_of_the_source(self):
        for entry in self.po:
            strings = list(entry.msgstr_plural.values()) if entry.msgid_plural else [entry.msgstr]
            for text in strings:
                self.assertEqual(set(PLACEHOLDER.findall(text)), set(PLACEHOLDER.findall(entry.msgid)), entry.msgid)

    def test_the_compiled_catalog_matches_the_po_file(self):
        mo = polib.mofile(str(CATALOG / "django.mo"))
        compiled = {(e.msgctxt, e.msgid): (e.msgstr, dict(e.msgstr_plural)) for e in mo}
        for entry in self.po:
            key = (entry.msgctxt, entry.msgid)
            self.assertIn(key, compiled, f"run compilemessages: {entry.msgid!r}")
            self.assertEqual(compiled[key], (entry.msgstr, dict(entry.msgstr_plural)), entry.msgid)


class LanguageSwitchTests(TestCase):
    def test_turkish_is_the_default_and_the_switch_sets_english(self):
        page = self.client.get(reverse("accounts:login"))
        self.assertContains(page, "Giriş yap")
        self.assertContains(page, '<html lang="tr">')

        self.client.post(reverse("set_language"), {"language": "en", "next": reverse("accounts:login")})
        page = self.client.get(reverse("accounts:login"))

        self.assertContains(page, "Sign in")
        self.assertContains(page, '<html lang="en">')
        self.assertNotContains(page, "Giriş yap")

    def test_the_choice_can_be_switched_back(self):
        self.client.post(reverse("set_language"), {"language": "en"})
        self.client.post(reverse("set_language"), {"language": "tr"})

        self.assertContains(self.client.get(reverse("accounts:login")), "Giriş yap")

    def test_first_time_visitors_get_the_language_of_their_browser(self):
        english = self.client.get(reverse("accounts:login"), headers={"accept-language": "en-US,en;q=0.9"})
        self.assertContains(english, "Sign in")
        turkish = self.client.get(reverse("accounts:login"), headers={"accept-language": "tr-TR,tr;q=0.9,en;q=0.5"})
        self.assertContains(turkish, "Giriş yap")
        other = self.client.get(reverse("accounts:login"), headers={"accept-language": "de-DE"})
        self.assertContains(other, "Giriş yap")  # unsupported languages fall back to Turkish

    def test_unknown_languages_and_external_redirects_are_refused(self):
        response = self.client.post(reverse("set_language"), {"language": "xx", "next": "https://evil.example/"})

        self.assertNotIn("evil.example", response.headers.get("Location", ""))
        self.assertContains(self.client.get(reverse("accounts:login")), "Giriş yap")

    def test_both_languages_are_offered_beside_the_logo(self):
        page = self.client.get(reverse("accounts:login"))

        self.assertContains(page, 'name="language" value="tr"')
        self.assertContains(page, 'name="language" value="en"')

    def test_the_manifest_follows_the_language(self):
        self.client.post(reverse("set_language"), {"language": "en"})

        manifest = self.client.get(reverse("pwa:manifest")).json()

        self.assertEqual((manifest["lang"], manifest["description"]), ("en", "Capture app ideas quickly."))


class EnglishInterfaceTests(TestCase):
    """Every page, rendered in English, must contain no Turkish text of its own."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("owner")
        self.client.force_login(self.user)
        self.client.post(reverse("set_language"), {"language": "en"})
        self.project = Project.objects.create(owner=self.user, name="Apple Store")
        self.idea = Idea.objects.create(owner=self.user, title="Water app", body="remind me to drink")
        self.idea.projects.add(self.project)
        Feature.objects.create(idea=self.idea, text="Streaks")
        self.idea.advice = [{"kind": "tag", "text": "health", "target": None, "target_title": "", "reason": "fits", "status": "pending"}]
        self.idea.similar = [{"kind": "idea", "id": 99, "title": "Other", "verdict": "similar", "reason": "same goal", "source": "ai", "status": "pending"}]
        self.idea.save()
        kanban.add_task(self.user, None, "Buy milk", "todo")
        Ticket.objects.create(owner=self.user, title="It breaks", body="always")

    def visible_text(self, response) -> str:
        html = response.content.decode()
        html = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S)
        html = re.sub(r'title="Türkçe"', "", html)
        return html

    def assert_english(self, url, **query):
        response = self.client.get(url, query)
        self.assertEqual(response.status_code, 200, url)
        found = TURKISH_LETTERS.findall(self.visible_text(response))
        self.assertEqual(found, [], f"Turkish text left on {url}: {sorted(set(found))}")

    def test_the_main_pages(self):
        for url in (
            reverse("ideas:list"), reverse("ideas:detail", args=[self.idea.pk]), reverse("ideas:create"),
            reverse("ideas:update", args=[self.idea.pk]), reverse("ideas:delete", args=[self.idea.pk]),
            reverse("ideas:project-list"), reverse("ideas:project-create"), reverse("ideas:project-detail", args=[self.project.pk]),
            reverse("ideas:project-update", args=[self.project.pk]), reverse("ideas:project-delete", args=[self.project.pk]),
            reverse("ideas:project-import"), reverse("ideas:chat"), reverse("ideas:idea-chat", args=[self.idea.pk]),
            reverse("ideas:project-chat", args=[self.project.pk]), reverse("accounts:settings"),
            reverse("ideas:ai-models"), reverse("ideas:ai-model-create"), reverse("kanban:board"),
            reverse("support:list"), reverse("support:create"), reverse("ideas:idea-prompt", args=[self.idea.pk]),
        ):
            self.assert_english(url)

    def test_the_project_board_and_ticket_detail(self):
        self.assert_english(reverse("kanban:board"), proje=self.project.pk)
        self.assert_english(reverse("support:detail", args=[Ticket.objects.get().pk]))

    def test_the_login_and_offline_pages(self):
        self.client.logout()
        self.client.post(reverse("set_language"), {"language": "en"})
        self.assert_english(reverse("accounts:login"))
        self.assert_english(reverse("pwa:offline"))

    def test_messages_and_choices_come_out_in_english(self):
        response = self.client.post(reverse("ideas:create"), {"body": "A brand new idea"}, follow=True)
        self.assertContains(response, "Idea saved.")

        with translation.override("en"):
            from support.models import KIND_CHOICES, STATUS_CHOICES

            self.assertEqual([str(label) for _, label in STATUS_CHOICES], ["Open", "In progress", "Solved", "Closed"])
            self.assertEqual(str(KIND_CHOICES[0][1]), "Suggestion")

    def test_plurals_follow_english_rules(self):
        self.client.post(reverse("kanban:add"), {"title": "second", "status": "todo"})
        page = self.client.get(reverse("kanban:board"))

        self.assertContains(page, "2 cards")

    def test_the_build_prompt_is_written_in_english_for_english_users(self):
        page = self.client.get(reverse("ideas:idea-prompt", args=[self.idea.pk]))

        self.assertContains(page, "WAY OF WORKING")
        self.assertContains(page, "Answer me in English")


class ThemeNamesTests(TestCase):
    def test_the_light_theme_is_called_light_and_a_ticket_status_open(self):
        self.client.post(reverse("set_language"), {"language": "en"})

        page = self.client.get(reverse("accounts:login"))

        self.assertContains(page, ">Light</button>")
        with translation.override("en"):
            from support.models import STATUS_CHOICES

            self.assertEqual(str(STATUS_CHOICES[0][1]), "Open")
