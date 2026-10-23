from dataclasses import dataclass

from django.conf import settings
from django.db import models
from django.db.models import Count, F, Q

TITLE_PREVIEW_LENGTH = 60

PLATFORM_CHOICES = [("pwa", "PWA"), ("android", "Android"), ("ios", "iOS")]
PLATFORM_LABELS = dict(PLATFORM_CHOICES)

AI_PENDING, AI_DONE, AI_FAILED = "pending", "done", "failed"
AI_STATUS_CHOICES = [(AI_PENDING, "Bekliyor"), (AI_DONE, "Tamam"), (AI_FAILED, "Başarısız")]


@dataclass(frozen=True)
class Progress:
    done: int
    total: int

    @property
    def percent(self) -> int:
        return round(100 * self.done / self.total) if self.total else 0

    @property
    def is_complete(self) -> bool:
        return self.total > 0 and self.done == self.total


class IdeaQuerySet(models.QuerySet):
    def owned_by(self, user):
        return self.filter(owner=user)

    def matching(self, text: str):
        text = text.strip()
        if not text:
            return self
        return self.filter(
            Q(title__icontains=text) | Q(body__icontains=text) | Q(ai_title__icontains=text) | Q(ai_summary__icontains=text)
        )

    def awaiting_ai(self):
        return self.exclude(ai_status=AI_DONE)

    def with_progress(self):
        # Aggregating adds GROUP BY, which discards Meta.ordering, so order explicitly.
        return self.annotate(
            total_features=Count("features", distinct=True),
            done_features=Count("features", filter=Q(features__is_done=True), distinct=True),
        ).order_by("-created_at", "-id")

    def finished(self):
        """Ideas whose features are all checked (needs with_progress)."""
        return self.filter(total_features__gt=0, done_features=F("total_features"))

    def unfinished(self):
        return self.exclude(total_features__gt=0, done_features=F("total_features"))


class Project(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.name

    @property
    def progress(self) -> Progress:
        features = Feature.objects.filter(idea__projects=self)
        return Progress(done=features.filter(is_done=True).count(), total=features.count())


class Idea(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ideas")
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    platforms = models.JSONField(default=list, blank=True)
    projects = models.ManyToManyField(Project, related_name="ideas", blank=True)
    # Filled by the AI layer; the idea is saved even when AI is unavailable (status stays pending/failed).
    ai_title = models.CharField(max_length=200, blank=True)
    ai_summary = models.TextField(blank=True)
    ai_tags = models.JSONField(default=list, blank=True)
    suggested_features = models.JSONField(default=list, blank=True)
    ai_status = models.CharField(max_length=10, choices=AI_STATUS_CHOICES, default=AI_PENDING)
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
        """Own title, else the AI title, else the first line of the body (quick capture has no title)."""
        if self.title:
            return self.title
        if self.ai_title:
            return self.ai_title
        first_line = self.body.strip().splitlines()[0] if self.body.strip() else ""
        if len(first_line) <= TITLE_PREVIEW_LENGTH:
            return first_line
        return first_line[: TITLE_PREVIEW_LENGTH - 1].rstrip() + "…"

    @property
    def platform_labels(self) -> list[str]:
        return [PLATFORM_LABELS[key] for key in self.platforms if key in PLATFORM_LABELS]

    @property
    def progress(self) -> Progress:
        """Uses the with_progress() annotations when present, otherwise counts."""
        if hasattr(self, "total_features"):
            return Progress(done=self.done_features, total=self.total_features)
        features = self.features.all()
        return Progress(done=sum(f.is_done for f in features), total=len(features))


class Feature(models.Model):
    """A checklist item of an idea. Copying to another idea creates an independent row."""

    idea = models.ForeignKey(Idea, on_delete=models.CASCADE, related_name="features")
    text = models.CharField(max_length=300)
    platform = models.CharField(max_length=10, choices=PLATFORM_CHOICES, blank=True)
    is_done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_done", "id"]

    def __str__(self) -> str:
        return self.text

    def copy_to(self, idea: Idea) -> "Feature":
        return Feature.objects.create(idea=idea, text=self.text, platform=self.platform)


ROLE_USER, ROLE_ASSISTANT = "user", "assistant"
ACTION_PENDING, ACTION_APPLIED, ACTION_DISMISSED = "pending", "applied", "dismissed"


class Conversation(models.Model):
    """A chat session about an idea, a project, or (both null) the whole idea list."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations")
    idea = models.ForeignKey(Idea, null=True, blank=True, on_delete=models.CASCADE, related_name="conversations")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(idea__isnull=True) | Q(project__isnull=True), name="conversation_single_scope"
            )
        ]

    def __str__(self) -> str:
        return self.title or f"Conversation {self.pk}"


class ChatMessage(models.Model):
    """One message of a conversation."""

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=[(ROLE_USER, "Kullanıcı"), (ROLE_ASSISTANT, "AI")])
    content = models.TextField()
    # Proposed changes: [{"type", "text", "idea_id", "status"}]; applied only after the user confirms.
    actions = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:40]}"
