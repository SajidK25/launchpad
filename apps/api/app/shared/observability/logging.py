"""Structured application logging that never serializes sensitive values."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_sensitive_key_fragments = (
    "secret",
    "password",
    "token",
    "authorization",
    "body",
    "object",
    "url",
)


def _sanitize_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return context that is safe to serialize into a log entry."""

    return {
        key: "[REDACTED]"
        if any(fragment in key.lower() for fragment in _sensitive_key_fragments)
        else value
        for key, value in context.items()
    }


class _JsonFormatter(logging.Formatter):
    """Serialize only the explicitly supported structured logging fields."""

    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "component": getattr(record, "component", "unknown"),
            "operation": getattr(record, "operation", "unknown"),
            "outcome": getattr(record, "outcome", "unknown"),
            "request_id": getattr(record, "request_id", None),
        }
        context = getattr(record, "context", {})
        if isinstance(context, Mapping) and context:
            event["context"] = context
        return json.dumps(event, default=str, sort_keys=True)


def configure_json_logger(name: str, stream: TextIO) -> logging.Logger:
    """Create an isolated JSON logger that writes to ``stream``."""

    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    return logger


@contextmanager
def request_context(request_id: str) -> Iterator[None]:
    """Bind a request identifier to log events inside this context."""

    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def log_event(
    logger: logging.Logger,
    *,
    component: str,
    operation: str,
    outcome: str,
    **context: Any,
) -> None:
    """Emit an operational event without rendering messages or sensitive data."""

    logger.info(
        "event",
        extra={
            "component": component,
            "operation": operation,
            "outcome": outcome,
            "request_id": _request_id.get(),
            "context": _sanitize_context(context),
        },
    )
