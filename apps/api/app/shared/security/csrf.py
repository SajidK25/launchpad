"""Session-bound CSRF token primitives."""

from __future__ import annotations

from app.shared.security.tokens import digest_token, generate_token, token_matches


def generate_csrf_token() -> tuple[str, bytes]:
    """Return the one-time-presented CSRF token and its storage digest."""

    token = generate_token()
    return token, digest_token(token)


def verify_csrf_token(token: str, expected_digest: bytes) -> bool:
    """Verify a CSRF token against the digest bound to its session."""

    return token_matches(token, expected_digest)
