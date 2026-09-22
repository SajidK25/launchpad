from __future__ import annotations

import pytest

from app.shared.email.codec import EmailPayloadCodec, PayloadDecodeError


def test_payload_is_authenticated_and_recovers_without_plaintext() -> None:
    codec = EmailPayloadCodec({"v1": b"a" * 32}, "v1")
    sentinel = "https://launchpad.example/reset?token=raw-secret"

    key_id, ciphertext = codec.encode({"recipient": "member@example.com", "link": sentinel})

    assert key_id == "v1"
    assert sentinel.encode() not in ciphertext
    assert codec.decode(key_id, ciphertext) == {
        "recipient": "member@example.com",
        "link": sentinel,
    }


def test_unknown_key_and_tampered_ciphertext_fail_without_plaintext() -> None:
    codec = EmailPayloadCodec({"v1": b"a" * 32}, "v1")
    key_id, ciphertext = codec.encode({"link": "raw-secret"})
    tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 1])

    with pytest.raises(PayloadDecodeError, match="unavailable"):
        codec.decode("unknown", ciphertext)
    with pytest.raises(PayloadDecodeError, match="unavailable"):
        codec.decode(key_id, tampered)
