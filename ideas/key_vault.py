"""Encrypts users' AI API keys before they reach the database.

A database leak (or a stolen backup) alone must not expose the keys, so they are sealed with Fernet using a
secret that lives only in the environment: KEYS_ENCRYPTION_KEY, or SECRET_KEY when that is not set.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class KeyUnreadable(Exception):
    """The stored key cannot be decrypted (the encryption secret changed); the user must enter it again."""


def _fernet() -> Fernet:
    secret = settings.KEYS_ENCRYPTION_KEY or settings.SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"idealar-ai-keys:{secret}".encode()).digest()))


def seal(plain_key: str) -> str:
    return _fernet().encrypt(plain_key.encode()).decode()


def unseal(sealed_key: str) -> str:
    try:
        return _fernet().decrypt(sealed_key.encode()).decode()
    except InvalidToken as error:
        raise KeyUnreadable from error


def hint(plain_key: str) -> str:
    """What the settings page may show of a saved key: only its last four characters."""
    return plain_key[-4:] if len(plain_key) >= 12 else ""
