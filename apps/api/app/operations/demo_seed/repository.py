"""PostgreSQL ownership ledger repository for demo seeding."""

from __future__ import annotations

from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.operations.demo_seed.models import DemoSeedArtifact, DemoSeedDataset


class SeedOwnershipConflict(RuntimeError):
    """A stable seed key is already owned by a different entity."""


class DemoSeedRepository:
    """Own target-scoped locking and durable stable-key ownership records."""

    async def lock_target(self, session: AsyncSession, *, target_id: str) -> None:
        """Serialize reconciliation for one target for the transaction lifetime."""

        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:target_id, 0))"),
            {"target_id": target_id},
        )

    async def get_or_create_dataset(
        self,
        session: AsyncSession,
        *,
        target_id: str,
        dataset_version: str,
        anchor_utc_date: date,
        now: datetime,
    ) -> DemoSeedDataset:
        """Create a target manifest once and preserve its original UTC anchor."""

        await session.execute(
            insert(DemoSeedDataset)
            .values(
                target_id=target_id,
                dataset_version=dataset_version,
                anchor_utc_date=anchor_utc_date,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[DemoSeedDataset.target_id])
        )
        dataset = await session.scalar(
            select(DemoSeedDataset).where(DemoSeedDataset.target_id == target_id).with_for_update()
        )
        if dataset is None:
            raise RuntimeError("Demo seed dataset could not be persisted.")
        if dataset.dataset_version != dataset_version:
            raise SeedOwnershipConflict("The target has a different demo dataset version.")
        await session.execute(
            update(DemoSeedDataset)
            .where(DemoSeedDataset.target_id == target_id)
            .values(updated_at=now)
        )
        return dataset

    async def get_artifact(
        self, session: AsyncSession, *, target_id: str, seed_key: str
    ) -> DemoSeedArtifact | None:
        """Find one target-owned artifact by its stable fixture key."""

        return cast(
            DemoSeedArtifact | None,
            await session.scalar(
                select(DemoSeedArtifact).where(
                    DemoSeedArtifact.target_id == target_id,
                    DemoSeedArtifact.seed_key == seed_key,
                )
            ),
        )

    async def record_artifact(
        self,
        session: AsyncSession,
        *,
        target_id: str,
        seed_key: str,
        artifact_kind: str,
        entity_id: UUID,
        now: datetime,
    ) -> DemoSeedArtifact:
        """Record ownership, accepting an exact replay but rejecting reassignment."""

        existing = await self.get_artifact(session, target_id=target_id, seed_key=seed_key)
        if existing is not None:
            if existing.artifact_kind != artifact_kind or existing.entity_id != entity_id:
                raise SeedOwnershipConflict("The seed key is already assigned to another entity.")
            return existing
        artifact = DemoSeedArtifact(
            id=uuid7(),
            target_id=target_id,
            seed_key=seed_key,
            artifact_kind=artifact_kind,
            entity_id=entity_id,
            created_at=now,
        )
        session.add(artifact)
        await session.flush()
        return artifact
