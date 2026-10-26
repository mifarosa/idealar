from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from ai.anthropic_client import AnthropicClient
from ai.client import OpenAICompatibleClient
from ai.errors import AINotConfiguredError
from ai.providers import ModelSpec, build_chain, build_client, specs_from_environment
from ai.test_client import FakeProviderServer, chat_reply
from ideas import ai_registry
from ideas.models import AIModel, ChatMessage, Conversation


def make_user(name="owner", staff=True):
    return get_user_model().objects.create_user(name, password="pw-for-tests-123", is_staff=staff)


class BuildClientTests(SimpleTestCase):
    def test_openai_style_kinds_use_their_fixed_endpoint(self):
        client = build_client(ModelSpec("m1", "Groq", "groq", "some-model", key_env="GROQ_API_KEY"), {"GROQ_API_KEY": "k"})

        self.assertIsInstance(client, OpenAICompatibleClient)
        self.assertIn("api.groq.com", client._chat_url)

    def test_fixed_kinds_ignore_a_stored_address(self):
        spec = ModelSpec("m1", "Groq", "groq", "x", base_url="http://evil.example", key_env="GROQ_API_KEY")

        self.assertIn("api.groq.com", build_client(spec, {"GROQ_API_KEY": "k"})._chat_url)

    def test_claude_uses_the_sdk_client(self):
        spec = ModelSpec("m1", "Claude", "anthropic", "claude-haiku-5-5", key_env="ANTHROPIC_API_KEY")

        self.assertIsInstance(build_client(spec, {"ANTHROPIC_API_KEY": "k"}), AnthropicClient)

    def test_ollama_gets_the_v1_suffix_and_needs_no_key(self):
        client = build_client(ModelSpec("m1", "Local", "ollama", "tiny", base_url="http://host:11434"), {})

        self.assertEqual(client._chat_url, "http://host:11434/v1/chat/completions")

    def test_custom_server_uses_the_address_as_given(self):
        client = build_client(ModelSpec("m1", "LM Studio", "custom", "m", base_url="http://host:1234/v1/"), {})

        self.assertEqual(client._chat_url, "http://host:1234/v1/chat/completions")

    def test_missing_key_or_address_is_not_configured(self):
        with self.assertRaises(AINotConfiguredError):
            build_client(ModelSpec("m1", "Groq", "groq", "x", key_env="GROQ_API_KEY"), {})
        with self.assertRaises(AINotConfiguredError):
            build_client(ModelSpec("m1", "Other", "custom", "x"), {})

    def test_chain_skips_unusable_models_and_moves_the_preferred_first(self):
        specs = [
            ModelSpec("m1", "Groq", "groq", "a", key_env="GROQ_API_KEY"),
            ModelSpec("m2", "Groq no key", "gemini", "b", key_env="GEMINI_API_KEY"),
            ModelSpec("m3", "Local", "ollama", "c", base_url="http://h:1"),
        ]

        with self.assertLogs("ai.providers", level="WARNING"):
            chain = build_chain(specs, {"GROQ_API_KEY": "k"}, preferred="m3")

        self.assertEqual([client.name for client in chain._clients], ["m3", "m1"])

    def test_environment_chain_becomes_model_definitions(self):
        environ = {"AI_PROVIDERS": "groq,ollama", "GROQ_MODEL": "g-model", "OLLAMA_BASE_URL": "http://h:11434/"}

        specs = specs_from_environment(environ)

        self.assertEqual([(s.kind, s.model, s.base_url, s.key_env) for s in specs],
                         [("groq", "g-model", "", "GROQ_API_KEY"), ("ollama", "qwen2.5:3b", "http://h:11434", "")])


