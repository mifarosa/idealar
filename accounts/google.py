"""Sign in with Google (OpenID Connect, authorization-code flow).

Authlib handles state, nonce and ID-token signature checks; this module only decides which local user a
verified Google identity belongs to.
"""
from functools import lru_cache
from django.utils.translation import gettext as _

from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from .models import GoogleAccount

DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


class SignInRefused(Exception):
    """A Google identity that may not enter; the message is shown to the user."""


def is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


@lru_cache(maxsize=1)
def oauth_client():
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url=DISCOVERY_URL,
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth.google


def user_for(userinfo: dict):
    """The local user for a verified Google identity: known identity, else a user with that e-mail, else a new one."""
    sub, email = userinfo.get("sub"), (userinfo.get("email") or "").strip().lower()
    if not sub or not email or userinfo.get("email_verified") is not True:
        raise SignInRefused(_("Google hesabının e-postası doğrulanmamış."))

    known = GoogleAccount.objects.select_related("user").filter(sub=sub).first()
    if known:
        return _active(known.user)

    User = get_user_model()
    with transaction.atomic():
        matches = list(User.objects.filter(email__iexact=email)[:2])
        if len(matches) == 1:
            user = matches[0]
        elif matches:
            raise SignInRefused(_("Bu e-posta birden fazla hesapta kayıtlı; yöneticiye başvur."))
        elif settings.GOOGLE_SIGNUP:
            user = User.objects.create_user(_free_username(email), email=email, first_name=(userinfo.get("given_name") or "")[:150])
        else:
            raise SignInRefused(_("Kayıtlar şu an kapalı."))
        GoogleAccount.objects.create(user=user, sub=sub)
    return _active(user)


def _active(user):
    if not user.is_active:
        raise SignInRefused(_("Bu hesap kapatılmış."))
    return user


def _free_username(email: str) -> str:
    User = get_user_model()
    base = (email.split("@")[0] or "kullanici")[:130]
    candidate, number = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        number += 1
        candidate = f"{base}{number}"
    return candidate
