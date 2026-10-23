import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from django.test import SimpleTestCase

from ai.client import OpenAICompatibleClient, parse_json_object
from ai.errors import AIProviderError, AIRateLimitError, AIResponseError


class FakeProviderServer:
    """A real local HTTP server speaking just enough of the chat-completions protocol."""

    def __init__(self, status: int = 200, body: str | dict = ""):
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                outer.requests.append(
                    {
                        "path": self.path,
                        "auth": self.headers.get("Authorization"),
                        "user_agent": self.headers.get("User-Agent"),
                        "json": json.loads(self.rfile.read(length)),
                    }
                )
                payload = body if isinstance(body, str) else json.dumps(body)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload.encode())

            def do_GET(self):
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "method": "GET"})
                payload = body if isinstance(body, str) else json.dumps(body)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload.encode())

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/v1"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


def chat_reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


class OpenAICompatibleClientTests(SimpleTestCase):
    def serve(self, status=200, body=""):
        server = FakeProviderServer(status, body)
        self.addCleanup(server.close)
        return server

    def client_for(self, server, api_key="secret-key"):
        return OpenAICompatibleClient("fake", server.url, "test-model", api_key=api_key, timeout=5)

    def test_sends_json_mode_request_with_auth_and_returns_parsed_object(self):
        server = self.serve(body=chat_reply('{"title": "Hi"}'))

        result = self.client_for(server).complete_json("be helpful", "an idea")

        self.assertEqual(result, {"title": "Hi"})
        request = server.requests[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["auth"], "Bearer secret-key")
        self.assertEqual(request["json"]["model"], "test-model")
        self.assertEqual(request["json"]["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in request["json"]["messages"]], ["system", "user"])

    def test_sends_a_custom_user_agent_because_cloudflare_blocks_urllibs_default(self):
        server = self.serve(body=chat_reply("{}"))

        self.client_for(server).complete_json("s", "u")

        self.assertEqual(server.requests[0]["user_agent"], "idealar/1.0")
        self.assertNotIn("urllib", server.requests[0]["user_agent"])

    def test_omits_auth_header_without_api_key(self):
        server = self.serve(body=chat_reply("{}"))

        self.client_for(server, api_key="").complete_json("s", "u")

        self.assertIsNone(server.requests[0]["auth"])

    def test_http_429_is_a_rate_limit_error(self):
        server = self.serve(status=429, body='{"error": "slow down"}')

        with self.assertRaises(AIRateLimitError):
            self.client_for(server).complete_json("s", "u")

    def test_http_500_is_a_provider_error_and_never_leaks_the_key(self):
        server = self.serve(status=500, body="boom")

        with self.assertRaises(AIProviderError) as caught:
            self.client_for(server).complete_json("s", "u")

        self.assertNotIn("secret-key", str(caught.exception))

    def test_unreachable_server_is_a_provider_error(self):
        server = self.serve()
        client = self.client_for(server)
        server.close()

        with self.assertRaises(AIProviderError):
            client.complete_json("s", "u")

    def test_unexpected_response_shape_is_a_response_error(self):
        server = self.serve(body={"unexpected": True})

        with self.assertRaises(AIResponseError):
            self.client_for(server).complete_json("s", "u")

    def test_non_json_content_is_a_response_error(self):
        server = self.serve(body=chat_reply("sorry, I cannot do that"))

        with self.assertRaises(AIResponseError):
            self.client_for(server).complete_json("s", "u")


class ListModelsTests(SimpleTestCase):
    def test_lists_model_ids_sorted_using_the_models_endpoint(self):
        server = FakeProviderServer(body={"data": [{"id": "b-model"}, {"id": "a-model"}]})
        self.addCleanup(server.close)

        models = OpenAICompatibleClient("fake", server.url, "m", api_key="k", timeout=5).list_models()

        self.assertEqual(models, ["a-model", "b-model"])
        self.assertEqual((server.requests[0]["path"], server.requests[0]["auth"]), ("/v1/models", "Bearer k"))

    def test_unexpected_shape_is_a_response_error(self):
        server = FakeProviderServer(body={"nope": 1})
        self.addCleanup(server.close)

        with self.assertRaises(AIResponseError):
            OpenAICompatibleClient("fake", server.url, "m", timeout=5).list_models()


class ParseJsonObjectTests(SimpleTestCase):
    def test_accepts_markdown_fenced_json(self):
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_accepts_text_around_the_object(self):
        self.assertEqual(parse_json_object('Here you go: {"a": 1} Hope it helps!'), {"a": 1})

    def test_rejects_invalid_and_non_object_json(self):
        for text in ("", "{broken", "[1, 2]"):
            with self.assertRaises(AIResponseError):
                parse_json_object(text)
