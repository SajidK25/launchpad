"""Confidential transactional email payload boundaries."""

from app.shared.email.codec import (
    EmailPayloadCodec,
    PayloadDecodeError,
    PayloadEncodeError,
)

__all__ = ["EmailPayloadCodec", "PayloadDecodeError", "PayloadEncodeError"]
