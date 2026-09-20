from app.main import create_app
from app.modules.health.service import HealthService, ProbeResult
from fastapi.testclient import TestClient


def test_liveness_is_independent_and_readiness_is_safe() -> None:
    async def failed() -> ProbeResult:
        return ProbeResult(False)

    client = TestClient(create_app(HealthService([failed])))
    live = client.get("/api/v1/health/live")
    ready = client.get("/api/v1/health/ready")
    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable"}
    assert ready.headers["cache-control"] == "no-store"
