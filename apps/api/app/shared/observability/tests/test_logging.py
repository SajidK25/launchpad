"""Contracts for sanitized structured diagnostics."""

from __future__ import annotations

import asyncio
import io
import json

from app.shared.observability.logging import configure_json_logger, log_event, request_context


def test_json_logs_correlate_request_context_without_secret_values() -> None:
    """Logs retain useful operation metadata but redact secret-bearing inputs."""

    stream = io.StringIO()
    logger = configure_json_logger("t3.logging", stream)

    with request_context("request-one"):
        log_event(
            logger,
            component="config",
            operation="load",
            outcome="failed",
            database_url="postgresql://user:T3_URL_SECRET@postgres/test",
            object_body="T3_OBJECT_SECRET",
            storage_secret_access_key="T3_SECRET_SENTINEL",
        )
    with request_context("request-two"):
        log_event(logger, component="config", operation="retry", outcome="success")

    first_event, second_event = map(json.loads, stream.getvalue().splitlines())

    assert first_event["level"] == "INFO"
    assert first_event["component"] == "config"
    assert first_event["operation"] == "load"
    assert first_event["outcome"] == "failed"
    assert first_event["request_id"] == "request-one"
    assert second_event["request_id"] == "request-two"
    assert "T3_URL_SECRET" not in stream.getvalue()
    assert "T3_OBJECT_SECRET" not in stream.getvalue()
    assert "T3_SECRET_SENTINEL" not in stream.getvalue()


def test_concurrent_request_contexts_do_not_leak_identifiers() -> None:
    """Each asynchronous request retains its own correlation identifier."""

    stream = io.StringIO()
    logger = configure_json_logger("t3.concurrent-logging", stream)

    async def emit(request_id: str) -> None:
        with request_context(request_id):
            await asyncio.sleep(0)
            log_event(logger, component="request", operation="complete", outcome="success")

    async def emit_both() -> None:
        await asyncio.gather(emit("request-alpha"), emit("request-beta"))

    asyncio.run(emit_both())

    events = [json.loads(line) for line in stream.getvalue().splitlines()]

    assert {event["request_id"] for event in events} == {"request-alpha", "request-beta"}
