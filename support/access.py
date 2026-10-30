"""Who may manage tickets: only accounts whose (Google-verified) e-mail is listed in TICKET_ADMIN_EMAILS."""
from django.conf import settings


def can_manage(user) -> bool:
    email = (getattr(user, "email", "") or "").strip().lower()
    return bool(user.is_authenticated and email and email in settings.TICKET_ADMIN_EMAILS)
