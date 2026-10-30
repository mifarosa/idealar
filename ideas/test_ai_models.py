from django.contrib.auth import get_user_model
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from ai.anthropic_client import AnthropicClient
from ai.client import OpenAICompatibleClient
from ai.errors import AINotConfiguredError, AIProviderError
from ai.providers import ModelSpec, build_chain, build_client, specs_from_environment
from ai.test_client import FakeProviderServer, chat_reply
from ideas import ai_registry
from ideas import key_vault
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


def sealed(owner, key="sk-test-key-123456"):
    return {"api_key_sealed": key_vault.seal(key, owner.pk), "key_hint": key_vault.hint(key)}


class SpecTests(SimpleTestCase):
    def test_api_key_stays_out_of_the_repr(self):
        spec = ModelSpec("m1", "Groq", "groq", "x", api_key="sk-super-secret-value")

        self.assertNotIn("sk-super-secret-value", repr(spec))

    def test_a_key_in_the_spec_is_used_without_any_environment(self):
        client = build_client(ModelSpec("m1", "Groq", "groq", "x", api_key="k"), {})

        self.assertIsInstance(client, OpenAICompatibleClient)


class KeyVaultTests(SimpleTestCase):
    def test_round_trip_and_the_sealed_value_hides_the_key(self):
        token = key_vault.seal("sk-test-key-123456", 7)

        self.assertNotIn("sk-test", token)
        self.assertEqual(key_vault.unseal(token, 7), "sk-test-key-123456")

    def test_a_sealed_key_is_useless_for_any_other_owner(self):
        token = key_vault.seal("sk-test-key-123456", 7)

        with self.assertRaises(key_vault.KeyUnreadable):
            key_vault.unseal(token, 8)

    def test_sealing_twice_gives_different_tokens(self):
        self.assertNotEqual(key_vault.seal("sk-test-key-123456", 7), key_vault.seal("sk-test-key-123456", 7))

    def test_tampered_value_is_unreadable(self):
        token = key_vault.seal("sk-test-key-123456", 7)

        with self.assertRaises(key_vault.KeyUnreadable):
            key_vault.unseal(token[:-4] + "AAAA", 7)

    def test_changed_secret_makes_the_key_unreadable(self):
        token = key_vault.seal("sk-test-key-123456", 7)

        with self.settings(KEYS_ENCRYPTION_KEY="another-secret-another-secret-123"), self.assertRaises(key_vault.KeyUnreadable):
            key_vault.unseal(token, 7)

    def test_rotation_keeps_old_values_readable_until_they_are_resealed(self):
        old = "old-secret-old-secret-old-secret-1"
        with self.settings(KEYS_ENCRYPTION_KEY=old):
            token = key_vault.seal("sk-test-key-123456", 7)

        with self.settings(KEYS_ENCRYPTION_KEY="new-secret-new-secret-new-secret-1", KEYS_ENCRYPTION_KEY_PREVIOUS=[old]):
            self.assertTrue(key_vault.needs_rotation(token))
            self.assertEqual(key_vault.unseal(token, 7), "sk-test-key-123456")
            fresh = key_vault.seal(key_vault.unseal(token, 7), 7)
            self.assertFalse(key_vault.needs_rotation(fresh))

        with self.settings(KEYS_ENCRYPTION_KEY="new-secret-new-secret-new-secret-1"):
            self.assertEqual(key_vault.unseal(fresh, 7), "sk-test-key-123456")

    def test_values_sealed_by_the_first_version_stay_readable(self):
        import base64
        import hashlib

        from cryptography.fernet import Fernet
        from django.conf import settings

        legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"idealar-ai-keys:{settings.SECRET_KEY}".encode()).digest()))
        token = legacy.encrypt(b"sk-legacy-key-123456").decode()

        self.assertEqual(key_vault.unseal(token, 7), "sk-legacy-key-123456")
        self.assertTrue(key_vault.needs_rotation(token))

    def test_hint_shows_only_the_last_four_characters_of_long_keys(self):
        self.assertEqual(key_vault.hint("sk-test-key-123456"), "3456")
        self.assertEqual(key_vault.hint("short"), "")


