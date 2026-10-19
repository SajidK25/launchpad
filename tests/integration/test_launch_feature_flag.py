"""PostgreSQL-backed checks for reversible launch API rollout."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, date, datetime, time
from typing import Any, cast
from uuid import uuid4

import pytest
from app.main import create_app
from app.modules.auth.models import Account
from app.modules.launches.models import LaunchBooking
from app.modules.products.models import Product
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.events.models import OutboxMessage
from conftest import IntegrationSettings
from pydantic import SecretStr
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_launch_routes_are_reversible_without_rolling_back_data(
    integration_settings_fixture: IntegrationSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled launch routes hide commands while durable booking and outbox rows remain."""

    import sys

    main = cast(Any, sys.modules["app.main"])
    database = Database.connect(integration_settings_fixture.database_url)
    now = datetime.now(UTC)
    founder_id = uuid4()
    product_id = uuid4()

    async def verify() -> None:
        await database.prepare()
        factory = async_sessionmaker(database.engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            await session.execute(
                insert(Account).values(
                    id=founder_id,
                    email_display=f"launch-flag-{founder_id.hex}@example.test",
                    email_key=f"launch-flag-{founder_id.hex}@example.test",
                    password_hash="test-only-hash",
                    role="member",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.execute(
                insert(Product).values(
                    id=product_id,
                    founder_id=founder_id,
                    status="approved",
                    version=1,
                    name="Launch flag fixture",
                    pitch="Private launch flag fixture",
                    description="Fixture content remains private while launch commands are gated.",
                    website_url="https://example.test/launch-flag",
                    website_key="example.test/launch-flag",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.execute(
                insert(LaunchBooking).values(
                    id=uuid4(),
                    product_id=product_id,
                    founder_id=founder_id,
                    launch_date=date(2099, 1, 2),
                    launch_at=datetime.combine(date(2099, 1, 2), time.min, UTC),
                    state="scheduled",
                    idempotency_key="launch-flag-test-booking",
                    request_fingerprint="a" * 64,
                    created_at=now,
                )
            )
            await session.execute(
                insert(OutboxMessage).values(
                    id=uuid4(),
                    event_type="launch.publication_scheduled",
                    aggregate_id=product_id,
                    encrypted_payload=b"test-only-encrypted-payload",
                    key_id="launch-flag-test",
                    available_at=now,
                    state="pending",
                )
            )

        monkeypatch.setattr(main.Database, "connect", lambda _: database)

        def build_settings(*, launches_enabled: bool) -> Settings:
            return Settings(
                environment="check",
                products_enabled=False,
                launches_enabled=launches_enabled,
                database_url=integration_settings_fixture.database_url,
                redis_url=integration_settings_fixture.redis_url,
                storage_endpoint_url=integration_settings_fixture.s3_endpoint_url,
                storage_access_key_id=SecretStr(integration_settings_fixture.s3_access_key_id),
                storage_secret_access_key=SecretStr(
                    integration_settings_fixture.s3_secret_access_key
                ),
                storage_bucket="launchpad-private",
                public_upload_endpoint_url="http://localhost:9000",
                mail_web_origin="http://localhost:8080",
                mail_sender="launchpad@example.com",
                outbox_key_id="launch-flag-test",
                outbox_key=SecretStr(base64.b64encode(b"f" * 32).decode("ascii")),
                trusted_web_origins=("http://localhost:8080",),
            )

        monkeypatch.setattr(main, "load_settings", lambda: build_settings(launches_enabled=False))
        disabled_paths = set(create_app().openapi()["paths"])
        assert "/api/v1/me/products/{product_id}/launch-booking" not in disabled_paths
        assert "/api/v1/me/launch-notification-preferences" not in disabled_paths
        assert "/api/v1/me/notifications/{notification_id}/read" in disabled_paths

        monkeypatch.setattr(main, "load_settings", lambda: build_settings(launches_enabled=True))
        enabled_paths = set(create_app().openapi()["paths"])
        assert "/api/v1/me/products/{product_id}/launch-booking" in enabled_paths
        assert "/api/v1/me/launch-notification-preferences" in enabled_paths

        async with factory() as session:
            booking_count = await session.scalar(
                select(func.count())
                .select_from(LaunchBooking)
                .where(LaunchBooking.product_id == product_id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(OutboxMessage)
                .where(OutboxMessage.aggregate_id == product_id)
            )
        assert (booking_count, outbox_count) == (1, 1)
        await database.close()

    asyncio.run(verify())
