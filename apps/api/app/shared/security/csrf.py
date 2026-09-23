"""Session-bound CSRF token primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
from urllib.parse import urlsplit

from app.shared.security.tokens import digest_token, generate_token, token_matches


class RequestSecurityError(PermissionError):
    """The browser request did not satisfy origin or CSRF requirements."""


def generate_csrf_token() -> tuple[str, bytes]:
    """Return the one-time-presented CSRF token and its storage digest."""

    token = generate_token()
    return token, digest_token(token)


def verify_csrf_token(token: str, expected_digest: bytes) -> bool:
    """Verify a CSRF token against the digest bound to its session."""

    return token_matches(token, expected_digest)


def derive_csrf_token(session_secret: str) -> str:
    """Derive a stable, session-bound CSRF token without storing another secret."""

    digest = hmac.new(
        b"launchpad-session-csrf-v1", session_secret.encode("ascii"), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def validate_origin(origin: str | None, trusted_origin: str) -> None:
    """Require an exact scheme/host/port match with the configured web origin."""

    if origin is None:
        raise RequestSecurityError("origin required")
    actual = urlsplit(origin)
    trusted = urlsplit(trusted_origin)
    if (
        actual.scheme.lower(),
        actual.hostname,
        actual.port,
    ) != (trusted.scheme.lower(), trusted.hostname, trusted.port):
        raise RequestSecurityError("untrusted origin")


def require_csrf(
    *, origin: str | None, trusted_origin: str, token: str | None, expected_digest: bytes
) -> None:
    """Apply origin and session-bound CSRF checks before unsafe mutations."""

    validate_origin(origin, trusted_origin)
    if token is None or not verify_csrf_token(token, expected_digest):
        raise RequestSecurityError("invalid csrf token")


check_origin = validate_origin
check_csrf = require_csrf
