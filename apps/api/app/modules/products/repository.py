"""Product-owned persistence for drafts, assets, topics, and submission periods."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from app.modules.products.models import (
    Product,
    ProductAsset,
    ProductSubmission,
    ProductTopic,
    Topic,
)
from app.modules.products.policies import ProductConflictError
from app.modules.products.schemas import ProductContentInput
from app.modules.products.service import canonical_topic_key, validate_topic_names
from sqlalchemy import delete, func, select, update
from sqlalchemy import insert as sa_insert
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7


@dataclass(frozen=True, slots=True)
class TopicResolution:
    """A topic identity paired with the current founder's own display label."""

    topic_id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class TopicChoice:
    """A launched topic that is safe to offer as a general choice."""

    topic_id: UUID
    display_name: str


class TopicRepository:
    """Persist canonical topic identities without exposing private proposals."""

    async def get_or_create_topic(
        self, session: AsyncSession, display_name: str
    ) -> TopicResolution:
        """Reuse an equivalent key atomically while returning only the caller's label."""

        label = validate_topic_names([display_name])[0]
        topic_id = uuid7()
        statement = (
            insert(Topic)
            .values(id=topic_id, display_name=label.display_name, name_key=label.name_key)
            .on_conflict_do_nothing(index_elements=[Topic.name_key])
            .returning(Topic.id)
        )
        result = await session.execute(statement)
        resolved_id = result.scalar_one_or_none()
        if resolved_id is None:
            resolved_id = await session.scalar(
                select(Topic.id).where(Topic.name_key == label.name_key)
            )
        if resolved_id is None:
            raise RuntimeError("topic key was not available after conflict resolution")
        return TopicResolution(topic_id=resolved_id, display_name=label.display_name)

    async def list_topic_choices(
        self, session: AsyncSession, *, query: str | None = None, limit: int = 20
    ) -> list[TopicChoice]:
        """Return only launched topics; private proposals are never general suggestions."""

        statement = select(Topic).where(Topic.first_launched_at.is_not(None))
        if query is not None and query.strip():
            statement = statement.where(
                Topic.name_key.startswith(canonical_topic_key(query), autoescape=True)
            )
        topics = (
            await session.scalars(statement.order_by(Topic.name_key).limit(min(max(limit, 1), 50)))
        ).all()
        return [TopicChoice(topic_id=topic.id, display_name=topic.display_name) for topic in topics]


