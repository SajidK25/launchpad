"""Service orchestration for repeatable private product workflow examples."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.launches.service import LaunchBookingService
from app.modules.notifications.service import NotificationService
from app.modules.products.schemas import ProductAssetIntentInput, ProductContentInput
from app.modules.products.service import ProductAssetStorage, ProductService
from app.operations.demo_seed.fixtures import (
    PRIVATE_PRODUCT_FIXTURES,
    PUBLIC_PRODUCT_FIXTURES,
)
from app.operations.demo_seed.repository import DemoSeedRepository


class DemoSeedService:
    """Coordinate domain-owned product transitions and ledger ownership."""

    def __init__(
        self,
        *,
        products: ProductService,
        launches: LaunchBookingService,
        storage: ProductAssetStorage,
        ownership: DemoSeedRepository | None = None,
        notifications: NotificationService,
        product_media: Mapping[str, bytes],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.products = products
        self.launches = launches
        self.storage = storage
        self.ownership = ownership or DemoSeedRepository()
        self.product_media = product_media
        self._current_time = (clock or (lambda: datetime.now(UTC)))().astimezone(UTC)
        self.clock: Callable[[], datetime] = lambda: self._current_time
        self.products.clock = self.clock
        self.launches.clock = self.clock
        self.notifications = notifications
        self.notifications.send_review_email = False
        self.products.review_notifications = notifications

    async def seed_private_products(
        self,
        session: AsyncSession,
        *,
        target_id: str,
        founder_ids: Mapping[str, UUID],
        reviewer_id: UUID,
    ) -> dict[str, UUID]:
        """Create/reconcile six examples using product and launch service boundaries.

        The caller owns a transaction per fixture so a successful example and its
        ownership row commit together. A later invocation reuses that stable key.
        """

        created: dict[str, UUID] = {}
        for fixture in PRIVATE_PRODUCT_FIXTURES:
            founder_id = founder_ids.get(fixture.founder_key)
            if founder_id is None:
                raise ValueError(f"missing owner for fixture {fixture.seed_key}")
            artifact = await self.ownership.get_artifact(
                session, target_id=target_id, seed_key=fixture.seed_key
            )
            if artifact is not None:
                if artifact.artifact_kind != "product":
                    raise RuntimeError("seed fixture ownership kind does not match")
                created[fixture.seed_key] = artifact.entity_id
                continue

            draft = await self.products.create_draft(session, actor_id=founder_id)
            saved = await self.products.save_draft(
                session,
                actor_id=founder_id,
                product_id=draft.id,
                expected_version=draft.version,
                content=ProductContentInput(
                    name=fixture.name,
                    pitch=fixture.pitch,
                    description=fixture.description,
                    website_url=fixture.website_url,
                ),
                topic_names=list(fixture.topics),
            )
            logo_id = await self._upload_asset(
                session,
                founder_id=founder_id,
                product_id=saved.id,
                kind="logo",
                media_key="logo",
            )
            screenshot_id = await self._upload_asset(
                session,
                founder_id=founder_id,
                product_id=saved.id,
                kind="screenshot",
                media_key="screenshot",
            )
            attached = await self.products.attach_assets(
                session,
                actor_id=founder_id,
                product_id=saved.id,
                expected_version=saved.version,
                logo_asset_id=logo_id,
                screenshot_asset_ids=(screenshot_id,),
            )
            product_id = attached.id
            if fixture.submit or fixture.outcome is not None:
                submission = await self.products.submit_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    expected_version=attached.version,
                )
                if fixture.outcome is not None:
                    decision = await self.products.decide_review(
                        session,
                        actor_id=reviewer_id,
                        product_id=product_id,
                        submission_id=submission.id,
                        expected_version=submission.product_version,
                        outcome=fixture.outcome,
                        feedback=fixture.feedback,
                        idempotency_key=f"demo-seed:{target_id}:{fixture.seed_key}:review",
                    )
                else:
                    decision = None
                if fixture.schedule and decision is not None:
                    now = self.clock().astimezone(UTC)
                    booking = await self.launches.book(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        launch_date=now.date() + timedelta(days=10),
                        expected_version=decision.version,
                        idempotency_key=f"demo-seed:{target_id}:{fixture.seed_key}:booking",
                    )
                    await self.ownership.record_artifact(
                        session,
                        target_id=target_id,
                        seed_key=f"{fixture.seed_key}:booking",
                        artifact_kind="booking",
                        entity_id=booking.id,
                        now=now,
                    )

            await self.ownership.record_artifact(
                session,
                target_id=target_id,
                seed_key=fixture.seed_key,
                artifact_kind="product",
                entity_id=product_id,
                now=self.clock().astimezone(UTC),
            )
            created[fixture.seed_key] = product_id
        return created

    async def seed_public_launches(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        target_id: str,
        anchor_utc_date: date,
        founder_ids: Mapping[str, UUID],
        reviewer_id: UUID,
    ) -> dict[str, UUID]:
        """Publish 20 products over the anchor date and its seven-day archive window.

        Each launch is committed with its ledger ownership in its own database
        transaction. The injected clock advances through the normal booking and
        publication services; no product or booking state is written directly.
        """

        if len(founder_ids) < 20:
            raise ValueError("at least 20 demo founder accounts are required")

        launch_ids: dict[str, UUID] = {}
        for fixture in PUBLIC_PRODUCT_FIXTURES:
            founder_id = founder_ids.get(fixture.founder_key)
            if founder_id is None:
                raise ValueError(f"missing owner for fixture {fixture.seed_key}")
            launch_date = anchor_utc_date - timedelta(days=fixture.day_offset)
            async with sessions() as session, session.begin():
                existing = await self.ownership.get_artifact(
                    session, target_id=target_id, seed_key=fixture.seed_key
                )
                if existing is not None:
                    if existing.artifact_kind != "product":
                        raise RuntimeError("seed fixture ownership kind does not match")
                    launch_ids[fixture.seed_key] = existing.entity_id
                    continue

                await self.notifications.update_launch_preferences(
                    session,
                    actor_id=founder_id,
                    values={
                        "reminder_email": False,
                        "reminder_in_site": True,
                        "live_email": False,
                        "live_in_site": True,
                        "failure_email": False,
                        "failure_in_site": True,
                    },
                )
                booking_time = datetime.combine(
                    launch_date - timedelta(days=1), time(hour=0, minute=1), tzinfo=UTC
                )
                self._current_time = booking_time
                draft = await self.products.create_draft(session, actor_id=founder_id)
                saved = await self.products.save_draft(
                    session,
                    actor_id=founder_id,
                    product_id=draft.id,
                    expected_version=draft.version,
                    content=ProductContentInput(
                        name=fixture.name,
                        pitch=fixture.pitch,
                        description=fixture.description,
                        website_url=fixture.website_url,
                    ),
                    topic_names=list(fixture.topics),
                )
                media_prefix = fixture.seed_key.removeprefix("product-")
                logo_id = await self._upload_asset(
                    session,
                    founder_id=founder_id,
                    product_id=saved.id,
                    kind="logo",
                    media_key=f"{media_prefix}-logo",
                )
                screenshot_id = await self._upload_asset(
                    session,
                    founder_id=founder_id,
                    product_id=saved.id,
                    kind="screenshot",
                    media_key=f"{media_prefix}-screenshot",
                )
                attached = await self.products.attach_assets(
                    session,
                    actor_id=founder_id,
                    product_id=saved.id,
                    expected_version=saved.version,
                    logo_asset_id=logo_id,
                    screenshot_asset_ids=(screenshot_id,),
                )
                submission = await self.products.submit_draft(
                    session,
                    actor_id=founder_id,
                    product_id=attached.id,
                    expected_version=attached.version,
                )
                decision = await self.products.decide_review(
                    session,
                    actor_id=reviewer_id,
                    product_id=attached.id,
                    submission_id=submission.id,
                    expected_version=submission.product_version,
                    outcome="approved",
                    feedback=None,
                    idempotency_key=f"demo-seed:{target_id}:{fixture.seed_key}:review",
                )
                booking = await self.launches.book(
                    session,
                    actor_id=founder_id,
                    product_id=attached.id,
                    launch_date=launch_date,
                    expected_version=decision.version,
                    idempotency_key=f"demo-seed:{target_id}:{fixture.seed_key}:booking",
                )
                launch_time = booking.launch_at.astimezone(UTC)
                self._current_time = launch_time
                product = await self.products.publish_scheduled_product(
                    session,
                    product_id=attached.id,
                    launch_at=launch_time,
                    now=launch_time,
                )
                if product.status != "launched":
                    raise RuntimeError(f"publication did not complete for {fixture.seed_key}")
                closed = await self.launches.record_publication_outcome(
                    session,
                    booking_id=booking.id,
                    outcome="launched",
                    now=launch_time,
                )
                if closed is None:
                    raise RuntimeError("published booking could not be closed")
                await self.notifications.record_launch_notice(
                    session, booking=closed, kind="launch_live"
                )
                await self.ownership.record_artifact(
                    session,
                    target_id=target_id,
                    seed_key=fixture.seed_key,
                    artifact_kind="product",
                    entity_id=attached.id,
                    now=launch_time,
                )
                await self.ownership.record_artifact(
                    session,
                    target_id=target_id,
                    seed_key=f"{fixture.seed_key}:booking",
                    artifact_kind="booking",
                    entity_id=booking.id,
                    now=launch_time,
                )
                launch_ids[fixture.seed_key] = attached.id
        return launch_ids

    async def _upload_asset(
        self,
        session: AsyncSession,
        *,
        founder_id: UUID,
        product_id: UUID,
        kind: Literal["logo", "screenshot"],
        media_key: str,
    ) -> UUID:
        body = self.product_media.get(media_key)
        if not body:
            raise ValueError(f"missing validated media fixture: {media_key}")
        intent = await self.products.create_asset_intent(
            session,
            actor_id=founder_id,
            product_id=product_id,
            intent=ProductAssetIntentInput(kind=kind, content_type="image/png", size=len(body)),
            storage=self.storage,
        )
        asset_id = intent.asset.id
        await self.products.transfer_asset(
            session,
            actor_id=founder_id,
            product_id=product_id,
            asset_id=asset_id,
            body=body,
            content_type="image/png",
            storage=self.storage,
        )
        result = await self.products.complete_asset(
            session,
            actor_id=founder_id,
            product_id=product_id,
            asset_id=asset_id,
            storage=self.storage,
        )
        if result.state != "clean":
            raise ValueError("product fixture media did not pass image validation")
        return asset_id
