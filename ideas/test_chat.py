from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ai.chat import ChatAction, ChatAssistant, ChatReply, ChatTurn
from ai.errors import AIProviderError, AllProvidersFailed
from ideas import chat_service
from ideas.chat_context import MAX_CONTEXT_CHARS, ChatScope, build_context
from ideas.models import (
    ACTION_APPLIED,
    ACTION_DISMISSED,
    ACTION_PENDING,
    ROLE_ASSISTANT,
    ROLE_USER,
    ChatMessage,
    Conversation,
    Feature,
    Idea,
    Project,
)


def make_user(name="owner"):
    return get_user_model().objects.create_user(name, password="pw-for-tests-123")


class StubAssistant(ChatAssistant):
    def __init__(self, reply="Fikir güzel.", actions=()):
        self._reply = ChatReply(reply, list(actions))
        self.seen = []

    def respond(self, context, history):
        self.seen.append((context, list(history)))
        return self._reply


class DownAssistant(ChatAssistant):
    def __init__(self):
        pass

    def respond(self, context, history):
        raise AllProvidersFailed([("groq", AIProviderError("down"))])


def stub_factory(assistant):
    return lambda: assistant


class ChatContextTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.project = Project.objects.create(owner=self.user, name="Mobile apps", description="All mobile things")
        self.idea = Idea.objects.create(owner=self.user, title="Water reminder", body="remind me to drink", platforms=["ios"])
        self.idea.projects.add(self.project)
        Feature.objects.create(idea=self.idea, text="Daily goal", is_done=True)
        Feature.objects.create(idea=self.idea, text="Charts")

    def test_idea_context_has_note_platforms_and_feature_states(self):
        context = build_context(ChatScope(self.user, idea=self.idea))

        for expected in (f"[id={self.idea.pk}]", "remind me to drink", "iOS", "[x] Daily goal", "[ ] Charts"):
            self.assertIn(expected, context)

    def test_project_context_lists_its_ideas_only(self):
        Idea.objects.create(owner=self.user, body="unrelated idea")

        context = build_context(ChatScope(self.user, project=self.project))

        self.assertIn("Mobile apps", context)
        self.assertIn("Water reminder", context)
        self.assertNotIn("unrelated idea", context)

    def test_general_context_has_all_own_ideas_but_never_other_users(self):
        Idea.objects.create(owner=make_user("other"), body="somebody else's secret")
        Idea.objects.create(owner=self.user, body="second idea")

        context = build_context(ChatScope(self.user))

        self.assertIn("Water reminder", context)
        self.assertIn("second idea", context)
        self.assertNotIn("secret", context)

    def test_context_is_capped(self):
        Idea.objects.create(owner=self.user, body="x" * 5000)
        for number in range(40):
            Feature.objects.create(idea=self.idea, text=f"feature {number} " + "y" * 100)

        self.assertLessEqual(len(build_context(ChatScope(self.user, project=self.project))), MAX_CONTEXT_CHARS)

    def test_empty_project_context_says_so(self):
        empty = Project.objects.create(owner=self.user, name="Empty")

        self.assertIn("No ideas", build_context(ChatScope(self.user, project=empty)))


class ChatServiceTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.idea = Idea.objects.create(owner=self.user, body="habit app")
        self.scope = ChatScope(self.user, idea=self.idea)
        self.conversation = chat_service.start_conversation(self.scope, "ne ekleyelim?")

    def test_start_conversation_titles_it_after_the_first_message(self):
        long = chat_service.start_conversation(self.scope, "word " * 40)

        self.assertEqual(self.conversation.title, "ne ekleyelim?")
        self.assertEqual(len(long.title), chat_service.TITLE_CHARS)
        self.assertTrue(long.title.endswith("…"))
        self.assertEqual([m.content for m in self.conversation.messages.all()], ["ne ekleyelim?"])

    def test_reply_is_stored_with_pending_actions_forced_to_scope_idea(self):
        assistant = StubAssistant(actions=[ChatAction("add_feature", "Streaks", idea_id=99999)])

        reply = chat_service.ask_assistant(self.conversation, stub_factory(assistant))

        self.assertEqual(reply.role, ROLE_ASSISTANT)
        self.assertEqual(reply.actions, [{"type": "add_feature", "text": "Streaks", "idea_id": self.idea.pk, "status": ACTION_PENDING}])

    def test_history_is_sent_oldest_first_and_only_from_this_conversation(self):
        other = chat_service.start_conversation(self.scope, "other session")
        assistant = StubAssistant()
        chat_service.ask_assistant(self.conversation, stub_factory(assistant))
        chat_service.save_user_message(self.conversation, "second")

        chat_service.ask_assistant(self.conversation, stub_factory(assistant))

        _, history = assistant.seen[-1]
        self.assertEqual([t.content for t in history], ["ne ekleyelim?", "Fikir güzel.", "second"])
        self.assertEqual(other.messages.count(), 1)

    def test_activity_moves_a_conversation_to_the_top(self):
        newer = chat_service.start_conversation(self.scope, "newer")
        self.assertEqual(self.scope.conversations().first(), newer)

        chat_service.save_user_message(self.conversation, "bump")

        self.assertEqual(self.scope.conversations().first(), self.conversation)

    def test_project_scope_drops_add_feature_for_ideas_outside_the_project(self):
        project = Project.objects.create(owner=self.user, name="P")
        inside = Idea.objects.create(owner=self.user, body="inside")
        inside.projects.add(project)
        conversation = chat_service.start_conversation(ChatScope(self.user, project=project), "hi")
        actions = [ChatAction("add_feature", "ok", inside.pk), ChatAction("add_feature", "bad", self.idea.pk)]

        reply = chat_service.ask_assistant(conversation, stub_factory(StubAssistant(actions=actions)))

        self.assertEqual([a["text"] for a in reply.actions], ["ok"])

    def test_general_scope_drops_other_users_idea_ids(self):
        foreign = Idea.objects.create(owner=make_user("other"), body="theirs")
        conversation = chat_service.start_conversation(ChatScope(self.user), "hi")

        reply = chat_service.ask_assistant(conversation, stub_factory(StubAssistant(actions=[ChatAction("add_feature", "x", foreign.pk)])))

        self.assertEqual(reply.actions, [])

    def test_ai_failure_returns_none_and_keeps_the_user_message(self):
        with self.assertLogs("ideas.chat_service", level="WARNING"):
            reply = chat_service.ask_assistant(self.conversation, stub_factory(DownAssistant()))

        self.assertIsNone(reply)
        self.assertTrue(chat_service.needs_reply(self.conversation))

    def test_factory_failure_is_also_handled(self):
        def broken_factory():
            raise AllProvidersFailed([])

        with self.assertLogs("ideas.chat_service", level="WARNING"):
            self.assertIsNone(chat_service.ask_assistant(self.conversation, broken_factory))

    def test_scopes_keep_separate_conversation_lists(self):
        project = Project.objects.create(owner=self.user, name="P")
        chat_service.start_conversation(ChatScope(self.user, project=project), "about project")
        chat_service.start_conversation(ChatScope(self.user), "general")

        self.assertEqual([c.title for c in self.scope.conversations()], ["ne ekleyelim?"])
        self.assertEqual([c.title for c in ChatScope(self.user).conversations()], ["general"])


class DecideActionTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.idea = Idea.objects.create(owner=self.user, body="habit app")

    def message(self, action, **scope):
        conversation = Conversation.objects.create(owner=self.user, title="t", **scope)
        return ChatMessage.objects.create(
            conversation=conversation, role=ROLE_ASSISTANT, content="c", actions=[{**action, "status": ACTION_PENDING}]
        )

    def test_apply_add_feature_creates_it_and_marks_applied(self):
        message = self.message({"type": "add_feature", "text": "Streaks", "idea_id": self.idea.pk}, idea=self.idea)

        chat_service.decide_action(message, 0, apply=True)

        message.refresh_from_db()
        self.assertEqual(list(self.idea.features.values_list("text", flat=True)), ["Streaks"])
        self.assertEqual(message.actions[0]["status"], ACTION_APPLIED)

    def test_apply_twice_creates_only_one_feature(self):
        message = self.message({"type": "add_feature", "text": "Streaks", "idea_id": self.idea.pk}, idea=self.idea)

        chat_service.decide_action(message, 0, apply=True)
        chat_service.decide_action(message, 0, apply=True)

        self.assertEqual(self.idea.features.count(), 1)

    def test_dismiss_changes_nothing_but_status(self):
        message = self.message({"type": "add_feature", "text": "Streaks", "idea_id": self.idea.pk}, idea=self.idea)

        chat_service.decide_action(message, 0, apply=False)

        self.assertEqual(self.idea.features.count(), 0)
        self.assertEqual(message.actions[0]["status"], ACTION_DISMISSED)

    def test_new_idea_in_project_chat_is_linked_to_the_project(self):
        project = Project.objects.create(owner=self.user, name="P")
        message = self.message({"type": "new_idea", "text": "A brand new idea", "idea_id": None}, project=project)

        chat_service.decide_action(message, 0, apply=True)

        new_idea = Idea.objects.get(body="A brand new idea")
        self.assertEqual((new_idea.owner, list(new_idea.projects.all())), (self.user, [project]))

    def test_apply_fails_cleanly_when_target_idea_is_outside_the_conversation(self):
        message = self.message(
            {"type": "add_feature", "text": "x", "idea_id": self.idea.pk}, project=Project.objects.create(owner=self.user, name="P")
        )

        with self.assertRaises(chat_service.ActionNotApplicable):
            chat_service.decide_action(message, 0, apply=True)

        message.refresh_from_db()
        self.assertEqual(message.actions[0]["status"], ACTION_PENDING)


class ChatViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.idea = Idea.objects.create(owner=self.user, body="habit app")
        self.project = Project.objects.create(owner=self.user, name="P")
        self.assistant = StubAssistant(actions=[ChatAction("new_idea", "Sleep tracker")])
        patcher = patch("ideas.chat_service.build_assistant", return_value=self.assistant)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_scope_pages_render_for_the_owner(self):
        for name, args in (("chat", []), ("idea-chat", [self.idea.pk]), ("project-chat", [self.project.pk])):
            self.assertEqual(self.client.get(reverse(f"ideas:{name}", args=args)).status_code, 200)

    def test_starting_a_chat_creates_a_conversation_with_both_messages_and_action_card(self):
        response = self.client.post(reverse("ideas:project-chat", args=[self.project.pk]), {"text": "ne yapalım?"}, follow=True)

        conversation = Conversation.objects.get()
        self.assertEqual((conversation.project, conversation.title), (self.project, "ne yapalım?"))
        self.assertEqual([m.role for m in conversation.messages.all()], [ROLE_USER, ROLE_ASSISTANT])
        self.assertContains(response, "Fikir güzel.")
        self.assertContains(response, "Sleep tracker")

    def test_each_new_chat_is_its_own_session_and_the_list_shows_them(self):
        url = reverse("ideas:chat")
        self.client.post(url, {"text": "first topic"})
        self.client.post(url, {"text": "second topic"})

        response = self.client.get(url)

        self.assertEqual(Conversation.objects.count(), 2)
        self.assertContains(response, "first topic")
        self.assertContains(response, "second topic")

    def test_empty_start_does_nothing(self):
        self.client.post(reverse("ideas:chat"), {"text": "  "})

        self.assertEqual(Conversation.objects.count(), 0)

    def test_replying_inside_a_conversation_appends_to_it(self):
        conversation = chat_service.start_conversation(ChatScope(self.user), "topic")

        self.client.post(reverse("ideas:conversation", args=[conversation.pk]), {"text": "follow up"})

        self.assertEqual([m.role for m in conversation.messages.all()], [ROLE_USER, ROLE_USER, ROLE_ASSISTANT])

    def test_ai_failure_keeps_message_and_offers_retry(self):
        self.assistant.respond = DownAssistant().respond

        with self.assertLogs("ideas.chat_service", level="WARNING"):
            response = self.client.post(reverse("ideas:chat"), {"text": "merhaba"}, follow=True)

        self.assertContains(response, "AI şu an yanıt veremedi")
        self.assertContains(response, "Tekrar dene")
        self.assertEqual(ChatMessage.objects.filter(role=ROLE_USER).count(), 1)

    def test_retry_with_empty_post_asks_again_without_duplicating_the_user_message(self):
        conversation = chat_service.start_conversation(ChatScope(self.user), "merhaba")

        self.client.post(reverse("ideas:conversation", args=[conversation.pk]), {"text": ""})

        self.assertEqual([m.role for m in conversation.messages.all()], [ROLE_USER, ROLE_ASSISTANT])

    def test_delete_removes_only_that_conversation(self):
        scope = ChatScope(self.user)
        doomed = chat_service.start_conversation(scope, "doomed")
        kept = chat_service.start_conversation(scope, "kept")

        response = self.client.post(reverse("ideas:conversation-delete", args=[doomed.pk]))

        self.assertRedirects(response, reverse("ideas:chat"), fetch_redirect_response=False)
        self.assertEqual(list(Conversation.objects.all()), [kept])
        self.assertFalse(ChatMessage.objects.filter(conversation_id=doomed.pk).exists())

    def test_deleting_an_idea_deletes_its_conversations(self):
        chat_service.start_conversation(ChatScope(self.user, idea=self.idea), "about idea")

        self.idea.delete()

        self.assertEqual(Conversation.objects.count(), 0)

    def test_apply_action_via_button_adds_feature(self):
        conversation = Conversation.objects.create(owner=self.user, idea=self.idea, title="t")
        message = ChatMessage.objects.create(
            conversation=conversation, role=ROLE_ASSISTANT, content="c",
            actions=[{"type": "add_feature", "text": "Streaks", "idea_id": self.idea.pk, "status": ACTION_PENDING}],
        )

        response = self.client.post(reverse("ideas:chat-action", args=[message.pk, 0]), {"decision": "apply"})

        self.assertRedirects(response, reverse("ideas:conversation", args=[conversation.pk]))
        self.assertEqual(list(self.idea.features.values_list("text", flat=True)), ["Streaks"])
        message.refresh_from_db()
        self.assertEqual(message.actions[0]["status"], ACTION_APPLIED)

    def test_action_index_out_of_range_is_ignored(self):
        conversation = Conversation.objects.create(owner=self.user, title="t")
        message = ChatMessage.objects.create(conversation=conversation, role=ROLE_ASSISTANT, content="c", actions=[])

        response = self.client.post(reverse("ideas:chat-action", args=[message.pk, 5]), {"decision": "apply"})

        self.assertEqual(response.status_code, 302)

    def test_message_longer_than_limit_is_truncated(self):
        self.client.post(reverse("ideas:chat"), {"text": "x" * 9000})

        self.assertEqual(len(ChatMessage.objects.get(role=ROLE_USER).content), 4000)