class RotateCommandTests(TestCase):
    def test_reseals_with_the_current_secret_and_reports_unreadable_ones(self):
        from io import StringIO

        from django.core.management import call_command

        user = make_user("owner", staff=False)
        old = "old-secret-old-secret-old-secret-1"
        with self.settings(KEYS_ENCRYPTION_KEY=old):
            good = AIModel.objects.create(owner=user, kind="groq", label="Good", model_name="m", **sealed(user))
        lost = AIModel.objects.create(owner=user, kind="groq", label="Lost", model_name="m", api_key_sealed="garbage")

        out, err = StringIO(), StringIO()
        with self.settings(KEYS_ENCRYPTION_KEY="new-secret-new-secret-new-secret-1", KEYS_ENCRYPTION_KEY_PREVIOUS=[old]):
            call_command("rotate_ai_keys", stdout=out, stderr=err)
            good.refresh_from_db()
            self.assertFalse(key_vault.needs_rotation(good.api_key_sealed))
            self.assertEqual(key_vault.unseal(good.api_key_sealed, user.pk), "sk-test-key-123456")

        self.assertIn("Re-sealed 1", out.getvalue())
        self.assertIn(f"Model {lost.pk}", err.getvalue())


class SystemCheckTests(SimpleTestCase):
    def test_short_secret_is_an_error_and_a_missing_one_a_warning_outside_debug(self):
        from ideas.checks import key_encryption_secret

        with self.settings(KEYS_ENCRYPTION_KEY="short", DEBUG=False):
            self.assertEqual([m.id for m in key_encryption_secret(None)], ["ideas.E001"])
        with self.settings(KEYS_ENCRYPTION_KEY="", DEBUG=False):
            self.assertEqual([m.id for m in key_encryption_secret(None)], ["ideas.W001"])
        with self.settings(KEYS_ENCRYPTION_KEY="x" * 40, DEBUG=False):
            self.assertEqual(key_encryption_secret(None), [])


class NewProviderTests(SimpleTestCase):
    def test_every_cloud_kind_has_its_own_fixed_endpoint_and_needs_a_key(self):
        for kind in ("openai", "mistral", "deepseek", "xai", "together", "cerebras", "fireworks"):
            client = build_client(ModelSpec("m1", kind, kind, "some-model", api_key="k"), {})

            self.assertIsInstance(client, OpenAICompatibleClient, kind)
            with self.assertRaises(AINotConfiguredError):
                build_client(ModelSpec("m1", kind, kind, "some-model"), {})

    def test_openai_requests_leave_out_temperature_but_others_send_it(self):
        server = FakeProviderServer(200, chat_reply('{"ok": true}'))
        self.addCleanup(server.close)

        for temperature, expected in ((None, False), (0.3, True)):
            OpenAICompatibleClient("x", server.url, "m", api_key="k", temperature=temperature).complete_json("s", "u")
            self.assertEqual("temperature" in server.requests[-1]["json"], expected)

        self.assertIn("api.openai.com", build_client(ModelSpec("m1", "ChatGPT", "openai", "m", api_key="k"), {})._chat_url)
        self.assertIsNone(build_client(ModelSpec("m1", "ChatGPT", "openai", "m", api_key="k"), {})._temperature)


