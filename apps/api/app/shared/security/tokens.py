"""Opaque random token and digest primitives."""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32


def generate_token() -> str:
    """Generate a URL-safe token backed by at least 256 bits of entropy."""

    return secrets.token_urlsafe(TOKEN_BYTES)


def digest_token(token: str) -> bytes:
    """Return the fixed-size digest suitable for storage."""

    if not isinstance(token, str):
        raise ValueError("invalid token")
    return hashlib.sha256(token.encode("utf-8")).digest()


def token_matches(token: str, expected_digest: bytes) -> bool:
    """Constant-time compare a token to its stored digest."""

    try:
        return hmac.compare_digest(digest_token(token), expected_digest)
    except (TypeError, ValueError):
        return False
