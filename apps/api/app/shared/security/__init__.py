"""Small security primitives shared by identity and recovery features."""

from app.shared.security.csrf import generate_csrf_token, verify_csrf_token
from app.shared.security.email import CanonicalEmail, canonicalize_email
from app.shared.security.passwords import PasswordPolicyError, hash_password, verify_password
from app.shared.security.tokens import digest_token, generate_token, token_matches

__all__ = [
    "CanonicalEmail",
    "PasswordPolicyError",
    "canonicalize_email",
    "digest_token",
    "generate_csrf_token",
    "generate_token",
    "hash_password",
    "token_matches",
    "verify_csrf_token",
    "verify_password",
]
