from django.test import SimpleTestCase

from ai.client import LLMClient
from ai.errors import AINotConfiguredError, AIProviderError, AIRateLimitError, AllProvidersFailed
from ai.fallback import FallbackClient


class StubClient(LLMClient):
    def __init__(self, name, result=None, error=None):
        self.name = name
        self._result = result
        self._error = error
        self.calls = 0

    def chat_json(self, system, messages):
        self.calls += 1
        if self._error:
            raise self._error
        return self._result


class FallbackClientTests(SimpleTestCase):
    def test_primary_answer_is_used_and_fallback_untouched(self):
        primary, backup = StubClient("primary", {"from": "primary"}), StubClient("backup", {"from": "backup"})

        result = FallbackClient([primary, backup]).complete_json("s", "u")

        self.assertEqual(result, {"from": "primary"})
        self.assertEqual(backup.calls, 0)

    def test_rate_limited_primary_falls_back(self):
        primary = StubClient("primary", error=AIRateLimitError("limit"))
        backup = StubClient("backup", {"from": "backup"})

        with self.assertLogs("ai.fallback", level="WARNING"):
            result = FallbackClient([primary, backup]).complete_json("s", "u")

        self.assertEqual(result, {"from": "backup"})

    def test_provider_outage_falls_back(self):
        primary = StubClient("primary", error=AIProviderError("down"))

        with self.assertLogs("ai.fallback", level="WARNING"):
            result = FallbackClient([primary, StubClient("backup", {"ok": 1})]).complete_json("s", "u")

        self.assertEqual(result, {"ok": 1})

    def test_all_failing_raises_with_every_failure_listed(self):
        clients = [StubClient("a", error=AIRateLimitError("limit")), StubClient("b", error=AIProviderError("down"))]

        with self.assertLogs("ai.fallback", level="WARNING"), self.assertRaises(AllProvidersFailed) as caught:
            FallbackClient(clients).complete_json("s", "u")

        self.assertEqual([name for name, _ in caught.exception.failures], ["a", "b"])

    def test_no_clients_is_a_configuration_error(self):
        with self.assertRaises(AINotConfiguredError):
            FallbackClient([]).complete_json("s", "u")

    def test_programming_errors_are_not_swallowed(self):
        broken = StubClient("broken", error=ValueError("bug"))

        with self.assertRaises(ValueError):
            FallbackClient([broken, StubClient("backup", {})]).complete_json("s", "u")


class RunInfoTests(SimpleTestCase):
    def test_last_run_names_the_provider_that_answered_and_those_that_failed(self):
        clients = [
            StubClient("a", error=AIRateLimitError("limit")),
            StubClient("b", error=AIProviderError("down")),
            StubClient("c", {"ok": 1}),
        ]
        fallback = FallbackClient(clients)

        with self.assertLogs("ai.fallback", level="WARNING"):
            fallback.complete_json("s", "u")

        self.assertEqual((fallback.last_run.served_by, fallback.last_run.failed), ("c", ["a", "b"]))

    def test_last_run_is_empty_failed_list_when_primary_answers(self):
        fallback = FallbackClient([StubClient("a", {"ok": 1})])

        fallback.complete_json("s", "u")

        self.assertEqual((fallback.last_run.served_by, fallback.last_run.failed), ("a", []))
