from django.conf import settings
from django.db import models

KIND_SUGGESTION, KIND_COMPLAINT, KIND_BUG = "suggestion", "complaint", "bug"
KIND_CHOICES = [(KIND_SUGGESTION, "Öneri"), (KIND_COMPLAINT, "Şikayet"), (KIND_BUG, "Hata bildirimi")]

STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_DONE, STATUS_CLOSED = "open", "in_progress", "done", "closed"
STATUS_CHOICES = [(STATUS_OPEN, "Açık"), (STATUS_IN_PROGRESS, "İnceleniyor"), (STATUS_DONE, "Çözüldü"), (STATUS_CLOSED, "Kapalı")]
ACTIVE_STATUSES = (STATUS_OPEN, STATUS_IN_PROGRESS)

MAX_TEXT_CHARS = 4000


class Ticket(models.Model):
    """A suggestion, complaint or bug report from a user. Only its author and the site owner can read it."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tickets")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=KIND_SUGGESTION)
    title = models.CharField(max_length=150)
    body = models.TextField(max_length=MAX_TEXT_CHARS)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["status", "-updated_at"])]

    def __str__(self) -> str:
        return self.title

    @property
    def accepts_replies_from_author(self) -> bool:
        return self.status != STATUS_CLOSED


class TicketMessage(models.Model):
    """A reply in a ticket thread, from the author or from the site owner."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    from_admin = models.BooleanField(default=False)
    body = models.TextField(max_length=MAX_TEXT_CHARS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
