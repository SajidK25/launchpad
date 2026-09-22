import asyncio

from redis import Redis

from app.modules.health.service import Probe, ProbeResult
from app.shared.db.database import Database
from app.shared.storage.client import StorageClient


async def unavailable() -> ProbeResult:
    return ProbeResult(False)


def database_probe(database: Database) -> Probe:
    async def check() -> ProbeResult:
        try:
            await database.ensure_compatible()
            return ProbeResult(True)
        except Exception:
            return ProbeResult(False)

    return check


def redis_probe(client: Redis) -> Probe:
    async def check() -> ProbeResult:
        try:
            return ProbeResult(bool(await asyncio.to_thread(client.ping)))
        except Exception:
            return ProbeResult(False)

    return check


def storage_probe(client: StorageClient, bucket_name: str) -> Probe:
    async def check() -> ProbeResult:
        try:
            await client.probe(bucket_name)
            return ProbeResult(True)
        except Exception:
            return ProbeResult(False)

    return check