class RegistryTests(TestCase):
    def test_without_models_the_environment_chain_is_used(self):
        self.assertFalse(ai_registry.uses_database())
        self.assertEqual(ai_registry.label_for("gemini"), "Gemini")

    def test_with_models_only_enabled_ones_form_the_chain_in_order(self):
        second = AIModel.objects.create(kind="ollama", label="Second", model_name="b", base_url="http://h:1", position=2)
        first = AIModel.objects.create(kind="ollama", label="First", model_name="a", base_url="http://h:1", position=1)
        AIModel.objects.create(kind="ollama", label="Off", model_name="c", base_url="http://h:1", position=3, enabled=False)

        self.assertEqual(ai_registry.choices(), [(first.chain_name, "First"), (second.chain_name, "Second")])
        self.assertEqual([c.name for c in ai_registry.build_client()._clients], [first.chain_name, second.chain_name])

    def test_labels_survive_renames_and_deletion(self):
        model = AIModel.objects.create(kind="ollama", label="Mine", model_name="a", base_url="http://h:1")
        name = model.chain_name

        self.assertEqual(ai_registry.label_for(name), "Mine")
        model.delete()
        self.assertEqual(ai_registry.label_for(name), "silinmiş model")
        self.assertEqual(ai_registry.label_for("groq"), "Groq")