class RegistryTests(TestCase):
    def setUp(self):
        self.user = make_user("owner", staff=False)

    def make(self, label, position, owner=None, **fields):
        fields = {"kind": "groq", "model_name": "m", **sealed(owner or self.user), **fields}
        return AIModel.objects.create(owner=owner or self.user, label=label, position=position, **fields)

    def test_chain_has_only_this_users_enabled_models_in_order(self):
        second = self.make("Second", 2)
        first = self.make("First", 1)
        self.make("Off", 3, enabled=False)
        self.make("Someone else", 1, owner=make_user("other"))

        self.assertEqual(ai_registry.choices(self.user), [(first.chain_name, "First"), (second.chain_name, "Second")])

    def test_decrypted_key_reaches_the_client_and_models_without_a_key_are_skipped(self):
        self.make("With key", 1, api_key_sealed=key_vault.seal("sk-live-abcdefgh", self.user.pk))
        self.make("No key", 2, api_key_sealed="", key_hint="", kind="gemini")

        with self.assertLogs("ai.providers", level="WARNING"):
            clients = ai_registry.build_client(self.user)._clients

        self.assertEqual([c._api_key for c in clients], ["sk-live-abcdefgh"])

    def test_user_without_models_gets_an_empty_chain(self):
        self.assertFalse(ai_registry.has_models(self.user))
        self.assertEqual(ai_registry.build_client(self.user)._clients, [])

    def test_staff_only_kinds_are_ignored_for_regular_users_but_work_for_staff(self):
        for user in (self.user, make_user("boss", staff=True)):
            self.make("Local", 1, owner=user, kind="ollama", base_url="http://h:1", api_key_sealed="", key_hint="")

        self.assertFalse(ai_registry.has_models(self.user))
        self.assertTrue(ai_registry.has_models(AIModel.objects.get(owner__username="boss").owner))

    def test_a_kind_name_as_preference_picks_the_first_model_of_that_kind(self):
        self.make("Groq", 1)
        gemini = self.make("Gem", 2, kind="gemini")

        client = ai_registry.build_client(self.user, preferred="gemini")

        self.assertEqual(client._clients[0].name, gemini.chain_name)

    def test_unreadable_stored_key_is_treated_as_missing_not_a_crash(self):
        self.make("Old", 1)

        with self.settings(KEYS_ENCRYPTION_KEY="rotated"), self.assertLogs("ideas.ai_registry", level="WARNING"), self.assertLogs("ai.providers", level="WARNING"):
            self.assertEqual(ai_registry.build_client(self.user)._clients, [])

    def test_labels_survive_renames_and_deletion(self):
        model = self.make("Mine", 1)
        name = model.chain_name

        self.assertEqual(ai_registry.label_for(name), "Mine")
        model.delete()
        self.assertEqual(ai_registry.label_for(name), "silinmiş model")
        self.assertEqual(ai_registry.label_for("groq"), "Groq")


