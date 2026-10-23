from django.conf import settings
from django.db import models
from django.db.models import Q

TITLE_PREVIEW_LENGTH = 60


class IdeaQuerySet(models.QuerySet):
    def owned_by(self, user):
        return self.filter(owner=user)

    def matching(self, text: str):
        text = text.strip()
        if not text:
            return self
        return self.filter(Q(title__icontains=text) | Q(body__icontains=text))


class Idea(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ideas")
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = IdeaQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["owner", "-created_at"])]

    def __str__(self) -> str:
        return self.display_title

    @property
    def display_title(self) -> str:
        """Explicit title if given, otherwise the first line of the body (quick capture has no title)."""
        if self.title:
            return self.title
        first_line = self.body.strip().splitlines()[0] if self.body.strip() else ""
        if len(first_line) <= TITLE_PREVIEW_LENGTH:
            return first_line
        return first_line[: TITLE_PREVIEW_LENGTH - 1].rstrip() + "…"
