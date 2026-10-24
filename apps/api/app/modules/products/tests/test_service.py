"""Product publication events and the narrow voting-context service port."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

from app.modules.products.service import ProductService


class _Transaction(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class _Session:
    def begin_nested(self) -> _Transaction:
        return _Transaction()


class _Accounts:
    async def current_account(self, *_args: object, **_kwargs: object) -> Any:
        return SimpleNamespace(suspended_at=None)


class _Repository:
    def __init__(self, product: Any) -> None:
        self.product = product

    async def get_product(self, *_args: object, **_kwargs: object) -> Any:
        return self.product

    async def transition_launch_state(self, _session: Any, **values: Any) -> Any:
        product = values["product"]
        product.status = values["to_status"]
        product.version += 1
        product.updated_at = values["now"]
        product.launched_at = values.get("launched_at")
        product.launch_failure_reason = values.get("failure_reason")
        return product


class _Outbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def add(self, _session: Any, event: Any) -> UUID:
        self.events.append(event)
        return uuid4()


class _Codec:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def encode(self, payload: Any) -> tuple[str, bytes]:
        self.payloads.append(dict(payload))
        return "test", b"encrypted"


def _product(*, status: str = "scheduled") -> Any:
    return SimpleNamespace(
        id=uuid4(),
        founder_id=uuid4(),
        status=status,
        version=7,
        launched_at=None,
        launch_failure_reason=None,
        updated_at=datetime(2026, 10, 24, tzinfo=UTC),
    )


def _service(product: Any, outbox: _Outbox, codec: _Codec) -> ProductService:
    return ProductService(
        member_access=cast(Any, _Accounts()),
        outbox_repository=cast(Any, outbox),
        payload_codec=cast(Any, codec),
        repository=cast(Any, _Repository(product)),
        clock=lambda: datetime(2026, 10, 24, tzinfo=UTC),
    )


def test_successful_scheduled_publication_emits_one_durable_launch_event() -> None:
    async def verify() -> None:
        product, outbox, codec = _product(), _Outbox(), _Codec()
        service = _service(product, outbox, codec)
        now = datetime(2026, 10, 24, tzinfo=UTC)
        launched = await service.publish_scheduled_product(
            cast(Any, _Session()), product_id=product.id, launch_at=now, now=now
        )
        assert launched.status == "launched" and launched.version == 8
        assert len(outbox.events) == 1
        assert outbox.events[0].event_type == "product.launched.v1"
        assert outbox.events[0].aggregate_id == product.id
        assert codec.payloads == [
            {
                "product_id": product.id,
                "owner_account_id": product.founder_id,
                "launch_date": date(2026, 10, 24).isoformat(),
            }
        ]

    asyncio.run(verify())


def test_publication_replay_does_not_emit_a_duplicate_launch_event() -> None:
    async def verify() -> None:
        product, outbox, codec = _product(), _Outbox(), _Codec()
        service = _service(product, outbox, codec)
        now = datetime(2026, 10, 24, tzinfo=UTC)
        await service.publish_scheduled_product(
            cast(Any, _Session()), product_id=product.id, launch_at=now, now=now
        )
        await service.publish_scheduled_product(
            cast(Any, _Session()), product_id=product.id, launch_at=now, now=now
        )
        assert len(outbox.events) == 1
        assert product.version == 8

    asyncio.run(verify())


def test_failed_or_non_launch_outcomes_do_not_emit_launch_event() -> None:
    async def verify() -> None:
        product, outbox, codec = _product(), _Outbox(), _Codec()
        service = _service(product, outbox, codec)
        launch_at = datetime(2026, 10, 23, tzinfo=UTC)
        result = await service.publish_scheduled_product(
            cast(Any, _Session()),
            product_id=product.id,
            launch_at=launch_at,
            now=datetime(2026, 10, 24, tzinfo=UTC),
        )
        assert result.status == "approved"
        assert outbox.events == []

    asyncio.run(verify())


def test_voting_context_exposes_only_launched_product_eligibility_fields() -> None:
    async def verify() -> None:
        product = _product(status="launched")
        product.launched_at = datetime(2026, 10, 24, tzinfo=UTC)
        service = _service(product, _Outbox(), _Codec())
        context = await service.voting_context(cast(Any, _Session()), product_id=product.id)
        assert context is not None
        assert context.product_id == product.id
        assert context.owner_account_id == product.founder_id
        assert context.launch_date == date(2026, 10, 24)
        assert context.launched is True
        assert not hasattr(context, "name")

        product.status = "approved"
        assert await service.voting_context(cast(Any, _Session()), product_id=product.id) is None

    asyncio.run(verify())
