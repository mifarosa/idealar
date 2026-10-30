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

    def test_project_boards_offer_only_ideas_not_in_the_project_yet(self):
        self.idea.projects.add(self.project)
        Idea.objects.create(owner=self.user, title="Unrelated", body="x")

        page = self.client.get(reverse("kanban:board"), {"proje": self.project.pk})

        self.assertContains(page, "Unrelated")  # offered in the "add an idea" list
        self.assertEqual(page.content.decode().count('<option value="' + str(self.idea.pk) + '">'), 0)  # already on the board
        self.assertContains(page, "Water app")  # as a card

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


class IdeaCardTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.project = Project.objects.create(owner=self.user, name="Apple Store")
        self.idea = Idea.objects.create(owner=self.user, title="Water app", body="x")

    def statuses(self, project):
        return {t.idea.display_title: t.status for t in services.board_tasks(self.user, project).filter(mirrors_idea=True)}

    def test_ideas_linked_to_a_project_appear_on_its_board_in_the_first_column(self):
        self.idea.projects.add(self.project)

        page = self.client.get(reverse("kanban:board"), {"proje": self.project.pk})

        self.assertEqual(self.statuses(self.project), {"Water app": "todo"})
        self.assertContains(page, "Water app")

    def test_moving_an_idea_card_sticks_and_new_links_arrive_without_disturbing_it(self):
        self.idea.projects.add(self.project)
        self.client.get(reverse("kanban:board"), {"proje": self.project.pk})
        card = Task.objects.get(idea=self.idea)
        self.client.post(reverse("kanban:move", args=[card.pk]), {"status": "doing", "index": "0"})
        other = Idea.objects.create(owner=self.user, title="Second", body="y")
        other.projects.add(self.project)

        self.client.get(reverse("kanban:board"), {"proje": self.project.pk})

        self.assertEqual(self.statuses(self.project), {"Water app": "doing", "Second": "todo"})

    def test_unlinking_an_idea_removes_its_card(self):
        self.idea.projects.add(self.project)
        self.client.get(reverse("kanban:board"), {"proje": self.project.pk})

        self.idea.projects.remove(self.project)
        self.client.get(reverse("kanban:board"), {"proje": self.project.pk})

        self.assertEqual(self.statuses(self.project), {})

    def test_project_boards_never_mirror_ideas_of_other_users(self):
        stranger_idea = Idea.objects.create(owner=make_user("other"), title="Theirs", body="x")
        stranger_idea.projects.add(self.project)  # should not be possible through the UI, but must not leak either

        self.client.get(reverse("kanban:board"), {"proje": self.project.pk})

        self.assertEqual(self.statuses(self.project), {})

    def test_the_personal_board_does_not_mirror_anything_by_itself(self):
        self.idea.projects.add(self.project)

        self.client.get(reverse("kanban:board"))

        self.assertEqual(self.statuses(None), {})

    def test_adding_an_idea_to_the_personal_board_makes_a_card_once(self):
        for _ in range(2):
            self.client.post(reverse("kanban:add-idea"), {"idea": str(self.idea.pk)})

        self.assertEqual(self.statuses(None), {"Water app": "todo"})
        self.assertNotContains(self.client.get(reverse("kanban:board")), f'<option value="{self.idea.pk}">')

    def test_adding_an_idea_on_a_project_board_links_it_to_the_project(self):
        self.client.post(reverse("kanban:add-idea"), {"idea": str(self.idea.pk), "proje": str(self.project.pk)})

        self.assertEqual(list(self.idea.projects.all()), [self.project])
        self.assertEqual(self.statuses(self.project), {"Water app": "todo"})

    def test_only_own_ideas_and_projects_can_be_added(self):
        stranger = make_user("other")
        foreign_idea = Idea.objects.create(owner=stranger, title="Theirs", body="x")
        foreign_project = Project.objects.create(owner=stranger, name="Theirs")

        self.client.post(reverse("kanban:add-idea"), {"idea": str(foreign_idea.pk)})
        denied = self.client.post(reverse("kanban:add-idea"), {"idea": str(self.idea.pk), "proje": str(foreign_project.pk)})

        self.assertEqual(denied.status_code, 404)
        self.assertFalse(Task.objects.exists())

    def test_removing_an_idea_card_from_a_project_board_unlinks_the_idea_but_keeps_it(self):
        self.idea.projects.add(self.project)
        self.client.get(reverse("kanban:board"), {"proje": self.project.pk})
        card = Task.objects.get(idea=self.idea)

        self.client.post(reverse("kanban:delete", args=[card.pk]))
        self.client.get(reverse("kanban:board"), {"proje": self.project.pk})  # the card must not come back

        self.assertFalse(Task.objects.exists())
        self.assertTrue(Idea.objects.filter(pk=self.idea.pk).exists())
        self.assertEqual(self.idea.projects.count(), 0)

    def test_removing_an_idea_card_from_the_personal_board_keeps_the_idea_and_its_projects(self):
        self.idea.projects.add(self.project)
        self.client.post(reverse("kanban:add-idea"), {"idea": str(self.idea.pk)})
        card = Task.objects.get(idea=self.idea, project=None)

        self.client.post(reverse("kanban:delete", args=[card.pk]))

        self.assertFalse(Task.objects.filter(project=None).exists())
        self.assertEqual(list(self.idea.projects.all()), [self.project])

    def test_idea_cards_cannot_be_renamed_from_the_board(self):
        self.client.post(reverse("kanban:add-idea"), {"idea": str(self.idea.pk)})
        card = Task.objects.get()

        response = self.client.post(reverse("kanban:rename", args=[card.pk]), {"title": "Other"})

        self.assertEqual(response.status_code, 400)
        self.idea.refresh_from_db()
        self.assertEqual(self.idea.title, "Water app")

    def test_deleting_an_idea_removes_its_card_from_every_board(self):
        self.idea.projects.add(self.project)
        self.client.post(reverse("kanban:add-idea"), {"idea": str(self.idea.pk)})
        self.client.get(reverse("kanban:board"), {"proje": self.project.pk})

        self.idea.delete()
        personal = self.client.get(reverse("kanban:board"))

        self.assertEqual(personal.status_code, 200)
        self.assertFalse(Task.objects.filter(mirrors_idea=True).exists())

    def test_the_card_shows_the_ideas_live_title_and_feature_progress(self):
        from ideas.models import Feature

        self.client.post(reverse("kanban:add-idea"), {"idea": str(self.idea.pk)})
        Feature.objects.create(idea=self.idea, text="a", is_done=True)
        Feature.objects.create(idea=self.idea, text="b")
        self.idea.title = "Renamed elsewhere"
        self.idea.save()

        page = self.client.get(reverse("kanban:board"))

        self.assertContains(page, "Renamed elsewhere")
        self.assertContains(page, "1/2 özellik")