class SettingsPageTests(TestCase):
    def setUp(self):
        self.user = make_user("owner", staff=False)
        self.client.force_login(self.user)

    def create(self, **overrides):
        data = {"kind": "groq", "label": "", "model_name": "m", "api_key": "sk-test-key-123456", "enabled": "on"}
        return self.client.post(reverse("ideas:ai-model-create"), {**data, **overrides})

    def test_anonymous_users_are_sent_to_login(self):
        self.client.logout()

        self.assertEqual(self.client.get(reverse("ideas:ai-models")).status_code, 302)

    def test_adding_a_model_seals_the_key_and_never_shows_it_again(self):
        self.create()

        model = AIModel.objects.get()
        self.assertEqual((model.owner, model.label, model.key_hint), (self.user, "Groq", "3456"))
        self.assertNotIn("sk-test", model.api_key_sealed)
        for page in (self.client.get(reverse("ideas:ai-models")), self.client.get(reverse("ideas:ai-model-update", args=[model.pk]))):
            self.assertNotContains(page, "sk-test-key-123456")
        self.assertContains(self.client.get(reverse("ideas:ai-models")), "anahtar …3456")

    def test_a_key_is_required_for_cloud_providers(self):
        response = self.create(api_key="")

        self.assertContains(response, "API anahtarı gerekli")
        self.assertFalse(AIModel.objects.exists())

    def test_keys_with_whitespace_are_rejected(self):
        self.assertContains(self.create(api_key="sk-a sk-b"), "boşluk içeremez")

    def test_regular_users_cannot_pick_address_based_kinds(self):
        response = self.create(kind="custom", base_url="http://169.254.169.254/latest", api_key="")

        self.assertContains(response, "Geçerli bir seçenek seçin")
        self.assertFalse(AIModel.objects.exists())

    def test_staff_can_add_a_local_server_with_a_valid_address(self):
        self.client.force_login(make_user("boss", staff=True))

        self.create(kind="ollama", base_url="not a url", api_key="")
        self.assertFalse(AIModel.objects.exists())
        self.create(kind="ollama", base_url="http://h:11434/", api_key="")

        self.assertEqual(AIModel.objects.get().base_url, "http://h:11434")

    def test_editing_keeps_the_key_when_the_field_is_left_blank_and_replaces_it_when_filled(self):
        self.create()
        model = AIModel.objects.get()
        sealed_before = model.api_key_sealed
        url = reverse("ideas:ai-model-update", args=[model.pk])
        base = {"kind": "groq", "label": "Renamed", "model_name": "new-model", "enabled": "on"}

        self.client.post(url, {**base, "api_key": ""})
        model.refresh_from_db()
        self.assertEqual((model.label, model.model_name, model.api_key_sealed), ("Renamed", "new-model", sealed_before))

        self.client.post(url, {**base, "api_key": "sk-another-key-9999"})
        model.refresh_from_db()
        self.assertEqual(key_vault.unseal(model.api_key_sealed, self.user.pk), "sk-another-key-9999")

    def test_changing_the_provider_requires_a_new_key_so_the_old_one_never_travels(self):
        self.create()
        model = AIModel.objects.get()

        response = self.client.post(reverse("ideas:ai-model-update", args=[model.pk]),
                                    {"kind": "gemini", "label": "x", "model_name": "m", "api_key": ""})

        self.assertContains(response, "API anahtarı gerekli")

    def test_users_cannot_see_or_change_each_others_models(self):
        other = make_user("other")
        theirs = AIModel.objects.create(owner=other, kind="groq", label="Theirs", model_name="m", **sealed(other))

        self.assertNotContains(self.client.get(reverse("ideas:ai-models")), "Theirs")
        self.assertEqual(self.client.get(reverse("ideas:ai-model-update", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("ideas:ai-model-available", args=[theirs.pk])).status_code, 404)
        for action in ("delete", "toggle", "up", "test", "use"):
            self.assertEqual(self.client.post(reverse("ideas:ai-model-action", args=[theirs.pk, action])).status_code, 404, action)
        self.assertTrue(AIModel.objects.filter(pk=theirs.pk).exists())

    def test_env_import_is_for_staff_only_and_copies_keys_sealed(self):
        self.assertEqual(self.client.post(reverse("ideas:ai-model-import-env")).status_code, 403)

        self.client.force_login(make_user("boss", staff=True))
        environ = {"AI_PROVIDERS": "groq,gemini,ollama", "GROQ_API_KEY": "sk-from-env-0001"}  # gemini has no key
        with patch.dict("os.environ", environ, clear=True):
            self.client.post(reverse("ideas:ai-model-import-env"))

        models = {m.kind: m for m in AIModel.objects.all()}
        self.assertEqual(set(models), {"groq", "ollama"})
        self.assertEqual(key_vault.unseal(models["groq"].api_key_sealed, models["groq"].owner_id), "sk-from-env-0001")

    def test_toggle_move_and_delete(self):
        a = AIModel.objects.create(owner=self.user, kind="groq", label="A", model_name="a", position=1, **sealed(self.user))
        b = AIModel.objects.create(owner=self.user, kind="groq", label="B", model_name="b", position=1, **sealed(self.user))  # tie on purpose

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
        model = AIModel.objects.create(owner=self.user, kind="groq", label="A", model_name="a", **sealed(self.user))

        self.assertEqual(self.client.post(reverse("ideas:ai-model-action", args=[model.pk, "explode"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("ideas:ai-model-action", args=[model.pk, "delete"])).status_code, 405)

    def test_test_button_reports_success_and_failure(self):
        server = FakeProviderServer(200, chat_reply('{"ok": true}'))
        self.addCleanup(server.close)
        self.client.force_login(make_user("boss", staff=True))
        boss = get_user_model().objects.get(username="boss")
        good = AIModel.objects.create(owner=boss, kind="custom", label="Good", model_name="m", base_url=server.url)
        bad = AIModel.objects.create(owner=boss, kind="custom", label="Bad", model_name="m", base_url="http://127.0.0.1:9/v1")

        ok = self.client.post(reverse("ideas:ai-model-action", args=[good.pk, "test"]), follow=True)
        failed = self.client.post(reverse("ideas:ai-model-action", args=[bad.pk, "test"]), follow=True)

        self.assertContains(ok, "çalışıyor")
        self.assertContains(failed, "çalışmadı")

    def test_test_button_never_leaks_the_key_into_the_page(self):
        model = AIModel.objects.create(owner=self.user, kind="groq", label="G", model_name="m", **sealed(self.user, "sk-secret-should-not-show"))

        with patch("ideas.ai_settings_views.build_client", side_effect=AIProviderError("groq HTTP 401: invalid key")):
            page = self.client.post(reverse("ideas:ai-model-action", args=[model.pk, "test"]), follow=True)

        self.assertContains(page, "çalışmadı")
        self.assertNotContains(page, "sk-secret-should-not-show")

    def test_available_models_are_listed_and_can_be_picked(self):
        server = FakeProviderServer(200, {"data": [{"id": "model-b"}, {"id": "model-a"}]})
        self.addCleanup(server.close)
        self.client.force_login(make_user("boss", staff=True))
        boss = get_user_model().objects.get(username="boss")
        model = AIModel.objects.create(owner=boss, kind="custom", label="Srv", model_name="model-a", base_url=server.url)

        page = self.client.get(reverse("ideas:ai-model-available", args=[model.pk]))
        self.assertContains(page, "model-b")
        self.client.post(reverse("ideas:ai-model-action", args=[model.pk, "use"]), {"model_name": "model-b"})

        model.refresh_from_db()
        self.assertEqual(model.model_name, "model-b")

    def test_unreachable_provider_shows_an_error_instead_of_crashing(self):
        self.client.force_login(make_user("boss", staff=True))
        boss = get_user_model().objects.get(username="boss")
        model = AIModel.objects.create(owner=boss, kind="custom", label="Srv", model_name="m", base_url="http://127.0.0.1:9/v1")

        page = self.client.get(reverse("ideas:ai-model-available", args=[model.pk]))

        self.assertContains(page, "Liste alınamadı")

    def test_a_demoted_staff_users_address_based_model_cannot_be_used(self):
        model = AIModel.objects.create(owner=self.user, kind="custom", label="Old", model_name="m", base_url="http://127.0.0.1:9/v1")

        self.assertEqual(self.client.post(reverse("ideas:ai-model-action", args=[model.pk, "test"])).status_code, 404)

    def test_notice_asks_users_without_models_to_add_one(self):
        self.assertContains(self.client.get(reverse("ideas:list")), "kendi AI anahtarını ekle")

        AIModel.objects.create(owner=self.user, kind="groq", label="G", model_name="m", **sealed(self.user))

        self.assertNotContains(self.client.get(reverse("ideas:list")), "kendi AI anahtarını ekle")

    def test_old_chat_messages_show_the_label_of_a_database_model(self):
        model = AIModel.objects.create(owner=self.user, kind="groq", label="Home PC", model_name="a", **sealed(self.user))
        conversation = Conversation.objects.create(owner=self.user, title="t")
        ChatMessage.objects.create(conversation=conversation, role="assistant", content="hi", provider=model.chain_name)

        page = self.client.get(reverse("ideas:conversation", args=[conversation.pk]))

        self.assertContains(page, "Yanıtlayan: Home PC")


class NavigationTests(TestCase):
    def test_settings_is_reachable_from_the_desktop_sidebar_and_the_phone_tab_bar(self):
        user = make_user("owner", staff=False)
        self.client.force_login(user)

        page = self.client.get(reverse("ideas:list")).content.decode()

        self.assertEqual(page.count(f'href="{reverse("accounts:settings")}"'), 2)  # sidebar + tab bar


class ModelNameOptionalTests(TestCase):
    def setUp(self):
        self.user = make_user("owner", staff=False)
        self.client.force_login(self.user)

    def add(self, kind):
        return self.client.post(reverse("ideas:ai-model-create"), {"kind": kind, "label": "", "model_name": "", "api_key": "sk-test-key-123456", "enabled": "on"})

    def test_leaving_the_name_empty_picks_the_providers_default(self):
        for kind, expected in (("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-flash-lite-latest"), ("anthropic", "claude-opus-5-5")):
            self.add(kind)
            self.assertEqual(AIModel.objects.get(kind=kind).model_name, expected)

    def test_providers_without_a_default_save_with_an_empty_name_and_are_not_used_until_one_is_picked(self):
        self.add("openai")
        model = AIModel.objects.get()

        self.assertEqual(model.model_name, "")
        self.assertFalse(ai_registry.has_models(self.user))
        page = self.client.get(reverse("ideas:ai-models"))
        self.assertContains(page, "model seçilmedi")
        test = self.client.post(reverse("ideas:ai-model-action", args=[model.pk, "test"]), follow=True)
        self.assertContains(test, "önce bir model seç")

        self.client.post(reverse("ideas:ai-model-action", args=[model.pk, "use"]), {"model_name": "some-model"})
        self.assertTrue(ai_registry.has_models(self.user))