class ProductRepository:
    """Persist owner-scoped draft rows and their optimistic version."""

    async def get_product_assets(
        self, session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> list[ProductAsset]:
        statement = select(ProductAsset).where(ProductAsset.product_id == product_id)
        if lock:
            statement = statement.with_for_update()
        return list((await session.scalars(statement.order_by(ProductAsset.id))).all())

    async def delete_product(self, session: AsyncSession, *, product: Product) -> None:
        """Hard-delete the product and its cascading private associations."""

        await session.execute(delete(Product).where(Product.id == product.id))

    async def count_drafts(self, session: AsyncSession, *, founder_id: UUID) -> int:
        count = await session.scalar(
            select(func.count())
            .select_from(Product)
            .where(Product.founder_id == founder_id, Product.status == "draft")
        )
        return int(count or 0)

    async def count_pending(self, session: AsyncSession, *, founder_id: UUID) -> int:
        count = await session.scalar(
            select(func.count())
            .select_from(ProductSubmission)
            .join(Product, Product.id == ProductSubmission.product_id)
            .where(Product.founder_id == founder_id, ProductSubmission.state == "pending")
        )
        return int(count or 0)

    async def count_pending_assets(
        self, session: AsyncSession, *, product_id: UUID, now: datetime
    ) -> int:
        count = await session.scalar(
            select(func.count())
            .select_from(ProductAsset)
            .where(
                ProductAsset.product_id == product_id,
                ProductAsset.state == "pending",
                ProductAsset.expires_at > now,
            )
        )
        return int(count or 0)

    async def create_asset(
        self,
        session: AsyncSession,
        *,
        asset_id: UUID,
        product_id: UUID,
        kind: str,
        staging_key: str,
        media_type: str,
        byte_count: int,
        expires_at: datetime,
    ) -> ProductAsset:
        asset = ProductAsset(
            id=asset_id,
            product_id=product_id,
            kind=kind,
            state="pending",
            staging_key=staging_key,
            clean_key=None,
            media_type=media_type,
            byte_count=byte_count,
            position=None,
            expires_at=expires_at,
            attached_at=None,
        )
        session.add(asset)
        await session.flush()
        return asset

    async def get_asset(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        asset_id: UUID,
        lock: bool = False,
    ) -> ProductAsset | None:
        statement = select(ProductAsset).where(
            ProductAsset.id == asset_id, ProductAsset.product_id == product_id
        )
        if lock:
            statement = statement.with_for_update()
        return cast(ProductAsset | None, await session.scalar(statement))

    async def get_assets(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        asset_ids: set[UUID],
    ) -> list[ProductAsset]:
        if not asset_ids:
            return []
        return list(
            (
                await session.scalars(
                    select(ProductAsset)
                    .where(ProductAsset.product_id == product_id, ProductAsset.id.in_(asset_ids))
                    .with_for_update()
                )
            ).all()
        )

    async def replace_asset_attachments(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        selected_positions: dict[UUID, int | None],
        now: datetime,
    ) -> list[ProductAsset]:
        """Replace attachment ordering and return assets detached by this change."""

        current = list(
            (
                await session.scalars(
                    select(ProductAsset)
                    .where(
                        ProductAsset.product_id == product_id, ProductAsset.attached_at.is_not(None)
                    )
                    .with_for_update()
                )
            ).all()
        )
        for asset in current:
            asset.attached_at = None
            asset.position = None
        await session.flush()
        detached: list[ProductAsset] = []
        for asset in current:
            if asset.id not in selected_positions:
                asset.state = "detached"
                detached.append(asset)
        if selected_positions:
            chosen = await self.get_assets(
                session,
                product_id=product_id,
                asset_ids=set(selected_positions),
            )
            for asset in chosen:
                asset.position = selected_positions[asset.id]
                asset.attached_at = now
        await session.flush()
        return detached

    async def mark_asset_clean(
        self,
        session: AsyncSession,
        *,
        asset: ProductAsset,
        clean_key: str,
        media_type: str,
        byte_count: int,
    ) -> ProductAsset:
        asset.state = "clean"
        asset.clean_key = clean_key
        asset.media_type = media_type
        asset.byte_count = byte_count
        await session.flush()
        return asset

    async def mark_asset_failed(
        self, session: AsyncSession, *, asset: ProductAsset
    ) -> ProductAsset:
        asset.state = "failed"
        await session.flush()
        return asset

    async def submission_gaps(self, session: AsyncSession, *, product_id: UUID) -> tuple[str, ...]:
        """Return missing media/topic fields required for a review-ready product."""

        logo_count = await session.scalar(
            select(func.count())
            .select_from(ProductAsset)
            .where(
                ProductAsset.product_id == product_id,
                ProductAsset.kind == "logo",
                ProductAsset.state == "clean",
                ProductAsset.attached_at.is_not(None),
            )
        )
        screenshot_count = await session.scalar(
            select(func.count())
            .select_from(ProductAsset)
            .where(
                ProductAsset.product_id == product_id,
                ProductAsset.kind == "screenshot",
                ProductAsset.state == "clean",
                ProductAsset.attached_at.is_not(None),
            )
        )
        topic_count = await session.scalar(
            select(func.count())
            .select_from(ProductTopic)
            .where(ProductTopic.product_id == product_id)
        )
        missing: list[str] = []
        if logo_count != 1:
            missing.append("logo")
        if not 1 <= int(screenshot_count or 0) <= 10:
            missing.append("screenshots")
        if not 1 <= int(topic_count or 0) <= 3:
            missing.append("topics")
        return tuple(missing)

    async def get_owned_product(
        self, session: AsyncSession, *, product_id: UUID, founder_id: UUID, lock: bool = False
    ) -> Product | None:
        statement = (
            select(Product)
            .where(Product.id == product_id, Product.founder_id == founder_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return cast(Product | None, await session.scalar(statement))

    async def get_pending_submission(
        self, session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> ProductSubmission | None:
        statement = select(ProductSubmission).where(
            ProductSubmission.product_id == product_id,
            ProductSubmission.state == "pending",
        )
        if lock:
            statement = statement.with_for_update()
        return cast(ProductSubmission | None, await session.scalar(statement))

    async def create_submission(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        product_version: int,
        submitted_at: datetime,
    ) -> ProductSubmission:
        period = ProductSubmission(
            id=uuid7(),
            product_id=product_id,
            state="pending",
            submitted_at=submitted_at,
            closed_at=None,
            product_version=product_version,
        )
        session.add(period)
        await session.flush()
        return period

    async def set_product_state(
        self,
        session: AsyncSession,
        *,
        product: Product,
        status: str,
        now: datetime,
        content: ProductContentInput | None = None,
        website_key: str | None = None,
    ) -> Product:
        values: dict[str, object] = {
            "status": status,
            "version": Product.version + 1,
            "updated_at": now,
        }
        if content is not None:
            values.update(
                name=content.name,
                pitch=content.pitch,
                description=content.description,
                website_url=content.website_url,
                website_key=website_key,
            )
        statement = (
            update(Product)
            .where(Product.id == product.id, Product.version == product.version)
            .values(**values)
            .returning(Product)
            .execution_options(populate_existing=True)
        )
        saved = (await session.execute(statement)).scalar_one_or_none()
        if saved is None:
            raise ProductConflictError("product changed; reload and retry")
        return saved

    async def update_submission_version(
        self, session: AsyncSession, *, submission: ProductSubmission, product_version: int
    ) -> None:
        submission.product_version = product_version
        await session.flush()

    async def close_submission(
        self,
        session: AsyncSession,
        *,
        submission: ProductSubmission,
        closed_at: datetime,
    ) -> None:
        submission.state = "withdrawn"
        submission.closed_at = closed_at
        await session.flush()

    async def create_draft(
        self, session: AsyncSession, *, founder_id: UUID, now: datetime
    ) -> Product:
        statement = (
            sa_insert(Product)
            .values(
                id=uuid7(),
                founder_id=founder_id,
                status="draft",
                version=0,
                created_at=now,
                updated_at=now,
            )
            .returning(Product)
        )
        result = await session.execute(statement)
        return result.scalar_one()

    async def get_draft(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        founder_id: UUID,
        lock: bool = False,
    ) -> Product | None:
        statement = (
            select(Product)
            .where(
                Product.id == product_id,
                Product.founder_id == founder_id,
                Product.status == "draft",
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return cast(Product | None, await session.scalar(statement))

    async def save_draft(
        self,
        session: AsyncSession,
        *,
        product: Product,
        content: ProductContentInput,
        website_key: str | None,
        now: datetime,
    ) -> Product:
        statement = (
            update(Product)
            .where(
                Product.id == product.id,
                Product.founder_id == product.founder_id,
                Product.status == "draft",
                Product.version == product.version,
            )
            .values(
                name=content.name,
                pitch=content.pitch,
                description=content.description,
                website_url=content.website_url,
                website_key=website_key,
                version=Product.version + 1,
                updated_at=now,
            )
            .returning(Product)
            .execution_options(populate_existing=True)
        )
        result = await session.execute(statement)
        saved = result.scalar_one_or_none()
        if saved is None:
            raise ProductConflictError("product changed; reload and retry")
        return saved
