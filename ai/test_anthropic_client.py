from django.test import SimpleTestCase

from ai.anthropic_client import AnthropicClient
from ai.errors import AIProviderError, AIRateLimitError, AIResponseError
from ai.providers import build_default_client
from ai.test_client import FakeProviderServer


def message(text: str, stop_reason: str = "end_turn", blocks: list | None = None) -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": blocks if blocks is not None else [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 3, "output_tokens": 5},
    }


def error_body(kind: str, text: str) -> dict:
    return {"type": "error", "error": {"type": kind, "message": text}}


class AnthropicClientTests(SimpleTestCase):
    def client_for(self, server):
        # The SDK appends /v1/messages itself, so the fake server's /v1 suffix is dropped.
        return AnthropicClient("anthropic", "claude-opus-5-5", "sk-secret", timeout=5, base_url=server.url.removesuffix("/v1"))

    def serve(self, status=200, body=None):
        server = FakeProviderServer(status, body)
        self.addCleanup(server.close)
        return server

    def test_sends_system_messages_and_model_and_returns_parsed_object(self):
        server = self.serve(body=message('{"title": "x"}'))

        result = self.client_for(server).chat_json("be brief", [{"role": "user", "content": "hi"}])

        self.assertEqual(result, {"title": "x"})
        sent = server.requests[0]["json"]
        self.assertEqual(server.requests[0]["path"], "/v1/messages")
        self.assertEqual(sent["model"], "claude-opus-5-5")
        self.assertEqual(sent["system"], "be brief")
        self.assertEqual(sent["messages"], [{"role": "user", "content": "hi"}])

    def test_ignores_non_text_blocks_and_joins_text_blocks(self):
        blocks = [{"type": "thinking", "thinking": "hm", "signature": "s"}, {"type": "text", "text": '{"a":'}, {"type": "text", "text": " 1}"}]
        server = self.serve(body=message("", blocks=blocks))

        self.assertEqual(self.client_for(server).complete_json("s", "u"), {"a": 1})

    def test_a_refusal_is_a_response_error_so_the_chain_moves_on(self):
        server = self.serve(body=message("", stop_reason="refusal", blocks=[]))

        with self.assertRaises(AIResponseError):
            self.client_for(server).complete_json("s", "u")

    def test_non_json_answer_is_a_response_error(self):
        server = self.serve(body=message("I cannot help"))

        with self.assertRaises(AIResponseError):
            self.client_for(server).complete_json("s", "u")

    def test_http_429_is_a_rate_limit_error(self):
        server = self.serve(429, error_body("rate_limit_error", "slow down"))

        with self.assertRaises(AIRateLimitError):
            self.client_for(server).complete_json("s", "u")

    def test_auth_failure_is_a_provider_error_and_never_leaks_the_key(self):
        server = self.serve(401, error_body("authentication_error", "invalid x-api-key"))

        with self.assertRaises(AIProviderError) as raised:
            self.client_for(server).complete_json("s", "u")

        self.assertIn("401", str(raised.exception))
        self.assertNotIn("sk-secret", str(raised.exception))

    def test_unreachable_server_is_a_provider_error(self):
        server = self.serve()
        client = self.client_for(server)
        server.close()

        with self.assertRaises(AIProviderError):
            client.complete_json("s", "u")

    def test_lists_model_ids_sorted(self):
        body = {"data": [{"id": "claude-b", "type": "model", "display_name": "B", "created_at": "2026-01-01T00:00:00Z"},
                         {"id": "claude-a", "type": "model", "display_name": "A", "created_at": "2026-01-01T00:00:00Z"}],
                "has_more": False, "first_id": "claude-b", "last_id": "claude-a"}
        server = self.serve(body=body)

        self.assertEqual(self.client_for(server).list_models(), ["claude-a", "claude-b"])


class AnthropicProviderTests(SimpleTestCase):
    def test_needs_a_key_and_defaults_to_opus(self):
        with self.assertLogs("ai.providers", level="WARNING"):
            skipped = build_default_client({"AI_PROVIDERS": "anthropic"})
        configured = build_default_client({"AI_PROVIDERS": "anthropic", "ANTHROPIC_API_KEY": "k"})

        self.assertEqual(skipped._clients, [])
        self.assertEqual(configured._clients[0].name, "anthropic")
        self.assertEqual(configured._clients[0]._model, "claude-opus-5-5")

    def test_model_can_be_overridden(self):
        client = build_default_client({"AI_PROVIDERS": "anthropic", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_MODEL": "claude-haiku-5-5"})

        self.assertEqual(client._clients[0]._model, "claude-haiku-5-5")
