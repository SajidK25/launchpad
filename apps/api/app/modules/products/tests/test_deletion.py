"""Transport contracts for permanent private-draft deletion."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.modules.products.tests.test_routes import _app


def test_delete_requires_exact_origin_and_version_before_service_access() -> None:
    app, _ = _app(("http://localhost:8080",))
    client = TestClient(app)
    path = f"/api/v1/me/products/{uuid4()}"

    untrusted = client.delete(f"{path}?expected_version=0", headers={"Origin": "http://evil.test"})
    assert untrusted.status_code == 403

    trusted_without_session = client.delete(
        f"{path}?expected_version=0", headers={"Origin": "http://localhost:8080"}
    )
    assert trusted_without_session.status_code == 401

    missing_version = client.delete(path, headers={"Origin": "http://localhost:8080"})
    assert missing_version.status_code == 422
