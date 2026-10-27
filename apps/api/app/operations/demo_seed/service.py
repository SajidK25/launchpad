"""Service orchestration for repeatable private product workflow examples."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.provisioning import DemoAccountProvisioningService
from app.modules.launches.service import LaunchBookingService
from app.modules.notifications.service import NotificationService
from app.modules.products.schemas import ProductAssetIntentInput, ProductContentInput
from app.modules.products.service import (
    ProductAssetStorage,
    ProductDeleteStorage,
    ProductService,
)
from app.modules.users.service import ProfileService
from app.operations.demo_seed.fixtures import (
    FOUNDER_FIXTURES,
    PRIVATE_PRODUCT_FIXTURES,
    PUBLIC_PRODUCT_FIXTURES,
    REVIEWER_FIXTURE,
    PrivateProductFixture,
    PublicProductFixture,
)
from app.operations.demo_seed.repository import DemoSeedRepository


class DemoSeedStorage(ProductAssetStorage, ProductDeleteStorage, Protocol):
    """Private product media operations needed by provisioning and cleanup."""


class DemoSeedIdentityConflict(ValueError):
    """A planned demo key collides with an entity outside its ownership ledger."""

    def __init__(self, seed_key: str) -> None:
        super().__init__(f"demo fixture identity collision: {seed_key}")


class DemoSeedService:
    """Coordinate domain-owned product transitions and ledger ownership."""

    def __init__(
        self,
        *,
        products: ProductService,
        launches: LaunchBookingService,
        storage: DemoSeedStorage,
        ownership: DemoSeedRepository | None = None,
        notifications: NotificationService,
        accounts: DemoAccountProvisioningService | None = None,
        profiles: ProfileService | None = None,
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
        self.accounts = accounts
        self.profiles = profiles

    async def preflight_seed(self, session: AsyncSession, *, target_id: str) -> dict[str, UUID]:
        """Validate all planned account/product identities before the first write."""

        if self.accounts is None:
            raise RuntimeError("auth provisioning service is required")
        artifacts = await self.ownership.list_artifacts(session, target_id=target_id)
        by_key = {artifact.seed_key: artifact for artifact in artifacts}
        account_ids: dict[str, UUID] = {}
        for fixture in (*FOUNDER_FIXTURES, REVIEWER_FIXTURE):
            key = f"account:{fixture.seed_key}"
            artifact = by_key.get(key)
            if artifact is not None and artifact.artifact_kind != "account":
                raise RuntimeError("seed account ownership kind does not match")
            account_id = await self.accounts.preflight_identity(
                session,
                email=fixture.email,
                owned_account_id=artifact.entity_id if artifact is not None else None,
            )
            if account_id is not None:
                account_ids[fixture.seed_key] = account_id

        fixtures: tuple[PrivateProductFixture | PublicProductFixture, ...] = (
            *PRIVATE_PRODUCT_FIXTURES,
            *PUBLIC_PRODUCT_FIXTURES,
        )
        products_by_owner: dict[UUID, set[tuple[UUID, str]]] = {}
        for product_fixture in fixtures:
            founder_id = account_ids.get(product_fixture.founder_key)
            if founder_id is None:
                if by_key.get(product_fixture.seed_key) is not None:
                    raise DemoSeedIdentityConflict(product_fixture.seed_key)
                continue
            if founder_id not in products_by_owner:
                owner_products: set[tuple[UUID, str]] = set()
                cursor: str | None = None
                while True:
                    page = await self.products.owner_list(
                        session, actor_id=founder_id, first=50, after=cursor
                    )
                    owner_products.update((item.id, item.content.name or "") for item in page.items)
                    if page.next_cursor is None:
                        break
                    cursor = page.next_cursor
                products_by_owner[founder_id] = owner_products
            owned = by_key.get(product_fixture.seed_key)
            if owned is not None and owned.artifact_kind != "product":
                raise RuntimeError("seed product ownership kind does not match")
            expected_id = owned.entity_id if owned is not None else None
            matching = [
                product_id
                for product_id, name in products_by_owner[founder_id]
                if name.casefold() == product_fixture.name.casefold()
            ]
            if any(product_id != expected_id for product_id in matching):
                raise DemoSeedIdentityConflict(product_fixture.seed_key)
            if expected_id is not None and not any(
                product_id == expected_id for product_id, _ in products_by_owner[founder_id]
            ):
                raise DemoSeedIdentityConflict(product_fixture.seed_key)
        return account_ids

    async def seed_accounts_and_profiles(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        target_id: str,
        passwords: Mapping[str, str],
        profile_media: Mapping[str, bytes],
    ) -> dict[str, UUID]:
        """Provision verified founders/reviewer and publish their complete profiles."""

        if self.accounts is None or self.profiles is None:
            raise RuntimeError("auth and profile provisioning services are required")
        account_ids: dict[str, UUID] = {}
        all_identities = (*FOUNDER_FIXTURES, REVIEWER_FIXTURE)
        for fixture in all_identities:
            password = passwords.get(fixture.seed_key)
            if not password:
                raise ValueError(f"missing credential for {fixture.seed_key}")
            account_key = f"account:{fixture.seed_key}"
            async with sessions() as session, session.begin():
                artifact = await self.ownership.get_artifact(
                    session, target_id=target_id, seed_key=account_key
                )
                if artifact is not None and artifact.artifact_kind != "account":
                    raise RuntimeError("seed account ownership kind does not match")
                result = await self.accounts.provision_verified_account(
                    session,
                    email=fixture.email,
                    password=password,
                    owned_account_id=artifact.entity_id if artifact is not None else None,
                )
                if fixture.seed_key == "reviewer":
                    await self.accounts.grant_reviewer(
                        session,
                        account_id=result.account_id,
                        actor="demo-seed-operator",
                    )
                if artifact is None:
                    await self.ownership.record_artifact(
                        session,
                        target_id=target_id,
                        seed_key=account_key,
                        artifact_kind="account",
                        entity_id=result.account_id,
                        now=self.clock().astimezone(UTC),
                    )
                if fixture.seed_key != "reviewer":
                    await self.notifications.update_launch_preferences(
                        session,
                        actor_id=result.account_id,
                        values={
                            "reminder_email": False,
                            "reminder_in_site": True,
                            "live_email": False,
                            "live_in_site": True,
                            "failure_email": False,
                            "failure_in_site": True,
                        },
                    )
                account_ids[fixture.seed_key] = result.account_id

            if fixture.seed_key == "reviewer":
                continue
            photo = profile_media.get(fixture.avatar_key)
            if not photo:
                raise ValueError(f"missing validated profile fixture: {fixture.avatar_key}")
            async with sessions() as session, session.begin():
                await self.profiles.provision_demo_profile(
                    session,
                    actor_id=account_ids[fixture.seed_key],
                    seed_key=fixture.seed_key,
                    display_name=fixture.display_name,
                    bio=fixture.bio,
                    links=list(fixture.profile_links),
                    photo_bytes=photo,
                    content_type="image/png",
                    storage=self.storage,
                )
                profile_key = f"profile:{fixture.seed_key}"
                profile_artifact = await self.ownership.get_artifact(
                    session, target_id=target_id, seed_key=profile_key
                )
                if profile_artifact is None:
                    await self.ownership.record_artifact(
                        session,
                        target_id=target_id,
                        seed_key=profile_key,
                        artifact_kind="profile",
                        entity_id=account_ids[fixture.seed_key],
                        now=self.clock().astimezone(UTC),
                    )
                elif (
                    profile_artifact.artifact_kind != "profile"
                    or profile_artifact.entity_id != account_ids[fixture.seed_key]
                ):
                    raise RuntimeError("seed profile ownership does not match")
        return account_ids

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
                media_key=f"private-{fixture.seed_key.removeprefix('product-private-')}-logo",
            )
            screenshot_id = await self._upload_asset(
                session,
                founder_id=founder_id,
                product_id=saved.id,
                kind="screenshot",
                media_key=f"private-{fixture.seed_key.removeprefix('product-private-')}-screenshot",
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

    async def cleanup_unreviewed_products(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        target_id: str,
        founder_ids: Mapping[str, UUID],
    ) -> dict[str, int]:
        """Delete only owned draft/pending examples with no review outcome.

        Product deletion and pending-submission withdrawal use the products
        service. All non-private workflow examples and public launch history are
        retained, and only the exact ownership row is removed after domain success.
        """

        founder_by_seed_key = {
            fixture.seed_key: founder_ids[fixture.founder_key]
            for fixture in PRIVATE_PRODUCT_FIXTURES
            if fixture.founder_key in founder_ids
        }
        counts = {"deleted": 0, "retained": 0}
        async with sessions() as session:
            artifacts = await self.ownership.list_artifacts(session, target_id=target_id)
        for artifact in artifacts:
            if artifact.artifact_kind != "product" or artifact.seed_key not in founder_by_seed_key:
                continue
            founder_id = founder_by_seed_key[artifact.seed_key]
            async with sessions() as session, session.begin():
                detail = await self.products.owner_detail(
                    session, actor_id=founder_id, product_id=artifact.entity_id
                )
                if detail.review_outcome is not None:
                    counts["retained"] += 1
                    continue
                product = detail.product
                if product.status == "submitted" and detail.submission is not None:
                    product = await self.products.withdraw_submission(
                        session,
                        actor_id=founder_id,
                        product_id=product.id,
                        submission_id=detail.submission.id,
                        expected_version=product.version,
                    )
                if product.status != "draft":
                    counts["retained"] += 1
                    continue
                await self.products.delete_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product.id,
                    expected_version=product.version,
                    storage=self.storage,
                )
                if not await self.ownership.delete_artifact(
                    session,
                    target_id=target_id,
                    seed_key=artifact.seed_key,
                    entity_id=artifact.entity_id,
                ):
                    raise RuntimeError("seed ownership changed during cleanup")
                counts["deleted"] += 1
        return counts

    async def rotate_credentials(
        self,
        session: AsyncSession,
        *,
        target_id: str,
        account_keys: tuple[str, ...],
        passwords: Mapping[str, str],
    ) -> dict[str, str]:
        """Rotate only selected account artifacts after proving target ownership."""

        if self.accounts is None:
            raise RuntimeError("auth provisioning service is required")
        if not account_keys or len(account_keys) != len(set(account_keys)):
            raise ValueError("credential rotation selection is invalid")
        artifacts = await self.ownership.list_artifacts(session, target_id=target_id)
        owned = {
            artifact.seed_key.removeprefix("account:"): artifact
            for artifact in artifacts
            if artifact.artifact_kind == "account" and artifact.seed_key.startswith("account:")
        }
        if any(key not in owned for key in account_keys):
            raise ValueError("credential rotation includes an unowned account key")
        replacements: dict[str, str] = {}
        for key in account_keys:
            password = passwords.get(key)
            if not password:
                raise ValueError(f"missing replacement credential for {key}")
            rotated = await self.accounts.rotate_owned_password(
                session, account_id=owned[key].entity_id, password=password
            )
            if not rotated:
                raise RuntimeError("owned account is unavailable for credential rotation")
            replacements[key] = password
        return replacements

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
