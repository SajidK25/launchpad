"""Password policy and Argon2id storage primitives."""

from __future__ import annotations

import importlib.resources
import unicodedata
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


class PasswordPolicyError(ValueError):
    """Raised when a password does not meet the local password policy."""


@lru_cache(maxsize=1)
def _compromised_passwords() -> frozenset[str]:
    resource = importlib.resources.files("app.shared.security").joinpath("blocklist.txt")
    values = {
        line.strip().casefold()
        for line in resource.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return frozenset(values)


def normalize_password(password: str) -> str:
    """Normalize and enforce the password policy without changing spaces."""

    if not isinstance(password, str):
        raise PasswordPolicyError("invalid password")
    normalized = unicodedata.normalize("NFC", password)
    if not MIN_PASSWORD_LENGTH <= len(normalized) <= MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError("invalid password")
    if normalized.casefold() in _compromised_passwords():
        raise PasswordPolicyError("invalid password")
    return normalized


def hash_password(password: str) -> str:
    """Return an Argon2id encoded password hash."""

    return _hasher.hash(normalize_password(password))


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password, returning false for invalid policy or hash input."""

    try:
        normalized = normalize_password(password)
        return _hasher.verify(encoded_hash, normalized)
    except (PasswordPolicyError, InvalidHashError, VerificationError, VerifyMismatchError):
        return False
