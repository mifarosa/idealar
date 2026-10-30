from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from ai.errors import AINotConfiguredError, AIProviderError, AIRateLimitError, AIResponseError, AllProvidersFailed
from ideas import ai_failure, ai_registry
from ideas.key_vault import seal
from ideas.models import AIModel, Idea


class DescribeTests(TestCase):
    def test_each_failure_is_explained_with_the_model_label(self):
        user = get_user_model().objects.create_user("owner")
        model = AIModel.objects.create(owner=user, kind="groq", label="My Groq", model_name="m")
        failure = AllProvidersFailed([(model.chain_name, AIProviderError("groq HTTP 404: model_not_found"))])

        text = ai_failure.describe(failure)

        self.assertIn("My Groq: modeli bulamadı (404)", text)

    def test_common_reasons_are_actionable(self):
        cases = {
            AIProviderError("x HTTP 401: invalid"): "anahtarı reddetti",
            AIProviderError("x HTTP 403: nope"): "erişimi reddetti",
            AIProviderError("x HTTP 503: down"): "şu an çalışmıyor (503)",
            AIProviderError("x unreachable: timed out"): "ulaşılamadı",
            AIRateLimitError("x rate limit"): "limiti doldu",
            AIResponseError("bad json"): "geçerli bir cevap vermedi",
            AINotConfiguredError("x has no API key"): "anahtar eksik",
        }
        for error, expected in cases.items():
            self.assertIn(expected, ai_failure._reason(error))

    def test_empty_chain_tells_the_user_where_to_add_a_model(self):
        self.assertIn("AI modellerimi yönet", ai_failure.describe(AINotConfiguredError("none")))

    def test_the_provider_body_is_never_repeated(self):
        error = AIProviderError("groq HTTP 401: Incorrect API key provided: sk-abc123SECRET")

        self.assertNotIn("sk-abc123SECRET", ai_failure._reason(error))


class ChatFailureMessageTests(TestCase):
    def test_chat_toast_names_the_reason(self):
        user = get_user_model().objects.create_user("owner")
        self.client.force_login(user)
        model = AIModel.objects.create(owner=user, kind="groq", label="Groq", model_name="old", api_key_sealed=seal("k", user.pk))
        Idea.objects.create(owner=user, body="x")
        failing = AllProvidersFailed([(model.chain_name, AIProviderError("groq HTTP 404: model_not_found"))])

        with patch("ideas.chat_service.build_assistant", side_effect=failing):
            response = self.client.post(reverse("ideas:chat"), {"text": "selam"}, follow=True)

        self.assertContains(response, "Hiçbir AI yanıt veremedi")
        self.assertContains(response, "Sebep: Groq: modeli bulamadı (404)")


class DiagnoseTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("owner")

    def make(self, label="G", **fields):
        defaults = {"kind": "groq", "model_name": "m", "api_key_sealed": seal("k", self.user.pk), "key_hint": ""}
        return AIModel.objects.create(owner=self.user, label=label, **{**defaults, **fields})

    def reasons(self):
        return dict(ai_registry.diagnose(self.user))

    def test_every_way_a_model_can_be_unusable_is_named(self):
        self.make("Off", enabled=False)
        self.make("NoName", model_name="")
        self.make("NoKey", api_key_sealed="")
        self.make("Local", kind="ollama", base_url="http://h:1", api_key_sealed="")

        reasons = self.reasons()

        self.assertEqual(reasons["Off"], "kapalı")
        self.assertIn("model seçilmedi", reasons["NoName"])
        self.assertIn("anahtar kayıtlı değil", reasons["NoKey"])
        self.assertIn("yalnızca yönetici", reasons["Local"])

    def test_an_unreadable_key_is_explained(self):
        self.make("Groq")

        with self.settings(KEYS_ENCRYPTION_KEY="a-brand-new-secret-a-brand-new-secret"):
            self.assertIn("okunamıyor", self.reasons()["Groq"])

    def test_working_models_are_not_listed(self):
        self.make("Fine")

        self.assertEqual(ai_registry.diagnose(self.user), [])

    def test_the_chat_message_lists_the_reasons_when_models_exist_but_none_work(self):
        self.make("Groq")
        self.client.force_login(self.user)

        with self.settings(KEYS_ENCRYPTION_KEY="a-brand-new-secret-a-brand-new-secret"):
            response = self.client.post(reverse("ideas:chat"), {"text": "selam"}, follow=True)

        self.assertContains(response, "Modellerin var ama hiçbiri kullanılamıyor")
        self.assertContains(response, "Groq: kayıtlı anahtar okunamıyor")

    def test_a_user_with_no_models_still_gets_the_add_a_model_hint(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("ideas:chat"), {"text": "selam"}, follow=True)

        self.assertContains(response, "bir model ve anahtarı ekle")
