from __future__ import annotations

import hashlib
import hmac
import secrets

from app.core.config import get_settings


def new_guest_token() -> str:
    """Generate a high-entropy opaque capability for one anonymous session."""
    return secrets.token_urlsafe(32)


def hash_guest_token(token: str | None) -> str | None:
    if not token:
        return None
    value = token.strip()
    if len(value) < 16 or len(value) > 256:
        return None
    secret = get_settings().guest_token_hash_secret.encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def guest_token_matches(token: str | None, expected_hash: str | None) -> bool:
    actual = hash_guest_token(token)
    return bool(actual and expected_hash and hmac.compare_digest(actual, expected_hash))
