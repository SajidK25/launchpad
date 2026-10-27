"""Cleanup is limited to seed-owned never-reviewed private examples."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from app.operations.demo_seed.service import DemoSeedService


class _Ownership:
    def __init__(self, artifacts: list[SimpleNamespace]) -> None:
        self.artifacts = artifacts
        self.deleted: list[str] = []

    async def list_artifacts(self, _session: Any, *, target_id: str) -> list[SimpleNamespace]:
        return [row for row in self.artifacts if row.target_id == target_id]

    async def delete_artifact(self, _session: Any, *, seed_key: str, **_: Any) -> bool:
        self.deleted.append(seed_key)
        return True


class _Products:
    def __init__(self, records: dict[Any, SimpleNamespace]) -> None:
        self.records = records
        self.withdrawn: list[Any] = []
        self.deleted: list[Any] = []

    async def owner_detail(self, _session: Any, *, product_id: Any, **_: Any) -> Any:
        return self.records[product_id]

    async def withdraw_submission(self, _session: Any, *, product_id: Any, **_: Any) -> Any:
        self.withdrawn.append(product_id)
        record = self.records[product_id]
        record.product.status = "draft"
        record.product.version += 1
        return record.product

    async def delete_draft(self, _session: Any, *, product_id: Any, **_: Any) -> None:
        self.deleted.append(product_id)


class _Notifications:
    send_review_email = True


class _Context:
    async def __aenter__(self) -> _Context:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> _Context:
        return self


class _Sessions:
    def __call__(self) -> _Context:
        return _Context()


def test_cleanup_withdraws_and_deletes_only_unreviewed_draft_and_pending() -> None:
    async def verify() -> None:
        target_id = "local-development"
        founder_ids = {f"founder-{index:02d}": uuid4() for index in range(1, 7)}
        fixture_keys = (
            "product-private-draft",
            "product-private-submitted",
            "product-private-changes-requested",
            "product-private-rejected",
            "product-private-approved",
            "product-private-scheduled",
        )
        states = ("draft", "submitted", "changes_requested", "rejected", "approved", "scheduled")
        products_by_id: dict[Any, SimpleNamespace] = {}
        artifacts: list[SimpleNamespace] = []
        for index, (seed_key, status) in enumerate(zip(fixture_keys, states, strict=True), start=1):
            product_id = uuid4()
            product = SimpleNamespace(id=product_id, status=status, version=2)
            decision = None if status in {"draft", "submitted"} else SimpleNamespace(outcome=status)
            submission = SimpleNamespace(id=uuid4()) if status == "submitted" else None
            products_by_id[product_id] = SimpleNamespace(
                product=product, review_outcome=decision, submission=submission
            )
            artifacts.append(
                SimpleNamespace(
                    target_id=target_id,
                    seed_key=seed_key,
                    artifact_kind="product",
                    entity_id=product_id,
                )
            )
        ownership, products = _Ownership(artifacts), _Products(products_by_id)
        service = DemoSeedService(
            products=cast(Any, products),
            launches=cast(Any, SimpleNamespace()),
            notifications=cast(Any, _Notifications()),
            storage=cast(Any, object()),
            ownership=cast(Any, ownership),
            product_media={},
            clock=lambda: datetime(2026, 10, 26, tzinfo=UTC),
        )

        result = await service.cleanup_unreviewed_products(
            cast(Any, _Sessions()), target_id=target_id, founder_ids=founder_ids
        )

        assert result == {"deleted": 2, "retained": 4}
        assert products.withdrawn == [artifacts[1].entity_id]
        assert products.deleted == [artifacts[0].entity_id, artifacts[1].entity_id]
        assert ownership.deleted == list(fixture_keys[:2])

    asyncio.run(verify())
