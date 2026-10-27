"""UTC archive assignment and one-shot launch orchestration coverage."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

from app.operations.demo_seed.fixtures import PUBLIC_PRODUCT_FIXTURES
from app.operations.demo_seed.service import DemoSeedService


class _Ownership:
    def __init__(self) -> None:
        self.artifacts: dict[str, SimpleNamespace] = {}

    async def get_artifact(self, _session: Any, *, target_id: str, seed_key: str) -> Any:
        return self.artifacts.get(f"{target_id}:{seed_key}")

    async def record_artifact(self, _session: Any, **values: Any) -> Any:
        artifact = SimpleNamespace(**values)
        self.artifacts[f"{values['target_id']}:{values['seed_key']}"] = artifact
        return artifact


class _Products:
    def __init__(self) -> None:
        self.rows: dict[UUID, SimpleNamespace] = {}
        self.review_count = 0
        self.published: list[tuple[UUID, datetime]] = []
        self.media_keys: list[str] = []

    async def create_draft(self, _session: Any, *, actor_id: UUID) -> Any:
        row = SimpleNamespace(
            id=uuid4(), founder_id=actor_id, status="draft", version=0, content=None
        )
        self.rows[row.id] = row
        return row

    async def save_draft(self, _session: Any, *, product_id: UUID, **values: Any) -> Any:
        row = self.rows[product_id]
        row.content = values["content"]
        row.version += 1
        return row

    async def create_asset_intent(
        self, _session: Any, *, product_id: UUID, intent: Any, **_: Any
    ) -> Any:
        return SimpleNamespace(asset=SimpleNamespace(id=uuid4()))

    async def transfer_asset(self, _session: Any, **values: Any) -> None:
        self.media_keys.append(values["content_type"] + str(len(values["body"])))

    async def complete_asset(self, _session: Any, *, asset_id: UUID, **_: Any) -> Any:
        return SimpleNamespace(id=asset_id, state="clean")

    async def attach_assets(self, _session: Any, *, product_id: UUID, **_: Any) -> Any:
        row = self.rows[product_id]
        row.version += 1
        return row

    async def submit_draft(self, _session: Any, *, product_id: UUID, **_: Any) -> Any:
        row = self.rows[product_id]
        row.status = "submitted"
        row.version += 1
        return SimpleNamespace(id=uuid4(), product_version=row.version)

    async def decide_review(self, _session: Any, *, product_id: UUID, **_: Any) -> Any:
        row = self.rows[product_id]
        row.status = "approved"
        row.version += 1
        self.review_count += 1
        return SimpleNamespace(version=row.version)

    async def publish_scheduled_product(
        self, _session: Any, *, product_id: UUID, now: datetime, **_: Any
    ) -> Any:
        row = self.rows[product_id]
        row.status = "launched"
        self.published.append((product_id, now))
        return row


class _Launches:
    def __init__(self, products: _Products) -> None:
        self.products = products
        self.bookings: list[tuple[UUID, date]] = []

    async def book(self, _session: Any, *, product_id: UUID, launch_date: date, **_: Any) -> Any:
        self.products.rows[product_id].status = "scheduled"
        self.bookings.append((product_id, launch_date))
        return SimpleNamespace(
            id=uuid4(), launch_at=datetime.combine(launch_date, datetime.min.time(), UTC)
        )

    async def record_publication_outcome(self, _session: Any, *, booking_id: UUID, **_: Any) -> Any:
        return SimpleNamespace(id=booking_id, founder_id=uuid4(), product_id=uuid4())


class _Notifications:
    def __init__(self) -> None:
        self.send_review_email = True
        self.preferences: list[UUID] = []
        self.live: list[UUID] = []

    async def update_launch_preferences(self, _session: Any, *, actor_id: UUID, **_: Any) -> None:
        self.preferences.append(actor_id)

    async def record_launch_notice(self, _session: Any, *, booking: Any, **_: Any) -> None:
        self.live.append(booking.id)


class _Scope:
    async def __aenter__(self) -> _Scope:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> _Scope:
        return self


class _Sessions:
    def __call__(self) -> _Scope:
        return _Scope()

    def begin(self) -> _Scope:
        return _Scope()


def test_public_manifest_covers_anchor_and_seven_prior_days_with_distinct_media_keys() -> None:
    assert len(PUBLIC_PRODUCT_FIXTURES) == 20
    assert len({fixture.name for fixture in PUBLIC_PRODUCT_FIXTURES}) == 20
    assert {fixture.day_offset for fixture in PUBLIC_PRODUCT_FIXTURES} == set(range(8))
    assert len({topic for fixture in PUBLIC_PRODUCT_FIXTURES for topic in fixture.topics}) >= 3
    assert len({fixture.website_url for fixture in PUBLIC_PRODUCT_FIXTURES}) == 20


def test_public_launches_use_review_booking_publication_and_keep_rerun_ids() -> None:
    async def verify() -> None:
        ownership, products = _Ownership(), _Products()
        launches, notifications = _Launches(products), _Notifications()
        media = {
            f"launched-{index:02d}-{kind}": f"image-{index}-{kind}".encode()
            for index in range(1, 21)
            for kind in ("logo", "screenshot")
        }
        service = DemoSeedService(
            products=cast(Any, products),
            launches=cast(Any, launches),
            notifications=cast(Any, notifications),
            storage=cast(Any, object()),
            ownership=cast(Any, ownership),
            product_media=media,
            clock=lambda: datetime(2026, 10, 26, 12, tzinfo=UTC),
        )
        founder_ids = {f"founder-{index:02d}": uuid4() for index in range(1, 21)}
        results = await service.seed_public_launches(
            cast(Any, _Sessions()),
            target_id="local-development",
            anchor_utc_date=date(2026, 10, 26),
            founder_ids=founder_ids,
            reviewer_id=uuid4(),
        )

        assert len(results) == 20
        assert len(products.rows) == len(launches.bookings) == len(products.published) == 20
        assert {product.status for product in products.rows.values()} == {"launched"}
        assert {launch_date for _, launch_date in launches.bookings} == {
            date(2026, 10, 26) - timedelta(days=offset) for offset in range(8)
        }
        assert notifications.send_review_email is False
        assert products.review_count == len(notifications.live) == 20
        assert notifications.preferences == list(founder_ids.values())
        assert all(
            "launchpad.example" in product.content.website_url for product in products.rows.values()
        )

        replay = await service.seed_public_launches(
            cast(Any, _Sessions()),
            target_id="local-development",
            anchor_utc_date=date(2026, 10, 27),
            founder_ids=founder_ids,
            reviewer_id=uuid4(),
        )
        assert replay == results
        assert len(products.rows) == 20
        assert len(launches.bookings) == 20
        assert products.review_count == 20

    asyncio.run(verify())
