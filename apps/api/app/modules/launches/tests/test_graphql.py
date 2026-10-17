"""Launch GraphQL fields remain owner-scoped and expose a narrow public projection."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

from graphql import GraphQLObjectType, get_named_type
from strawberry import Schema

from app.graphql import Query
from app.modules.auth.sessions import MemberContext
from app.modules.launches.service import LaunchBookingPage, LaunchBookingRead
from app.modules.products.service import ProductAssetResult, PublicProductProjection


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None


def _context(member: MemberContext | None, **values: object) -> dict[str, object]:
    return {
        "member": member,
        "session_factory": _SessionContext,
        **values,
    }


def test_viewer_launch_bookings_returns_owner_failure_details_and_cursor() -> None:
    async def verify() -> None:
        account_id, product_id, booking_id = uuid4(), uuid4(), uuid4()
        created_at = datetime(2026, 10, 17, tzinfo=UTC)
        service = _Bookings(
            LaunchBookingPage(
                items=(
                    LaunchBookingRead(
                        id=booking_id,
                        product_id=product_id,
                        state="missed_day",
                        product_status="approved",
                        launch_date=date(2026, 10, 16),
                        launch_at=datetime(2026, 10, 16, tzinfo=UTC),
                        failure_reason="missed_day",
                        created_at=created_at,
                        closed_at=created_at,
                    ),
                ),
                next_cursor="opaque-cursor",
            )
        )
        result = await Schema(query=Query).execute(
            "query { viewerLaunchBookings { items { id productId state productStatus "
            "launchDate failureReason } nextCursor } }",
            context_value=_context(
                MemberContext(account_id=account_id, verified=True, session_id=uuid4()),
                launch_booking_service_factory=lambda: service,
            ),
        )

        assert result.errors is None
        assert result.data == {
            "viewerLaunchBookings": {
                "items": [
                    {
                        "id": str(booking_id),
                        "productId": str(product_id),
                        "state": "missed_day",
                        "productStatus": "approved",
                        "launchDate": "2026-10-16",
                        "failureReason": "missed_day",
                    }
                ],
                "nextCursor": "opaque-cursor",
            }
        }
        assert service.calls[0][0] == account_id

    asyncio.run(verify())


def test_launch_bookings_requires_an_authenticated_owner() -> None:
    async def verify() -> None:
        result = await Schema(query=Query).execute(
            "query { viewerLaunchBookings { items { id } } }",
            context_value=_context(None),
        )

        assert result.data is None
        assert result.errors is not None
        assert result.errors[0].message == "authentication required"

    asyncio.run(verify())


def test_viewer_launch_preferences_returns_saved_and_default_channel_values() -> None:
    async def verify() -> None:
        account_id = uuid4()
        defaults = {
            "reminder_email": True,
            "reminder_in_site": True,
            "live_email": True,
            "live_in_site": True,
            "failure_email": True,
            "failure_in_site": True,
        }
        service = _LaunchPreferences(defaults)
        result = await Schema(query=Query).execute(
            "query { viewerLaunchNotificationPreferences { reminderEmail reminderInSite "
            "liveEmail liveInSite failureEmail failureInSite } }",
            context_value=_context(
                MemberContext(account_id=account_id, verified=True, session_id=uuid4()),
                notification_service_factory=lambda: service,
            ),
        )

        assert result.errors is None
        assert result.data == {
            "viewerLaunchNotificationPreferences": {
                "reminderEmail": True,
                "reminderInSite": True,
                "liveEmail": True,
                "liveInSite": True,
                "failureEmail": True,
                "failureInSite": True,
            }
        }
        assert service.account_id == account_id

    asyncio.run(verify())


def test_public_product_contains_only_the_launched_public_projection() -> None:
    async def verify() -> None:
        product_id, asset_id = uuid4(), uuid4()
        projection = PublicProductProjection(
            id=product_id,
            name="Public launch",
            pitch="A concise pitch",
            description="Public description",
            website_url="https://example.test",
            launched_at=datetime(2026, 10, 17, tzinfo=UTC),
            logo=ProductAssetResult(
                id=asset_id,
                kind="logo",
                state="clean",
                media_type="image/png",
                byte_count=123,
            ),
            screenshots=(),
            topics=("Developer tools",),
        )
        service = _PublicProducts(projection)
        schema = Schema(query=Query)
        result = await schema.execute(
            'query { publicProduct(id: "' + str(product_id) + '") { id name pitch '
            "websiteUrl launchedAt logo { id kind mediaType byteCount url } topics } }",
            context_value=_context(None, product_service_factory=lambda: service),
        )

        assert result.errors is None
        assert result.data is not None
        product = result.data["publicProduct"]
        assert product["id"] == str(product_id)
        assert product["logo"]["url"] == (f"/api/v1/products/{product_id}/assets/{asset_id}/public")
        query_type = schema._schema.query_type
        assert query_type is not None
        public_type = get_named_type(query_type.fields["publicProduct"].type)
        assert isinstance(public_type, GraphQLObjectType)
        assert set(public_type.fields) == {
            "id",
            "name",
            "pitch",
            "description",
            "websiteUrl",
            "launchedAt",
            "logo",
            "screenshots",
            "topics",
        }

    asyncio.run(verify())


class _Bookings:
    def __init__(self, page: LaunchBookingPage) -> None:
        self.page = page
        self.calls: list[tuple[object, int, str | None]] = []

    async def owner_bookings(
        self,
        _session: object,
        *,
        actor_id: object,
        first: int,
        after: str | None,
    ) -> LaunchBookingPage:
        self.calls.append((actor_id, first, after))
        return self.page


class _PublicProducts:
    def __init__(self, projection: PublicProductProjection | None) -> None:
        self.projection = projection

    async def public_projection(
        self, _session: object, *, product_id: object
    ) -> PublicProductProjection | None:
        if self.projection is not None:
            assert product_id == self.projection.id
        return self.projection


class _LaunchPreferences:
    def __init__(self, values: dict[str, bool]) -> None:
        self.values = values
        self.account_id: object | None = None

    async def launch_preferences(self, _session: object, *, actor_id: object) -> dict[str, bool]:
        self.account_id = actor_id
        return self.values
