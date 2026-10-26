"""Service orchestration for repeatable private product workflow examples."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.launches.service import LaunchBookingService
from app.modules.products.schemas import ProductAssetIntentInput, ProductContentInput
from app.modules.products.service import ProductAssetStorage, ProductService
from app.operations.demo_seed.fixtures import PRIVATE_PRODUCT_FIXTURES
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
        product_media: Mapping[str, bytes],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.products = products
        self.launches = launches
        self.storage = storage
        self.ownership = ownership or DemoSeedRepository()
        self.product_media = product_media
        self.clock = clock or (lambda: datetime.now(UTC))

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