class ChatToBoardTests(TestCase):
    def setUp(self):
        from ai.chat import ChatAction
        from ideas import chat_service
        from ideas.chat_context import ChatScope

        self.user = make_user()
        self.project = Project.objects.create(owner=self.user, name="Apple Store")
        self.ChatAction, self.chat_service, self.ChatScope = ChatAction, chat_service, ChatScope

    def propose(self, scope, *actions):
        from ai.chat import ChatAssistant, ChatReply

        class Stub(ChatAssistant):
            def __init__(self):
                pass

            def respond(self, context, history):
                return ChatReply("ok", list(actions))

        conversation = self.chat_service.start_conversation(scope, "hi")
        return self.chat_service.ask_assistant(conversation, lambda: Stub())

    def test_an_idea_accepted_in_the_general_chat_lands_on_the_personal_board(self):
        message = self.propose(self.ChatScope(self.user), self.ChatAction("new_idea", "Evde yapılacak bir şey"))

        self.chat_service.decide_action(message, 0, apply=True)

        idea = Idea.objects.get()
        card = Task.objects.get()
        self.assertEqual((card.idea, card.project, card.status, card.mirrors_idea), (idea, None, "todo", True))

    def test_an_idea_from_a_project_chat_lands_on_that_projects_board_and_not_the_personal_one(self):
        message = self.propose(self.ChatScope(self.user, project=self.project), self.ChatAction("new_idea", "Store listing"))

        self.chat_service.decide_action(message, 0, apply=True)
        self.client.force_login(self.user)
        self.client.get(reverse("kanban:board"), {"proje": self.project.pk})

        self.assertEqual(list(Task.objects.values_list("project", flat=True)), [self.project.pk])

    def test_declining_the_suggestion_creates_nothing(self):
        message = self.propose(self.ChatScope(self.user), self.ChatAction("new_idea", "Nope"))

        self.chat_service.decide_action(message, 0, apply=False)

        self.assertFalse(Idea.objects.exists())
        self.assertFalse(Task.objects.exists())
