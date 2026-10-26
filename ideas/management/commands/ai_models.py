from django.core.management.base import BaseCommand

from ai.client import LLMClient
from ai.errors import AIError
from ai.providers import build_default_client


class Command(BaseCommand):
    help = "Lists the models each configured AI provider offers, to pick a valid *_MODEL value."

    def handle(self, *args, **options):
        for client in build_default_client()._clients:
            self.stdout.write(f"[{client.name}] configured model: {client._model}")
            self._print_models(client)

    def _print_models(self, client: LLMClient) -> None:
        try:
            models = client.list_models()
        except AIError as error:
            self.stdout.write(f"  could not list models: {error}")
            return
        for model in models:
            marker = "  <- in use" if model == client._model else ""
            self.stdout.write(f"  {model}{marker}")
