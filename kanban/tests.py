import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ideas.models import Idea, Project
from kanban import services
from kanban.models import Task


def make_user(name="owner"):
    return get_user_model().objects.create_user(name)


def titles(owner, project, status):
    return [t.title for t in services.board_tasks(owner, project).filter(status=status)]


class ServiceTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.project = Project.objects.create(owner=self.user, name="P")

    def test_new_cards_go_to_the_bottom_of_their_column(self):
        for title in ("a", "b", "c"):
            services.add_task(self.user, None, title, "todo")

        self.assertEqual(titles(self.user, None, "todo"), ["a", "b", "c"])

    def test_boards_are_separate_per_project_and_personal(self):
        services.add_task(self.user, None, "personal", "todo")
        services.add_task(self.user, self.project, "project", "todo")

        self.assertEqual(titles(self.user, None, "todo"), ["personal"])
        self.assertEqual(titles(self.user, self.project, "todo"), ["project"])

    def test_move_within_a_column_reorders_and_renumbers(self):
        a, b, c = (services.add_task(self.user, None, t, "todo") for t in "abc")

        services.move_task(c, "todo", 0)

        self.assertEqual(titles(self.user, None, "todo"), ["c", "a", "b"])
        self.assertEqual(sorted(Task.objects.values_list("position", flat=True)), [0, 1, 2])

    def test_move_to_another_column_inserts_at_the_index_and_closes_the_gap(self):
        a, b = (services.add_task(self.user, None, t, "todo") for t in "ab")
        x, y = (services.add_task(self.user, None, t, "doing") for t in "xy")

        services.move_task(a, "doing", 1)

        self.assertEqual(titles(self.user, None, "todo"), ["b"])
        self.assertEqual(titles(self.user, None, "doing"), ["x", "a", "y"])

    def test_index_is_clamped_and_unknown_status_rejected(self):
        a = services.add_task(self.user, None, "a", "todo")
        b = services.add_task(self.user, None, "b", "todo")

        services.move_task(a, "todo", 99)
        self.assertEqual(titles(self.user, None, "todo"), ["b", "a"])
        with self.assertRaises(ValueError):
            services.move_task(a, "archived", 0)

    def test_stepping_moves_to_the_neighbouring_column_and_stops_at_the_edges(self):
        task = services.add_task(self.user, None, "t", "todo")

        services.step_task(task, -1)
        self.assertEqual(task.status, "todo")
        services.step_task(task, 1)
        services.step_task(task, 1)
        services.step_task(task, 1)
        task.refresh_from_db()
        self.assertEqual(task.status, "done")


class ViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.project = Project.objects.create(owner=self.user, name="Apple Store")
        self.idea = Idea.objects.create(owner=self.user, title="Water app", body="x")
        self.stranger = make_user("other")
        self.foreign_project = Project.objects.create(owner=self.stranger, name="Theirs")

    def add(self, **data):
        return self.client.post(reverse("kanban:add"), {"title": "Write copy", "status": "todo", **data})

    def test_anonymous_users_are_sent_to_login(self):
        self.client.logout()

        self.assertEqual(self.client.get(reverse("kanban:board")).status_code, 302)

    def test_personal_and_project_boards_render_their_own_cards(self):
        self.add()
        self.add(proje=str(self.project.pk), title="Upload screenshots")

        personal = self.client.get(reverse("kanban:board"))
        project = self.client.get(reverse("kanban:board"), {"proje": self.project.pk})

        self.assertContains(personal, "Write copy")
        self.assertNotContains(personal, "Upload screenshots")
        self.assertContains(project, "Upload screenshots")
        self.assertNotContains(project, "Write copy")
        self.assertContains(project, "Apple Store")

    def test_a_card_can_link_one_of_the_users_ideas_but_not_a_foreign_one(self):
        foreign_idea = Idea.objects.create(owner=self.stranger, title="Secret", body="x")

        self.add(idea=str(self.idea.pk), title="linked")
        self.add(idea=str(foreign_idea.pk), title="foreign link")

        self.assertEqual(Task.objects.get(title="linked").idea, self.idea)
        self.assertIsNone(Task.objects.get(title="foreign link").idea)

    def test_project_boards_only_offer_the_ideas_of_that_project(self):
        self.idea.projects.add(self.project)
        Idea.objects.create(owner=self.user, title="Unrelated", body="x")

        page = self.client.get(reverse("kanban:board"), {"proje": self.project.pk})

        self.assertContains(page, "Water app")
        self.assertNotContains(page, "Unrelated")

    def test_someone_elses_project_board_is_a_404_and_cannot_receive_cards(self):
        self.assertEqual(self.client.get(reverse("kanban:board"), {"proje": self.foreign_project.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse("kanban:board"), {"proje": "abc"}).status_code, 404)
        self.assertEqual(self.add(proje=str(self.foreign_project.pk)).status_code, 404)
        self.assertFalse(Task.objects.exists())

    def test_an_empty_title_adds_nothing(self):
        self.client.post(reverse("kanban:add"), {"title": "  ", "status": "todo"})

        self.assertFalse(Task.objects.exists())

    def test_unknown_status_falls_back_to_the_first_column(self):
        self.add(status="bogus")

        self.assertEqual(Task.objects.get().status, "todo")

    def test_drag_and_drop_endpoint_moves_the_card(self):
        self.add(title="a")
        self.add(title="b")
        a, b = Task.objects.order_by("id")

        response = self.client.post(reverse("kanban:move", args=[b.pk]), {"status": "doing", "index": "0"})

        self.assertEqual(json.loads(response.content), {"ok": True})
        b.refresh_from_db()
        self.assertEqual((b.status, b.position), ("doing", 0))

    def test_invalid_moves_are_400_and_change_nothing(self):
        self.add()
        task = Task.objects.get()

        for data in ({"status": "bogus", "index": "0"}, {"status": "done", "index": "-1"}, {"status": "done"}):
            self.assertEqual(self.client.post(reverse("kanban:move", args=[task.pk]), data).status_code, 400)
        task.refresh_from_db()
        self.assertEqual(task.status, "todo")

    def test_arrow_buttons_move_to_the_neighbour_column(self):
        self.add()
        task = Task.objects.get()

        self.client.post(reverse("kanban:move", args=[task.pk]), {"direction": "right"})
        task.refresh_from_db()

        self.assertEqual(task.status, "doing")

    def test_rename_and_delete(self):
        self.add()
        task = Task.objects.get()

        ok = self.client.post(reverse("kanban:rename", args=[task.pk]), {"title": "  New name "})
        empty = self.client.post(reverse("kanban:rename", args=[task.pk]), {"title": " "})
        self.assertEqual((json.loads(ok.content)["title"], empty.status_code), ("New name", 400))

        self.client.post(reverse("kanban:delete", args=[task.pk]))
        self.assertFalse(Task.objects.exists())

    def test_nobody_can_touch_another_users_cards(self):
        theirs = services.add_task(self.stranger, None, "Theirs", "todo")

        for name, data in (("move", {"status": "done", "index": "0"}), ("rename", {"title": "x"}), ("delete", {})):
            self.assertEqual(self.client.post(reverse(f"kanban:{name}", args=[theirs.pk]), data).status_code, 404, name)
        theirs.refresh_from_db()
        self.assertEqual((theirs.title, theirs.status), ("Theirs", "todo"))

    def test_actions_need_post(self):
        self.add()
        task = Task.objects.get()

        self.assertEqual(self.client.get(reverse("kanban:delete", args=[task.pk])).status_code, 405)

    def test_html_in_a_card_title_is_escaped(self):
        self.add(title="<b>bold</b>")

        self.assertNotContains(self.client.get(reverse("kanban:board")), "<b>bold</b>")

    def test_deleting_a_project_removes_its_cards_and_an_idea_only_unlinks(self):
        self.add(proje=str(self.project.pk), idea=str(self.idea.pk), title="card")
        self.add(title="personal", idea=str(self.idea.pk))

        self.idea.delete()
        self.assertEqual(Task.objects.filter(title="personal").count(), 1)  # the card survives, unlinked
        self.project.delete()

        self.assertEqual(list(Task.objects.values_list("title", flat=True)), ["personal"])

    def test_sidebar_and_tab_bar_link_to_the_board(self):
        page = self.client.get(reverse("ideas:list"))

        self.assertEqual(page.content.decode().count(f'href="{reverse("kanban:board")}"'), 2)
