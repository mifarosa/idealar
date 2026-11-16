from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ideas.chat_context import MAX_NOTES_BLOCK_CHARS, ChatScope, build_context
from ideas.models import Project, ProjectNote


def make_user(name="owner"):
    return get_user_model().objects.create_user(name)


class ProjectNoteTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.project = Project.objects.create(owner=self.user, name="Apple Store")
        self.detail = reverse("ideas:project-detail", args=[self.project.pk])

    def add(self, body, project=None):
        return self.client.post(reverse("ideas:project-note-add", args=[(project or self.project).pk]), {"body": body})

    def test_a_note_is_added_to_the_project_and_shown_on_its_page(self):
        response = self.add("Screenshots need 6.7 inch size")

        self.assertRedirects(response, f"{self.detail}#notes", fetch_redirect_response=False)
        self.assertEqual(self.project.notes.get().body, "Screenshots need 6.7 inch size")
        self.assertContains(self.client.get(self.detail), "Screenshots need 6.7 inch size")

    def test_each_project_keeps_its_own_notes(self):
        other = Project.objects.create(owner=self.user, name="Play Store")
        self.add("only for apple")
        self.add("only for play", project=other)

        self.assertContains(self.client.get(self.detail), "only for apple")
        self.assertNotContains(self.client.get(self.detail), "only for play")
        self.assertContains(self.client.get(reverse("ideas:project-detail", args=[other.pk])), "only for play")

    def test_newest_notes_come_first_and_line_breaks_survive(self):
        self.add("first note")
        self.add("second note\nwith a second line")

        page = self.client.get(self.detail).content.decode()

        self.assertLess(page.index("second note"), page.index("first note"))
        self.assertIn("second note<br>with a second line", page)

    def test_empty_and_overlong_notes_are_refused(self):
        self.add("   ")
        self.add("x" * 10001)

        self.assertFalse(ProjectNote.objects.exists())

    def test_html_in_a_note_is_escaped(self):
        self.add("<script>alert(1)</script>")

        self.assertNotContains(self.client.get(self.detail), "<script>alert(1)</script>")

    def test_web_addresses_in_a_note_become_safe_links(self):
        self.add("TestFlight: https://example.com/tf?x=1&y=2 and <b>bold</b>")

        page = self.client.get(self.detail).content.decode()

        self.assertIn('href="https://example.com/tf?x=1&amp;y=2"', page)
        self.assertIn('rel="nofollow"', page)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", page)  # markup is still shown as text

    def test_a_note_can_be_edited_and_is_marked_as_edited(self):
        self.add("draft")
        note = self.project.notes.get()
        url = reverse("ideas:project-note-edit", args=[self.project.pk, note.pk])

        self.assertContains(self.client.get(url), "draft")
        self.client.post(url, {"body": "final wording"})
        note.refresh_from_db()

        self.assertEqual(note.body, "final wording")
        self.assertEqual(self.client.post(url, {"body": ""}).status_code, 200)  # stays on the form with an error
        self.assertEqual(ProjectNote.objects.get().body, "final wording")

    def test_a_note_can_be_deleted_and_the_page_asks_first(self):
        self.add("to remove")
        note = self.project.notes.get()

        self.assertContains(self.client.get(self.detail), "data-confirm=")
        self.client.post(reverse("ideas:project-note-delete", args=[self.project.pk, note.pk]))

        self.assertFalse(ProjectNote.objects.exists())

    def test_nobody_can_touch_notes_of_someone_elses_project(self):
        stranger = make_user("stranger")
        theirs = Project.objects.create(owner=stranger, name="Theirs")
        note = ProjectNote.objects.create(project=theirs, body="secret plan")

        for name, args in (("project-note-edit", [theirs.pk, note.pk]), ("project-note-delete", [theirs.pk, note.pk]), ("project-note-add", [theirs.pk])):
            self.assertEqual(self.client.post(reverse(f"ideas:{name}", args=args), {"body": "x"}).status_code, 404, name)
        self.assertEqual(self.client.get(reverse("ideas:project-note-edit", args=[theirs.pk, note.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("ideas:project-list")), "secret plan")
        self.assertEqual(ProjectNote.objects.get().body, "secret plan")

    def test_a_note_cannot_be_reached_through_another_project_of_the_same_user(self):
        other = Project.objects.create(owner=self.user, name="Other")
        self.add("belongs to apple")
        note = self.project.notes.get()

        response = self.client.post(reverse("ideas:project-note-delete", args=[other.pk, note.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(ProjectNote.objects.exists())

    def test_notes_need_a_login_and_post(self):
        note = ProjectNote.objects.create(project=self.project, body="x")
        self.assertEqual(self.client.get(reverse("ideas:project-note-add", args=[self.project.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse("ideas:project-note-delete", args=[self.project.pk, note.pk])).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("ideas:project-note-add", args=[self.project.pk]), {"body": "x"}).status_code, 302)

    def test_deleting_the_project_deletes_its_notes(self):
        self.add("goes with the project")

        self.project.delete()

        self.assertFalse(ProjectNote.objects.exists())

    def test_the_project_list_counts_notes(self):
        self.add("one")
        self.add("two")

        self.assertContains(self.client.get(reverse("ideas:project-list")), "2 not")


class ProjectNotesForTheAITests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.project = Project.objects.create(owner=self.user, name="Apple Store")

    def test_the_project_chat_sees_the_projects_notes_but_not_other_projects(self):
        ProjectNote.objects.create(project=self.project, body="Review takes about two days")
        other = Project.objects.create(owner=self.user, name="Other")
        ProjectNote.objects.create(project=other, body="unrelated secret")

        context = build_context(ChatScope(self.user, project=self.project))

        self.assertIn("Review takes about two days", context)
        self.assertNotIn("unrelated secret", context)

    def test_a_huge_note_cannot_crowd_out_the_rest_of_the_context(self):
        for n in range(30):
            ProjectNote.objects.create(project=self.project, body=f"note {n} " + "x" * 600)

        context = build_context(ChatScope(self.user, project=self.project))

        self.assertLessEqual(context.count("- note"), 8)
        self.assertLess(len(context.split("Project notes")[1]), MAX_NOTES_BLOCK_CHARS + 200)

    def test_notes_are_part_of_the_data_export(self):
        from accounts.export import export_user_data

        ProjectNote.objects.create(project=self.project, body="remember the review times")

        data = export_user_data(self.user)

        self.assertEqual(data["projects"][0]["notes"][0]["text"], "remember the review times")


class ProjectNotesEnglishTests(TestCase):
    def test_the_notes_section_is_in_english_when_english_is_chosen(self):
        user = make_user()
        self.client.force_login(user)
        project = Project.objects.create(owner=user, name="Apple Store")
        self.client.post(reverse("set_language"), {"language": "en"})

        page = self.client.get(reverse("ideas:project-detail", args=[project.pk]))

        self.assertContains(page, "Add note")
        self.assertContains(page, "No notes for this project yet.")
        self.assertNotContains(page, "Not ekle")
