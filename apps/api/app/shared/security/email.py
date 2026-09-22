"""Canonical email identity primitives."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from email_validator import EmailNotValidError, validate_email


@dataclass(frozen=True, slots=True)
class CanonicalEmail:
    """Delivery spelling and stable comparison key for an email address."""

    delivery: str
    key: str


def canonicalize_email(value: str) -> CanonicalEmail:
    """Validate an address and canonicalize casing and the domain's IDNA form."""

    if not isinstance(value, str):
        raise ValueError("invalid email")
    candidate = unicodedata.normalize("NFC", value.strip())
    try:
        validated = validate_email(candidate, allow_smtputf8=True, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError("invalid email") from exc

    local, _, domain = validated.normalized.rpartition("@")
    if not local or not domain:
        raise ValueError("invalid email")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise ValueError("invalid email") from exc
    # Keep the user's NFC-normalized spelling for delivery; only the comparison
    # key applies case and IDNA normalization. Provider aliases are untouched.
    return CanonicalEmail(delivery=candidate, key=f"{local.casefold()}@{ascii_domain}")
