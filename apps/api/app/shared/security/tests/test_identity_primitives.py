from __future__ import annotations

import pytest
from app.shared.security.csrf import generate_csrf_token, verify_csrf_token
from app.shared.security.email import canonicalize_email
from app.shared.security.passwords import PasswordPolicyError, hash_password
from app.shared.security.tokens import digest_token, generate_token, token_matches


def test_email_key_is_case_and_idna_normalized_without_alias_rewrites() -> None:
    email = canonicalize_email("  Alice@Exämple.com ")
    alias = canonicalize_email("alice+tag@example.com")

    assert email.delivery == "Alice@Exämple.com"
    assert email.key == "alice@xn--exmple-cua.com"
    assert alias.key == "alice+tag@example.com"
    assert alias.key != canonicalize_email("alice@example.com").key


def test_generated_token_is_digestible_and_raw_value_is_not_stored() -> None:
    token = generate_token()
    digest = digest_token(token)

    assert len(token) >= 43
    assert len(digest) == 32
    assert token_matches(token, digest)
    assert not token_matches(generate_token(), digest)


def test_csrf_token_is_bound_to_its_digest() -> None:
    token, digest = generate_csrf_token()

    assert verify_csrf_token(token, digest)
    assert not verify_csrf_token(token + "tampered", digest)
    assert not verify_csrf_token(token, digest_token(generate_token()))


def test_invalid_inputs_do_not_echo_secret_values() -> None:
    sentinel = "qwerty123"

    with pytest.raises(ValueError) as email_error:
        canonicalize_email(f"{sentinel} is not an email")
    with pytest.raises(PasswordPolicyError) as password_error:
        hash_password(sentinel)

    assert sentinel not in str(email_error.value)
    assert sentinel not in str(password_error.value)
