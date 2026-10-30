"""Seals users' AI API keys before they reach the database.

Threat model: a leaked database or backup alone must not reveal keys. Keys are encrypted with Fernet (AES-128-CBC +
HMAC-SHA256), using a key derived with HKDF from KEYS_ENCRYPTION_KEY (or SECRET_KEY when that is unset). The secret
lives only in the environment, never in the database or in backups.

Each sealed value also carries the id of the user it belongs to and is rejected for anyone else, so copying a sealed
key between rows (for instance with write access to the database) cannot make one user spend another's key.

Rotation: put the new secret in KEYS_ENCRYPTION_KEY, move the old one to KEYS_ENCRYPTION_KEY_PREVIOUS and run
`manage.py rotate_ai_keys`; once it reports nothing left on the old secret, delete KEYS_ENCRYPTION_KEY_PREVIOUS.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

FORMAT_PREFIX = "v1"
MIN_SECRET_CHARS = 32


class KeyUnreadable(Exception):
    """The stored key cannot be decrypted (the secret changed or the value belongs to someone else)."""


def _derive(secret: str) -> bytes:
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"idealar-ai-keys-v1", info=b"fernet").derive(secret.encode())
    return base64.urlsafe_b64encode(raw)


def _legacy_derive(secret: str) -> bytes:
    """Plain SHA-256 derivation used before HKDF; kept only so values sealed back then stay readable."""
    return base64.urlsafe_b64encode(hashlib.sha256(f"idealar-ai-keys:{secret}".encode()).digest())


def current_secret() -> str:
    return settings.KEYS_ENCRYPTION_KEY or settings.SECRET_KEY


def _secrets() -> list[str]:
    """Newest first: the first one encrypts, all of them may decrypt."""
    return [current_secret(), *settings.KEYS_ENCRYPTION_KEY_PREVIOUS]


def _keyring() -> MultiFernet:
    secrets = _secrets()
    return MultiFernet([Fernet(_derive(s)) for s in secrets] + [Fernet(_legacy_derive(s)) for s in secrets])


def seal(plain_key: str, owner_id: int) -> str:
    return _keyring().encrypt(f"{FORMAT_PREFIX}:{owner_id}:{plain_key}".encode()).decode()


def unseal(sealed_key: str, owner_id: int) -> str:
    try:
        plain = _keyring().decrypt(sealed_key.encode()).decode()
    except InvalidToken as error:
        raise KeyUnreadable from error
    if plain.startswith(f"{FORMAT_PREFIX}:"):
        _, bound_owner, key = plain.split(":", 2)
        if bound_owner != str(owner_id):
            raise KeyUnreadable
        return key
    return plain  # sealed before keys were bound to their owner


def needs_rotation(sealed_key: str) -> bool:
    """True when the value is not sealed with the current secret in the current format."""
    try:
        Fernet(_derive(current_secret())).decrypt(sealed_key.encode())
    except InvalidToken:
        return True
    return False


def hint(plain_key: str) -> str:
    """What the settings page may show of a saved key: only its last four characters."""
    return plain_key[-4:] if len(plain_key) >= 12 else ""
