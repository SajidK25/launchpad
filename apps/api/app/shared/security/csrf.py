"""Session-bound CSRF token primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Collection
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


def _origin_parts(
    value: str, *, allow_root_path: bool = False
) -> tuple[str, str, int | None] | None:
    """Return comparable origin parts for a URL that contains only an origin."""

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or (parsed.path if not allow_root_path else parsed.path not in ("", "/"))
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed.scheme.lower(), parsed.hostname.lower(), port


def validate_origin(origin: str | None, trusted_origins: Collection[str] | str) -> None:
    """Require an exact scheme/host/port match with a configured web origin."""

    if origin is None:
        raise RequestSecurityError("origin required")
    actual = _origin_parts(origin)
    configured = (trusted_origins,) if isinstance(trusted_origins, str) else trusted_origins
    if actual is None or not any(
        actual == trusted
        for trusted in (_origin_parts(value, allow_root_path=True) for value in configured)
    ):
        raise RequestSecurityError("untrusted origin")


def require_csrf(
    *,
    origin: str | None,
    trusted_origin: Collection[str] | str,
    token: str | None,
    expected_digest: bytes,
) -> None:
    """Apply origin and session-bound CSRF checks before unsafe mutations."""

    validate_origin(origin, trusted_origin)
    if token is None or not verify_csrf_token(token, expected_digest):
        raise RequestSecurityError("invalid csrf token")


check_origin = validate_origin
check_csrf = require_csrf
