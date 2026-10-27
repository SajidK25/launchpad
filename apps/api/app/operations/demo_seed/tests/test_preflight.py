"""Seed-wide identity checks run before any ledger or domain writes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from app.operations.demo_seed.fixtures import FOUNDER_FIXTURES, PRIVATE_PRODUCT_FIXTURES
from app.operations.demo_seed.service import DemoSeedIdentityConflict, DemoSeedService


class _Ownership:
    async def list_artifacts(self, _session: Any, *, target_id: str) -> list[Any]:
        return []


class _Accounts:
    async def preflight_identity(
        self, _session: Any, *, email: str, owned_account_id: UUID | None
    ) -> UUID:
        assert owned_account_id is None
        key = email.split("@", maxsplit=1)[0]
        if key == "reviewer":
            return uuid4()
        index = int(key[-2:])
        return account_ids[index - 1]


class _Products:
    def __init__(self, collision: bool) -> None:
        self.collision = collision
        self.write_calls = 0

    async def owner_list(
        self, _session: Any, *, actor_id: UUID, first: int, after: str | None = None
    ) -> Any:
        assert first == 50
        assert after is None
        if self.collision and actor_id == account_ids[1]:
            return SimpleNamespace(
                items=(SimpleNamespace(id=uuid4(), content=SimpleNamespace(name="Fieldnote")),),
                next_cursor=None,
            )
        return SimpleNamespace(items=(), next_cursor=None)


account_ids = [uuid4() for _ in FOUNDER_FIXTURES]


def test_seed_preflight_rejects_unowned_product_before_any_seed_writes() -> None:
    async def verify() -> None:
        products = _Products(collision=True)
        service = DemoSeedService(
            products=cast(Any, products),
            launches=cast(Any, SimpleNamespace()),
            notifications=cast(Any, SimpleNamespace(send_review_email=True)),
            storage=cast(Any, object()),
            ownership=cast(Any, _Ownership()),
            accounts=cast(Any, _Accounts()),
            product_media={},
            clock=lambda: datetime(2026, 10, 26, tzinfo=UTC),
        )

        with pytest.raises(DemoSeedIdentityConflict, match="product-private-submitted"):
            await service.preflight_seed(cast(Any, object()), target_id="local-development")

        assert products.write_calls == 0

    asyncio.run(verify())


def test_seed_preflight_accepts_unowned_new_identities_without_writing() -> None:
    async def verify() -> None:
        products = _Products(collision=False)
        service = DemoSeedService(
            products=cast(Any, products),
            launches=cast(Any, SimpleNamespace()),
            notifications=cast(Any, SimpleNamespace(send_review_email=True)),
            storage=cast(Any, object()),
            ownership=cast(Any, _Ownership()),
            accounts=cast(Any, _Accounts()),
            product_media={},
            clock=lambda: datetime(2026, 10, 26, tzinfo=UTC),
        )

        existing_accounts = await service.preflight_seed(
            cast(Any, object()), target_id="local-development"
        )

        assert {key: existing_accounts[key] for key in existing_accounts if key != "reviewer"} == {
            fixture.seed_key: account_ids[index] for index, fixture in enumerate(FOUNDER_FIXTURES)
        }
        assert "reviewer" in existing_accounts
        assert len(PRIVATE_PRODUCT_FIXTURES) == 6
        assert products.write_calls == 0

    asyncio.run(verify())