class SettingsPageTests(TestCase):
    def setUp(self):
        self.staff = make_user()
        self.client.force_login(self.staff)

    def create(self, **overrides):
        data = {"kind": "ollama", "label": "Local", "model_name": "tiny", "base_url": "http://h:11434", "key_env": "", "enabled": "on"}
        return self.client.post(reverse("ideas:ai-model-create"), {**data, **overrides})

    def test_non_staff_users_are_forbidden_everywhere(self):
        self.client.force_login(make_user("plain", staff=False))
        model = AIModel.objects.create(kind="ollama", label="L", model_name="a", base_url="http://h:1")

        for url in [reverse("ideas:ai-models"), reverse("ideas:ai-model-create"), reverse("ideas:ai-model-update", args=[model.pk]),
                    reverse("ideas:ai-model-available", args=[model.pk])]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        response = self.client.post(reverse("ideas:ai-model-action", args=[model.pk, "delete"]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(AIModel.objects.exists())

    def test_anonymous_users_are_sent_to_login(self):
        self.client.logout()

        self.assertEqual(self.client.get(reverse("ideas:ai-models")).status_code, 302)

    def test_empty_list_offers_to_import_the_environment_chain(self):
        page = self.client.get(reverse("ideas:ai-models"))
        self.assertContains(page, "ayarlarımı listeye aktar")

        self.client.post(reverse("ideas:ai-model-import-env"))

        self.assertTrue(AIModel.objects.exists())
        self.assertNotContains(self.client.get(reverse("ideas:ai-models")), "ayarlarımı listeye aktar")

    def test_adding_a_local_model_appends_it_to_the_end(self):
        self.create(label="One")
        self.create(label="Two", model_name="other")

        self.assertEqual(list(AIModel.objects.values_list("label", flat=True)), ["One", "Two"])

    def test_label_and_key_variable_default_from_the_kind(self):
        self.create(kind="groq", label="", key_env="", base_url="")

        model = AIModel.objects.get()
        self.assertEqual((model.label, model.key_env, model.base_url), ("Groq", "GROQ_API_KEY", ""))

    def test_key_variable_must_look_like_an_api_key_name(self):
        response = self.create(kind="custom", key_env="SECRET_KEY", base_url="http://h:1/v1")

        self.assertContains(response, "_API_KEY ile bitmeli")
        self.assertFalse(AIModel.objects.exists())

    def test_local_kinds_need_a_valid_address(self):
        for bad in ["", "ftp://x", "javascript:alert(1)", "not a url"]:
            response = self.create(base_url=bad)
            self.assertContains(response, "http://", msg_prefix=bad)
        self.assertFalse(AIModel.objects.exists())

    def test_editing_changes_the_model_name(self):
        model = AIModel.objects.create(kind="ollama", label="L", model_name="old", base_url="http://h:1")

        self.client.post(reverse("ideas:ai-model-update", args=[model.pk]),
                         {"kind": "ollama", "label": "L", "model_name": "new", "base_url": "http://h:1", "key_env": ""})

        model.refresh_from_db()
        self.assertEqual(model.model_name, "new")
        self.assertFalse(model.enabled)  # unchecked box means off

    def test_toggle_move_and_delete(self):
        a = AIModel.objects.create(kind="ollama", label="A", model_name="a", base_url="http://h:1", position=1)
        b = AIModel.objects.create(kind="ollama", label="B", model_name="b", base_url="http://h:1", position=1)  # tie on purpose

        self.client.post(reverse("ideas:ai-model-action", args=[b.pk, "up"]))
        self.assertEqual([m.label for m in AIModel.objects.all()], ["B", "A"])
        self.client.post(reverse("ideas:ai-model-action", args=[b.pk, "up"]))  # already first: no change
        self.assertEqual([m.label for m in AIModel.objects.all()], ["B", "A"])
        self.client.post(reverse("ideas:ai-model-action", args=[a.pk, "toggle"]))
        a.refresh_from_db()
        self.assertFalse(a.enabled)
        self.client.post(reverse("ideas:ai-model-action", args=[a.pk, "delete"]))
        self.assertEqual([m.label for m in AIModel.objects.all()], ["B"])

    def test_unknown_action_is_a_404_and_actions_need_post(self):
        model = AIModel.objects.create(kind="ollama", label="A", model_name="a", base_url="http://h:1")

        self.assertEqual(self.client.post(reverse("ideas:ai-model-action", args=[model.pk, "explode"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("ideas:ai-model-action", args=[model.pk, "delete"])).status_code, 405)

    def test_test_button_reports_success_and_failure(self):
        server = FakeProviderServer(200, chat_reply('{"ok": true}'))
        self.addCleanup(server.close)
        good = AIModel.objects.create(kind="custom", label="Good", model_name="m", base_url=server.url)
        bad = AIModel.objects.create(kind="custom", label="Bad", model_name="m", base_url="http://127.0.0.1:9/v1")

        ok = self.client.post(reverse("ideas:ai-model-action", args=[good.pk, "test"]), follow=True)
        failed = self.client.post(reverse("ideas:ai-model-action", args=[bad.pk, "test"]), follow=True)

        self.assertContains(ok, "çalışıyor")
        self.assertContains(failed, "çalışmadı")

    def test_available_models_are_listed_and_can_be_picked(self):
        server = FakeProviderServer(200, {"data": [{"id": "model-b"}, {"id": "model-a"}]})
        self.addCleanup(server.close)
        model = AIModel.objects.create(kind="custom", label="Srv", model_name="model-a", base_url=server.url)

        page = self.client.get(reverse("ideas:ai-model-available", args=[model.pk]))
        self.assertContains(page, "model-b")
        self.client.post(reverse("ideas:ai-model-action", args=[model.pk, "use"]), {"model_name": "model-b"})

        model.refresh_from_db()
        self.assertEqual(model.model_name, "model-b")

    def test_unreachable_provider_shows_an_error_instead_of_crashing(self):
        model = AIModel.objects.create(kind="custom", label="Srv", model_name="m", base_url="http://127.0.0.1:9/v1")

        page = self.client.get(reverse("ideas:ai-model-available", args=[model.pk]))

        self.assertContains(page, "Liste alınamadı")

    def test_old_chat_messages_show_the_label_of_a_database_model(self):
        model = AIModel.objects.create(kind="ollama", label="Home PC", model_name="a", base_url="http://h:1")
        conversation = Conversation.objects.create(owner=self.staff, title="t")
        ChatMessage.objects.create(conversation=conversation, role="assistant", content="hi", provider=model.chain_name)

        page = self.client.get(reverse("ideas:conversation", args=[conversation.pk]))

        self.assertContains(page, "Yanıtlayan: Home PC")
