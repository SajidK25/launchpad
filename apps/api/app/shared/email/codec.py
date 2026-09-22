"""Versioned authenticated encryption for transactional email payloads."""

from __future__ import annotations

import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CODEC_VERSION = 1
NONCE_BYTES = 12


class PayloadEncodeError(ValueError):
    """Raised when an email payload cannot be safely encoded."""


class PayloadDecodeError(ValueError):
    """Raised when an email payload cannot be authenticated or decoded."""


@dataclass(frozen=True, slots=True)
class EmailPayloadCodec:
    """Encrypt JSON-compatible mail payloads with a versioned key ring."""

    keys: Mapping[str, bytes]
    active_key_id: str

    def __post_init__(self) -> None:
        if self.active_key_id not in self.keys:
            raise PayloadEncodeError("active email key is unavailable")
        if any(len(key) not in {16, 24, 32} for key in self.keys.values()):
            raise PayloadEncodeError("email keys have invalid length")

    def encode(self, payload: Mapping[str, Any]) -> tuple[str, bytes]:
        """Return the active key ID and authenticated ciphertext."""

        try:
            serialized = json.dumps(
                _json_safe(payload), ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            raise PayloadEncodeError("email payload is not serializable") from exc
        nonce = secrets.token_bytes(NONCE_BYTES)
        ciphertext = AESGCM(self.keys[self.active_key_id]).encrypt(
            nonce, serialized, self.active_key_id.encode("utf-8")
        )
        return self.active_key_id, bytes([CODEC_VERSION]) + nonce + ciphertext

    def decode(self, key_id: str, ciphertext: bytes) -> dict[str, Any]:
        """Authenticate and decode ciphertext, without exposing cryptographic details."""

        key = self.keys.get(key_id)
        if key is None or not isinstance(ciphertext, bytes) or len(ciphertext) <= NONCE_BYTES + 1:
            raise PayloadDecodeError("email payload is unavailable")
        if ciphertext[0] != CODEC_VERSION:
            raise PayloadDecodeError("email payload is unavailable")
        try:
            plaintext = AESGCM(key).decrypt(
                ciphertext[1 : NONCE_BYTES + 1],
                ciphertext[NONCE_BYTES + 1 :],
                key_id.encode("utf-8"),
            )
            decoded = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise PayloadDecodeError("email payload is unavailable") from exc
        if not isinstance(decoded, dict):
            raise PayloadDecodeError("email payload is unavailable")
        return decoded


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