class ChatIsolationTests(TestCase):
    def setUp(self):
        owner = make_user("owner")
        self.idea = Idea.objects.create(owner=owner, body="private")
        self.project = Project.objects.create(owner=owner, name="Private")
        self.conversation = Conversation.objects.create(owner=owner, title="secret chat")
        self.message = ChatMessage.objects.create(
            conversation=self.conversation, role=ROLE_ASSISTANT, content="c",
            actions=[{"type": "new_idea", "text": "x", "idea_id": None, "status": ACTION_PENDING}],
        )
        self.client.force_login(make_user("intruder"))

    def test_other_users_chats_and_actions_are_404(self):
        self.assertEqual(self.client.get(reverse("ideas:idea-chat", args=[self.idea.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("ideas:project-chat", args=[self.project.pk]), {"text": "hi"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("ideas:conversation", args=[self.conversation.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("ideas:conversation", args=[self.conversation.pk]), {"text": "hi"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("ideas:conversation-delete", args=[self.conversation.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("ideas:chat-action", args=[self.message.pk, 0]), {"decision": "apply"}).status_code, 404)
        self.assertFalse(Idea.objects.filter(body="x").exists())
        self.assertTrue(Conversation.objects.filter(pk=self.conversation.pk).exists())

    def test_general_chat_list_never_shows_other_users_conversations(self):
        self.assertNotContains(self.client.get(reverse("ideas:chat")), "secret chat")

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()

        self.assertEqual(self.client.get(reverse("ideas:chat")).status_code, 302)
