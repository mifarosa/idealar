from django.conf import settings
from django.db import models


class GoogleAccount(models.Model):
    """Ties a user to a Google identity. Google's stable `sub` id is the key, never the e-mail, which can change."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_account")
    sub = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user} ({self.sub})"
