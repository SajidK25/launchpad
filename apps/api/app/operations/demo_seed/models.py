"""Operations-owned persistence for demo seed ownership."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class DemoSeedBase(DeclarativeBase):
    """Metadata owned by demo-seed operations."""


class DemoSeedDataset(DemoSeedBase):
    """One stable seed dataset and date anchor for an explicitly named target."""

    __tablename__ = "demo_seed_datasets"
    __table_args__ = (
        CheckConstraint(
            "length(target_id) BETWEEN 1 AND 120 AND target_id = trim(target_id)",
            name="ck_demo_seed_datasets_target",
        ),
        CheckConstraint(
            "length(dataset_version) BETWEEN 1 AND 80 AND dataset_version = trim(dataset_version)",
            name="ck_demo_seed_datasets_version",
        ),
    )

    target_id: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_version: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_utc_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DemoSeedArtifact(DemoSeedBase):
    """Stable key to the domain record created by the seed operation."""

    __tablename__ = "demo_seed_artifacts"
    __table_args__ = (
        CheckConstraint(
            "length(seed_key) BETWEEN 1 AND 160 AND seed_key = trim(seed_key)",
            name="ck_demo_seed_artifacts_key",
        ),
        CheckConstraint(
            "artifact_kind IN ('account', 'profile', 'product', 'booking', 'notification')",
            name="ck_demo_seed_artifacts_kind",
        ),
        UniqueConstraint("target_id", "seed_key", name="uq_demo_seed_artifacts_target_key"),
        Index("ix_demo_seed_artifacts_target_kind", "target_id", "artifact_kind"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    target_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("demo_seed_datasets.target_id", ondelete="RESTRICT"),
        nullable=False,
    )
    seed_key: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
