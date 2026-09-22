from __future__ import annotations

import pytest
from app.shared.security.passwords import (
    PasswordPolicyError,
    hash_password,
    verify_password,
)


def test_argon2id_round_trip_does_not_store_plaintext() -> None:
    password = "a secure password 2026!"
    encoded = hash_password(password)

    assert encoded.startswith("$argon2id$")
    assert password not in encoded
    assert verify_password(password, encoded)
    assert not verify_password("a different password", encoded)


@pytest.mark.parametrize("password", ["short", "12345678", "password", "password123"])
def test_short_or_known_compromised_passwords_are_rejected(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password(password)


def test_long_spaced_password_is_accepted_without_character_mix() -> None:
    password = "a" * 64 + " with spaces"
    encoded = hash_password(password)

    assert verify_password(password, encoded)


def test_password_is_nfc_normalized_before_hashing() -> None:
    composed = "café password"
    decomposed = "cafe\u0301 password"

    encoded = hash_password(decomposed)

    assert verify_password(composed, encoded)
