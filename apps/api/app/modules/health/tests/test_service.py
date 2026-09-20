import asyncio

from app.modules.health.service import HealthService, ProbeResult


def test_readiness_requires_every_probe() -> None:
    async def ready() -> ProbeResult:
        return ProbeResult(True)

    async def failed() -> ProbeResult:
        return ProbeResult(False)

    assert asyncio.run(HealthService([ready, ready, failed]).readiness()) is False


def test_readiness_has_a_bounded_deadline() -> None:
    async def stalled() -> ProbeResult:
        await asyncio.sleep(1)
        return ProbeResult(True)

    assert asyncio.run(HealthService([stalled]).readiness(timeout_seconds=0.01)) is False
