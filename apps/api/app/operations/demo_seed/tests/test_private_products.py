"""Private product fixture orchestration across the existing service boundaries."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from app.operations.demo_seed.fixtures import PRIVATE_PRODUCT_FIXTURES
from app.operations.demo_seed.service import DemoSeedService


class _Ownership:
    def __init__(self) -> None:
        self.artifacts: dict[str, SimpleNamespace] = {}

    async def get_artifact(
        self, _session: Any, *, target_id: str, seed_key: str
    ) -> SimpleNamespace | None:
        return self.artifacts.get(f"{target_id}:{seed_key}")

    async def record_artifact(
        self,
        _session: Any,
        *,
        target_id: str,
        seed_key: str,
        artifact_kind: str,
        entity_id: UUID,
        now: datetime,
    ) -> SimpleNamespace:
        artifact = SimpleNamespace(artifact_kind=artifact_kind, entity_id=entity_id, created_at=now)
        self.artifacts[f"{target_id}:{seed_key}"] = artifact
        return artifact


class _Products:
    def __init__(self) -> None:
        self.products: dict[UUID, SimpleNamespace] = {}
        self.reviews: list[tuple[UUID, str, str | None]] = []
        self.uploads: list[tuple[UUID, str]] = []
        self.submissions: list[UUID] = []
        self.notices: list[UUID] = []
        self._asset_ids: dict[UUID, str] = {}

    async def create_draft(self, _session: Any, *, actor_id: UUID) -> SimpleNamespace:
        product = SimpleNamespace(
            id=uuid4(), founder_id=actor_id, status="draft", version=0, content=None
        )
        self.products[product.id] = product
        return product

    async def save_draft(
        self, _session: Any, *, product_id: UUID, **values: Any
    ) -> SimpleNamespace:
        product = self.products[product_id]
        product.content = values["content"]
        product.version += 1
        return product

    async def create_asset_intent(
        self, _session: Any, *, product_id: UUID, intent: Any, **_: Any
    ) -> Any:
        asset_id = uuid4()
        self._asset_ids[asset_id] = intent.kind
        return SimpleNamespace(asset=SimpleNamespace(id=asset_id))

    async def transfer_asset(
        self, _session: Any, *, product_id: UUID, asset_id: UUID, **_: Any
    ) -> None:
        self.uploads.append((product_id, self._asset_ids[asset_id]))

    async def complete_asset(self, _session: Any, *, asset_id: UUID, **_: Any) -> SimpleNamespace:
        return SimpleNamespace(asset_id=asset_id, state="clean")

    async def attach_assets(
        self, _session: Any, *, product_id: UUID, logo_asset_id: UUID, **_: Any
    ) -> SimpleNamespace:
        product = self.products[product_id]
        product.assets = (logo_asset_id,)
        product.version += 1
        return product

    async def submit_draft(self, _session: Any, *, product_id: UUID, **_: Any) -> SimpleNamespace:
        product = self.products[product_id]
        product.status = "submitted"
        product.version += 1
        submission = SimpleNamespace(id=uuid4(), product_version=product.version)
        self.submissions.append(product_id)
        return submission

    async def decide_review(
        self,
        _session: Any,
        *,
        product_id: UUID,
        outcome: str,
        feedback: str | None,
        **_: Any,
    ) -> SimpleNamespace:
        product = self.products[product_id]
        product.status = outcome
        product.version += 1
        self.reviews.append((product_id, outcome, feedback))
        self.notices.append(product_id)
        return SimpleNamespace(version=product.version)


class _Launches:
    def __init__(self, products: _Products) -> None:
        self.bookings: list[tuple[UUID, Any]] = []
        self.products = products

    async def book(self, _session: Any, *, product_id: UUID, launch_date: Any, **_: Any) -> Any:
        self.bookings.append((product_id, launch_date))
        self.products.products[product_id].status = "scheduled"
        return SimpleNamespace(id=uuid4())


def _service(ownership: _Ownership, products: _Products, launches: _Launches) -> DemoSeedService:
    return DemoSeedService(
        products=cast(Any, products),
        launches=cast(Any, launches),
        storage=cast(Any, object()),
        ownership=cast(Any, ownership),
        product_media={"logo": b"fixture-logo", "screenshot": b"fixture-shot"},
        clock=lambda: datetime(2026, 10, 26, 12, tzinfo=UTC),
    )


def test_private_fixture_manifest_covers_each_required_lifecycle_state() -> None:
    assert [fixture.seed_key for fixture in PRIVATE_PRODUCT_FIXTURES] == [
        "product-private-draft",
        "product-private-submitted",
        "product-private-changes-requested",
        "product-private-rejected",
        "product-private-approved",
        "product-private-scheduled",
    ]
    assert len({fixture.website_url for fixture in PRIVATE_PRODUCT_FIXTURES}) == 6
    assert all(
        fixture.website_url.endswith(".launchpad.example") for fixture in PRIVATE_PRODUCT_FIXTURES
    )


def test_private_products_use_review_and_booking_services_and_rerun_by_ledger() -> None:
    async def verify() -> None:
        ownership, products = _Ownership(), _Products()
        launches = _Launches(products)
        service = _service(ownership, products, launches)
        founder_ids = {f"founder-{index:02d}": uuid4() for index in range(1, 7)}
        reviewer_id = uuid4()
        ids = await service.seed_private_products(
            cast(Any, None),
            target_id="local-development",
            founder_ids=founder_ids,
            reviewer_id=reviewer_id,
        )

        statuses = {product.status for product in products.products.values()}
        assert statuses == {
            "draft",
            "submitted",
            "changes_requested",
            "rejected",
            "approved",
            "scheduled",
        }
        assert len(ids) == 6 and len(products.products) == 6
        assert len(products.reviews) == 4
        assert {outcome for _, outcome, _ in products.reviews} == {
            "approved",
            "changes_requested",
            "rejected",
        }
        assert len(launches.bookings) == 1
        assert launches.bookings[0][1].isoformat() == "2026-11-05"
        assert len(products.notices) == 4
        assert len(products.uploads) == 12
        assert all(
            product.content.website_url.endswith(".launchpad.example")
            for product in products.products.values()
        )

        replay = await service.seed_private_products(
            cast(Any, None),
            target_id="local-development",
            founder_ids=founder_ids,
            reviewer_id=reviewer_id,
        )
        assert replay == ids
        assert len(products.products) == 6
        assert len(products.reviews) == 4
        assert len(launches.bookings) == 1

    asyncio.run(verify())


def test_private_product_fixture_rejects_missing_owner_or_media() -> None:
    async def verify() -> None:
        products = _Products()
        service = _service(_Ownership(), products, _Launches(products))
        with pytest.raises(ValueError, match="missing owner"):
            await service.seed_private_products(
                cast(Any, None), target_id="local-development", founder_ids={}, reviewer_id=uuid4()
            )
        service.product_media = {"logo": b""}
        founders = {f"founder-{index:02d}": uuid4() for index in range(1, 7)}
        with pytest.raises(ValueError, match="missing validated media"):
            await service.seed_private_products(
                cast(Any, None),
                target_id="local-development",
                founder_ids=founders,
                reviewer_id=uuid4(),
            )

    asyncio.run(verify())
