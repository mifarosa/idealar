from django.core.management.base import BaseCommand

from ideas import ai_enrichment
from ideas.models import Idea


class Command(BaseCommand):
    help = "Fills AI fields (title, summary, tags, suggestions) for ideas that do not have them yet."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50, help="Maximum number of ideas to process.")

    def handle(self, *args, limit, **options):
        analyzer = ai_enrichment.build_analyzer()
        ideas = Idea.objects.awaiting_ai().order_by("id")[:limit]
        results = [ai_enrichment.enrich_idea(idea, analyzer) for idea in ideas]
        succeeded = sum(results)
        self.stdout.write(f"AI filled {succeeded} of {len(results)} ideas.")
