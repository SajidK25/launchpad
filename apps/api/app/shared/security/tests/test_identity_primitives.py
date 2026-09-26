from __future__ import annotations

import pytest
from app.shared.security.csrf import (
    RequestSecurityError,
    derive_csrf_token,
    generate_csrf_token,
    require_csrf,
    validate_origin,
    verify_csrf_token,
)
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


def test_unsafe_request_requires_trusted_origin_and_session_csrf() -> None:
    token, digest = generate_csrf_token()
    require_csrf(
        origin="https://launchpad.example",
        trusted_origin="https://launchpad.example",
        token=token,
        expected_digest=digest,
    )
    cases = (("https://evil.example", token), ("https://launchpad.example", token + "x"))
    for origin, submitted in cases:
        try:
            require_csrf(
                origin=origin,
                trusted_origin="https://launchpad.example",
                token=submitted,
                expected_digest=digest,
            )
        except RequestSecurityError:
            pass
        else:
            raise AssertionError("unsafe request should be rejected")


def test_origin_validation_accepts_each_configured_origin() -> None:
    trusted_origins = ("http://localhost:8080", "http://127.0.0.1:8080")

    validate_origin("http://localhost:8080", trusted_origins)
    validate_origin("http://127.0.0.1:8080", trusted_origins)


def test_origin_validation_accepts_explicit_internal_check_origin() -> None:
    validate_origin("http://web:8080", ("http://web:8080",))


def test_origin_validation_rejects_missing_origin() -> None:
    with pytest.raises(RequestSecurityError):
        validate_origin(None, ("http://localhost:8080",))


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:8080",
        "http://localhost:3000",
        "http://evil.example:8080",
        "http://localhost:8080/path",
        "http://localhost:8080?debug=true",
        "http://user:pass@localhost:8080",
    ],
)
def test_origin_validation_rejects_non_exact_origins(origin: str) -> None:
    with pytest.raises(RequestSecurityError):
        validate_origin(origin, ("http://localhost:8080",))


def test_derived_csrf_token_is_stable_and_session_bound() -> None:
    first = derive_csrf_token("session-one")
    assert first == derive_csrf_token("session-one")
    assert first != derive_csrf_token("session-two")


def test_invalid_inputs_do_not_echo_secret_values() -> None:
    sentinel = "qwerty123"

    with pytest.raises(ValueError) as email_error:
        canonicalize_email(f"{sentinel} is not an email")
    with pytest.raises(PasswordPolicyError) as password_error:
        hash_password(sentinel)

    assert sentinel not in str(email_error.value)
    assert sentinel not in str(password_error.value)
