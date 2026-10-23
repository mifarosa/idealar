from django.test import SimpleTestCase

from ai.errors import AINotConfiguredError
from ai.providers import build_default_client


def names(client) -> list[str]:
    return [c.name for c in client._clients]


class ProviderChainTests(SimpleTestCase):
    def test_default_chain_is_groq_then_ollama(self):
        client = build_default_client({"GROQ_API_KEY": "k"})

        self.assertEqual(names(client), ["groq", "ollama"])

    def test_groq_is_skipped_without_key_leaving_ollama(self):
        with self.assertLogs("ai.providers", level="WARNING"):
            client = build_default_client({})

        self.assertEqual(names(client), ["ollama"])

    def test_order_follows_ai_providers_setting(self):
        environ = {"AI_PROVIDERS": "ollama, groq", "GROQ_API_KEY": "k"}

        self.assertEqual(names(build_default_client(environ)), ["ollama", "groq"])

    def test_unknown_provider_name_fails_loudly(self):
        with self.assertRaises(AINotConfiguredError):
            build_default_client({"AI_PROVIDERS": "skynet"})

    def test_openrouter_needs_key_and_model(self):
        with self.assertLogs("ai.providers", level="WARNING"):
            skipped = build_default_client({"AI_PROVIDERS": "openrouter", "OPENROUTER_API_KEY": "k"})
        configured = build_default_client(
            {"AI_PROVIDERS": "openrouter", "OPENROUTER_API_KEY": "k", "OPENROUTER_MODEL": "some/model:free"}
        )

        self.assertEqual(names(skipped), [])
        self.assertEqual(names(configured), ["openrouter"])

    def test_ollama_url_and_model_come_from_environment(self):
        client = build_default_client(
            {"AI_PROVIDERS": "ollama", "OLLAMA_BASE_URL": "http://host.docker.internal:11434/", "OLLAMA_MODEL": "tiny"}
        )

        ollama = client._clients[0]
        self.assertEqual(ollama._chat_url, "http://host.docker.internal:11434/v1/chat/completions")
        self.assertEqual(ollama._model, "tiny")
