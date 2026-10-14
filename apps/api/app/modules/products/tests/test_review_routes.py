"""Transport contracts for the gated staff review command."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from redis import Redis

from app.modules.products.routes import router
from app.modules.products.schemas import ReviewDecisionInput
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.storage.objects import PrivateObjectStore


def _app(*, review_writes_enabled: bool) -> tuple[FastAPI, APIRouter]:
    settings = Settings(
        trusted_web_origins=("http://localhost:8080",),
        outbox_key_id="test",
        outbox_key=SecretStr(base64.b64encode(b"x" * 32).decode("ascii")),
        review_writes_enabled=review_writes_enabled,
    )
    storage = PrivateObjectStore(
        endpoint_url="http://minio:9000",
        bucket_name="private",
        access_key_id="key",
        secret_access_key="secret",
        client_factory=lambda: SimpleNamespace(),
    )
    routes = router(
        settings=settings,
        database=Database.connect(str(settings.database_url)),
        redis=Redis.from_url(str(settings.redis_url)),
        storage=storage,
    )
    app = FastAPI()
    app.include_router(routes)
    return app, routes


def test_review_command_is_registered_and_disabled_flag_fails_closed() -> None:
    app, routes = _app(review_writes_enabled=False)
    paths = {route.path for route in routes.routes if isinstance(route, APIRoute)}
    product_id = uuid4()
    response = TestClient(app).post(
        f"/api/v1/staff/products/{product_id}/review-decisions",
        json={
            "submission_id": str(uuid4()),
            "expected_version": 4,
            "outcome": "approved",
        },
        headers={
            "Origin": "http://localhost:8080",
            "Idempotency-Key": "review-off-test",
        },
    )

    assert "/api/v1/staff/products/{product_id}/review-decisions" in paths
    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}


def test_review_input_normalizes_feedback_and_requires_reason_for_nonapproval() -> None:
    approved = ReviewDecisionInput(
        submission_id=uuid4(), expected_version=0, outcome="approved", feedback=None
    )
    returned = ReviewDecisionInput(
        submission_id=uuid4(),
        expected_version=0,
        outcome="changes_requested",
        feedback="  Update the setup flow.  ",
    )

    assert approved.feedback is None
    assert returned.feedback == "Update the setup flow."
    for feedback in (None, "   "):
        with pytest.raises(ValidationError):
            ReviewDecisionInput(
                submission_id=uuid4(),
                expected_version=0,
                outcome="rejected",
                feedback=feedback,
            )
    with pytest.raises(ValidationError):
        ReviewDecisionInput(
            submission_id=uuid4(),
            expected_version=0,
            outcome="approved",
            feedback="A reason is not valid for approval.",
        )
