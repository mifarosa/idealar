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

    def test_gemini_needs_only_a_key_and_can_sit_between_groq_and_ollama(self):
        base = {"AI_PROVIDERS": "groq,gemini,ollama", "GROQ_API_KEY": "k"}
        with self.assertLogs("ai.providers", level="WARNING"):
            without_key = build_default_client(base)
        configured = build_default_client({**base, "GEMINI_API_KEY": "g"})

        self.assertEqual(names(without_key), ["groq", "ollama"])
        self.assertEqual(names(configured), ["groq", "gemini", "ollama"])
        gemini = configured._clients[1]
        self.assertIn("generativelanguage.googleapis.com", gemini._chat_url)
        self.assertEqual(gemini._model, "gemini-flash-lite-latest")

    def test_gemini_model_can_be_overridden(self):
        client = build_default_client({"AI_PROVIDERS": "gemini", "GEMINI_API_KEY": "g", "GEMINI_MODEL": "gemini-x"})

        self.assertEqual(client._clients[0]._model, "gemini-x")

    def test_ollama_url_and_model_come_from_environment(self):
        client = build_default_client(
            {"AI_PROVIDERS": "ollama", "OLLAMA_BASE_URL": "http://host.docker.internal:11434/", "OLLAMA_MODEL": "tiny"}
        )

        ollama = client._clients[0]
        self.assertEqual(ollama._chat_url, "http://host.docker.internal:11434/v1/chat/completions")
        self.assertEqual(ollama._model, "tiny")


class PreferredProviderTests(SimpleTestCase):
    ENVIRON = {"AI_PROVIDERS": "groq,gemini,ollama", "GROQ_API_KEY": "k", "GEMINI_API_KEY": "g"}

    def test_preferred_provider_goes_first_and_others_keep_their_order(self):
        client = build_default_client(self.ENVIRON, preferred="gemini")

        self.assertEqual(names(client), ["gemini", "groq", "ollama"])

    def test_unknown_or_missing_preference_keeps_the_configured_order(self):
        self.assertEqual(names(build_default_client(self.ENVIRON, preferred="skynet")), ["groq", "gemini", "ollama"])
        self.assertEqual(names(build_default_client(self.ENVIRON, preferred=None)), ["groq", "gemini", "ollama"])

    def test_configured_names_list_only_usable_providers_without_logging(self):
        from ai.providers import configured_provider_names

        environ = {"AI_PROVIDERS": "groq,gemini,ollama", "GEMINI_API_KEY": "g"}  # groq has no key

        with self.assertNoLogs("ai.providers", level="WARNING"):
            self.assertEqual(configured_provider_names(environ), ["gemini", "ollama"])
