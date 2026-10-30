from django.test import SimpleTestCase

from ai.chat import MAX_ACTIONS, ChatAction, ChatAssistant, ChatTurn
from ai.client import LLMClient
from ai.errors import AIResponseError


class RecordingClient(LLMClient):
    name = "recording"

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def chat_json(self, system, messages):
        self.calls.append((system, messages))
        return self.answer


def respond(answer, history=(ChatTurn("user", "hi"),), context="ctx"):
    return ChatAssistant(RecordingClient(answer)).respond(context, history)


class ChatAssistantTests(SimpleTestCase):
    def test_reply_and_actions_are_parsed(self):
        result = respond(
            {
                "reply": " Add reminders. ",
                "actions": [
                    {"type": "add_feature", "idea_id": 3, "text": "Reminders"},
                    {"type": "new_idea", "text": "A sleep tracker"},
                ],
            }
        )

        self.assertEqual(result.reply, "Add reminders.")
        self.assertEqual(
            result.actions, [ChatAction("add_feature", "Reminders", 3), ChatAction("new_idea", "A sleep tracker", None)]
        )

    def test_missing_or_blank_reply_is_a_response_error(self):
        for answer in ({}, {"reply": "  "}, {"reply": 5}):
            with self.assertRaises(AIResponseError):
                respond(answer)

    def test_malformed_actions_are_dropped_not_fatal(self):
        bad_actions = [
            "string",
            {"type": "delete_everything", "text": "x"},
            {"type": "add_feature", "text": ""},
            {"type": "add_feature"},
            {"type": "new_idea", "text": 7},
        ]

        self.assertEqual(respond({"reply": "ok", "actions": bad_actions}).actions, [])

    def test_actions_are_capped(self):
        actions = [{"type": "new_idea", "text": f"idea {n}"} for n in range(10)]

        self.assertEqual(len(respond({"reply": "ok", "actions": actions}).actions), MAX_ACTIONS)

    def test_idea_id_is_coerced_safely(self):
        def parsed(value):
            action = {"type": "add_feature", "text": "x", "idea_id": value}
            return respond({"reply": "ok", "actions": [action]}).actions[0].idea_id

        self.assertEqual((parsed("7"), parsed(7), parsed(True), parsed("abc"), parsed(None)), (7, 7, None, None, None))

    def test_context_and_history_reach_the_model_in_order(self):
        client = RecordingClient({"reply": "ok"})
        history = [ChatTurn("user", "first"), ChatTurn("assistant", "second"), ChatTurn("user", "third")]

        ChatAssistant(client).respond("[id=1] Habit app", history)

        system, messages = client.calls[0]
        self.assertIn("[id=1] Habit app", system)
        self.assertEqual([m["content"] for m in messages], ["first", "second", "third"])
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])


class ProviderInfoTests(SimpleTestCase):
    def test_reply_reports_provider_and_failures_from_a_fallback_client(self):
        from ai.fallback import FallbackClient, RunInfo

        class Down(LLMClient):
            name = "groq"

            def chat_json(self, system, messages):
                from ai.errors import AIRateLimitError

                raise AIRateLimitError("limit")

        class Up(LLMClient):
            name = "gemini"

            def chat_json(self, system, messages):
                return {"reply": "merhaba"}

        with self.assertLogs("ai.fallback", level="WARNING"):
            result = ChatAssistant(FallbackClient([Down(), Up()])).respond("ctx", [ChatTurn("user", "hi")])

        self.assertEqual((result.provider, result.failed_providers), ("gemini", ("groq",)))

    def test_plain_client_reports_its_own_name(self):
        result = respond({"reply": "ok"})

        self.assertEqual((result.provider, result.failed_providers), ("recording", ()))


class LinkProjectParseTests(SimpleTestCase):
    def parse(self, *actions):
        client = type("C", (LLMClient,), {"name": "c", "chat_json": lambda self, s, m: {"reply": "ok", "actions": list(actions)}})()
        return ChatAssistant(client).respond("ctx", []).actions

    def test_link_project_needs_no_text_and_reads_both_ids(self):
        [action] = self.parse({"type": "link_project", "idea_id": "4", "project_id": 9})

        self.assertEqual((action.type, action.idea_id, action.project_id, action.text), ("link_project", 4, 9, ""))

    def test_new_idea_may_carry_a_project_id(self):
        [action] = self.parse({"type": "new_idea", "text": "Store text", "project_id": 3})

        self.assertEqual(action.project_id, 3)

    def test_junk_ids_become_none(self):
        [action] = self.parse({"type": "link_project", "idea_id": True, "project_id": "x"})

        self.assertEqual((action.idea_id, action.project_id), (None, None))
