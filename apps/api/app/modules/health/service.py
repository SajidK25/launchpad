import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeResult:
    available: bool


Probe = Callable[[], Awaitable[ProbeResult]]


class HealthService:
    def __init__(self, probes: list[Probe]) -> None:
        self.probes = probes

    async def readiness(self, timeout_seconds: float = 3.0) -> bool:
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*(probe() for probe in self.probes), return_exceptions=True),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return False
        return all(isinstance(result, ProbeResult) and result.available for result in results)
