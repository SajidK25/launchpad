"""Product content rules that are independent of transport and persistence."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol, cast
from urllib.parse import SplitResult, urlsplit
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.modules.auth.staff import AccountState
from app.modules.products.models import (
    Product,
    ProductAsset,
    ProductReviewDecision,
    ProductSubmission,
)
from app.modules.products.policies import (
    PRODUCT_MEDIA_URL_TTL_SECONDS,
    ProductConflictError,
    ProductForbiddenError,
    ProductInfrastructureError,
    ProductNotFoundError,
    ProductQuotaError,
    create_product_media_signature,
    require_active_founder,
    require_draft_status,
    require_editable_status,
    require_expected_version,
    require_product_not_reviewed,
    require_product_owner,
    require_review_transition,
    require_staff_reviewer,
    verify_product_media_signature,
)
from app.modules.products.schemas import ProductAssetIntentInput, ProductContentInput
from app.shared.events.outbox import OutboxEvent, OutboxRepository, PermanentEventError
from app.shared.storage.objects import (
    CleanPhoto,
    ObjectNotFound,
    ObjectOperationError,
    ObjectValidationError,
    StagingUpload,
)

if TYPE_CHECKING:
    from app.modules.products.repository import ProductRepository, TopicChoice


class ProductValidationError(ValueError):
    """A product field or set of fields is invalid for the requested operation."""

    def __init__(self, message: str, *, fields: tuple[str, ...]) -> None:
        super().__init__(message)
        self.fields = fields


@dataclass(frozen=True, slots=True)
class TopicLabel:
    """A founder's own spelling paired with its private canonical topic key."""

    display_name: str
    name_key: str


class ProductMemberAccess(Protocol):
    """Named auth-owned account state and account lock boundary."""

    async def current_account(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None: ...

    async def founder_states(
        self, session: AsyncSession, account_ids: Sequence[UUID]
    ) -> dict[UUID, AccountState]: ...


class ProductPayloadCodec(Protocol):
    """Encrypt minimal product event payloads before outbox persistence."""

    def encode(self, payload: Mapping[str, object]) -> tuple[str, bytes]: ...


class ProductEvents(Protocol):
    """Transactional outbox interface used by the products feature."""

    async def add(self, session: AsyncSession, event: OutboxEvent) -> UUID: ...


class ReviewNoticeDecision(Protocol):
    """Small immutable decision shape passed across the notification boundary."""

    id: UUID
    outcome: str


class ProductReviewNotifications(Protocol):
    """Named notifications interface used within a product decision transaction."""

    async def record_review_outcome(
        self,
        session: AsyncSession,
        *,
        decision: ReviewNoticeDecision,
        founder_id: UUID,
        product_id: UUID,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ProductDraft:
    """Owner-safe product draft view without exposing an ORM mapping."""

    id: UUID
    founder_id: UUID
    status: str
    version: int
    content: ProductContentInput
    website_key: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SubmissionPeriod:
    """Current owner-safe queue period and the product version it represents."""

    id: UUID
    product_id: UUID
    submitted_at: datetime
    product_version: int


@dataclass(frozen=True, slots=True)
class SubmittedProduct:
    """Owner-safe current submitted product snapshot."""

    id: UUID
    founder_id: UUID
    status: str
    version: int
    content: ProductContentInput
    website_key: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProductAssetResult:
    """Owner-safe asset lifecycle view without storage keys."""

    id: UUID
    kind: Literal["logo", "screenshot"]
    state: str
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    byte_count: int


@dataclass(frozen=True, slots=True)
class ProductTopicSelection:
    """The label chosen by this product's founder, not the shared topic label."""

    topic_id: UUID
    display_name: str
    position: int


@dataclass(frozen=True, slots=True)
class OwnerProductDetail:
    """Authorized editor snapshot of one private product."""

    product: ProductDraft
    topics: tuple[ProductTopicSelection, ...]
    assets: tuple[ProductAssetResult, ...]
    submission: SubmissionPeriod | None
    review_outcome: OwnerReviewOutcome | None = None


@dataclass(frozen=True, slots=True)
class OwnerReviewOutcome:
    """Latest founder-visible decision fields, without reviewer identity or audit keys."""

    status: str
    feedback: str | None


@dataclass(frozen=True, slots=True)
class OwnerProductPage:
    """Bounded private founder listing."""

    items: tuple[ProductDraft, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class StaffQueueItem:
    """Current pending product and flags visible to authorized reviewers only."""

    product: ProductDraft
    submission: SubmissionPeriod
    possible_duplicate: bool
    founder_suspended: bool


@dataclass(frozen=True, slots=True)
class StaffQueuePage:
    """Bounded oldest-first reviewer queue."""

    items: tuple[StaffQueueItem, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ApprovedReviewItem:
    """One currently approved product available to staff for a correction return."""

    product: ProductDraft
    submission: SubmissionPeriod
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class ApprovedReviewPage:
    """Bounded approved product discovery ordered by approval time and identity."""

    items: tuple[ApprovedReviewItem, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class StaffProductDetail:
    """One current pending product's complete private review snapshot."""

    product: OwnerProductDetail
    submission: SubmissionPeriod
    possible_duplicate: bool
    founder_suspended: bool


@dataclass(frozen=True, slots=True)
class ProductReviewResult:
    """Safe command result for one immutable staff review action."""

    decision: ProductReviewDecision
    product_id: UUID
    status: str
    version: int


@dataclass(frozen=True, slots=True)
class ProductAssetUpload:
    """Intent metadata and short-lived write-only storage capability."""

    asset: ProductAssetResult
    upload: StagingUpload


class ProductAssetStorage(Protocol):
    """Private object-storage operations required by the product asset lifecycle."""

    async def create_product_staging_upload(
        self,
        *,
        account_id: UUID,
        product_id: UUID,
        asset_id: UUID,
        content_type: str,
        size: int,
        expires_in: int = 300,
    ) -> StagingUpload: ...

    async def put_staging(self, *, object_key: str, body: bytes, content_type: str) -> None: ...

    async def finalize_product_staging(
        self,
        *,
        account_id: UUID,
        product_id: UUID,
        asset_id: UUID,
        declared_content_type: str | None = None,
    ) -> CleanPhoto: ...


class ProductEventStorage(Protocol):
    """Private object deletion interface used by durable product purge work."""

    async def delete_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> None: ...


class ProductDeleteStorage(Protocol):
    """Read-only private storage probe required before irreversible metadata deletion."""

    async def get_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> tuple[bytes, str | None]: ...


class ProductMediaStorage(Protocol):
    """Read clean product media through the private storage adapter."""

    async def get_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> tuple[bytes, str | None]: ...


@dataclass(frozen=True, slots=True)
class ProductPrivateMedia:
    """Validated private image bytes and response media type."""

    body: bytes
    media_type: str


class ProductService:
    """Create, load, and version private drafts under live account authorization."""

    DRAFT_LIMIT = 10
    PENDING_ASSET_LIMIT = 10
    ASSET_UPLOAD_EXPIRY_SECONDS = 300
    PRODUCT_MEDIA_URL_TTL_SECONDS = PRODUCT_MEDIA_URL_TTL_SECONDS
    ASSET_CLEANUP_GRACE = timedelta(hours=24)
    PRODUCT_STATE_EVENTS = frozenset(
        {
            "product.created.v1",
            "product.saved.v1",
            "product.submitted.v1",
            "product.withdrawn.v1",
            "product.deleted.v1",
            "product.asset_changed.v1",
        }
    )

    def __init__(
        self,
        *,
        member_access: ProductMemberAccess,
        outbox_repository: ProductEvents | None = None,
        payload_codec: ProductPayloadCodec,
        repository: ProductRepository | None = None,
        event_storage: ProductEventStorage | None = None,
        review_notifications: ProductReviewNotifications | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if repository is None:
            from app.modules.products.repository import ProductRepository

            repository = ProductRepository()
        self.repository = repository
        self.member_access = member_access
        self.outbox_repository = outbox_repository or OutboxRepository()
        self.payload_codec = payload_codec
        self.event_storage = event_storage
        if review_notifications is None:
            from app.modules.notifications.service import NotificationService
            from app.shared.email.codec import EmailPayloadCodec

            review_notifications = NotificationService(
                outbox_repository=cast(OutboxRepository, self.outbox_repository),
                payload_codec=cast(EmailPayloadCodec, payload_codec),
            )
        self.review_notifications = review_notifications
        self.clock = clock or (lambda: datetime.now(UTC))

    async def decide_review(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        submission_id: UUID,
        expected_version: int,
        outcome: str,
        feedback: str | None,
        idempotency_key: str,
    ) -> ProductReviewResult:
        """Resolve the current product version and persist audit/notice in one transaction."""

        require_staff_reviewer(
            await self.member_access.current_account(session, actor_id, lock=True)
        )
        key = idempotency_key.strip()
        normalized_feedback = feedback.strip() if feedback is not None else None
        if not key or len(key) > 255:
            raise ProductValidationError("invalid idempotency key", fields=("idempotency_key",))
        if outcome not in {"approved", "rejected", "changes_requested"}:
            raise ProductValidationError("invalid review outcome", fields=("outcome",))
        if outcome == "approved":
            if normalized_feedback is not None:
                raise ProductValidationError(
                    "approval cannot include feedback", fields=("feedback",)
                )
        elif normalized_feedback is None or len(normalized_feedback) > 2000:
            raise ProductValidationError(
                "feedback must contain 1 to 2,000 characters", fields=("feedback",)
            )

        fingerprint = _review_request_fingerprint(
            product_id=product_id,
            submission_id=submission_id,
            expected_version=expected_version,
            outcome=outcome,
            feedback=normalized_feedback,
        )
        async with session.begin_nested():
            replay = await self.repository.find_review_decision_by_actor_key(
                session, actor_id=actor_id, idempotency_key=key
            )
            if replay is not None:
                if not hmac.compare_digest(replay.request_fingerprint, fingerprint):
                    raise ProductConflictError("idempotency key was used for a different review")
                return ProductReviewResult(
                    decision=replay,
                    product_id=product_id,
                    status=replay.outcome,
                    version=replay.reviewed_product_version + 1,
                )

            product = await self.repository.get_product(session, product_id=product_id, lock=True)
            if product is None:
                raise ProductNotFoundError("product unavailable")
            require_review_transition(status=product.status, outcome=outcome)
            require_expected_version(current=product.version, expected=expected_version)

            if product.status == "submitted":
                submission = await self.repository.get_pending_submission(
                    session, product_id=product_id, lock=True
                )
                if (
                    submission is None
                    or submission.id != submission_id
                    or submission.product_version != expected_version
                ):
                    raise ProductConflictError("submission period has changed")
            else:
                submission = await self.repository.get_latest_submission(
                    session, product_id=product_id, lock=True
                )
                if (
                    submission is None
                    or submission.id != submission_id
                    or submission.state != "approved"
                ):
                    raise ProductConflictError("approved submission period has changed")

            current_status = product.status
            reviewed_version = product.version
            now = self.clock()
            updated = await self.repository.set_product_state(
                session, product=product, status=outcome, now=now
            )
            await self.repository.resolve_submission(
                session, submission=submission, outcome=outcome, closed_at=now
            )
            decision = await self.repository.create_review_decision(
                session,
                submission_id=submission.id,
                actor_id=actor_id,
                from_status=current_status,
                outcome=outcome,
                reviewed_product_version=reviewed_version,
                feedback=normalized_feedback,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                created_at=now,
            )
            try:
                await self.review_notifications.record_review_outcome(
                    session,
                    decision=decision,
                    founder_id=product.founder_id,
                    product_id=product.id,
                )
            except Exception as error:
                raise ProductInfrastructureError("review outcome could not be recorded") from error
            return ProductReviewResult(
                decision=decision,
                product_id=product.id,
                status=updated.status,
                version=updated.version,
            )

    async def create_draft(self, session: AsyncSession, *, actor_id: UUID) -> ProductDraft:
        """Create an incomplete private draft for any signed-in unsuspended member."""

        account = await self.member_access.current_account(session, actor_id, lock=True)
        require_active_founder(account)
        async with session.begin_nested():
            if await self.repository.count_drafts(session, founder_id=actor_id) >= self.DRAFT_LIMIT:
                raise ProductQuotaError("private draft limit reached")
            now = self.clock()
            product = await self.repository.create_draft(session, founder_id=actor_id, now=now)
            await self._record_event(session, product, event_type="product.created.v1", now=now)
            return _draft_view(product)

    async def sign_private_asset_url(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        session_secret: str,
        product_id: UUID,
        asset_id: UUID,
    ) -> str:
        """Issue a short-lived URL only after checking current private-media access."""

        await self._authorized_private_asset(
            session, actor_id=actor_id, product_id=product_id, asset_id=asset_id
        )
        path = _product_media_path(product_id, asset_id)
        expires_at = int(self.clock().timestamp()) + self.PRODUCT_MEDIA_URL_TTL_SECONDS
        signature = create_product_media_signature(session_secret, path, expires_at)
        return f"{path}?expires={expires_at}&signature={signature}"

    async def read_private_asset(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        session_secret: str,
        product_id: UUID,
        asset_id: UUID,
        expires_at: int,
        signature: str,
        storage: ProductMediaStorage,
    ) -> ProductPrivateMedia:
        """Revalidate the signed request and live authorization before every object read."""

        path = _product_media_path(product_id, asset_id)
        if not verify_product_media_signature(
            session_secret,
            path,
            expires_at,
            signature,
            now=self.clock(),
        ):
            raise ProductNotFoundError("product media unavailable")
        product, asset = await self._authorized_private_asset(
            session, actor_id=actor_id, product_id=product_id, asset_id=asset_id
        )
        if asset.clean_key is None:
            raise ProductNotFoundError("product media unavailable")
        try:
            body, _storage_media_type = await storage.get_product_private(
                account_id=product.founder_id,
                product_id=product.id,
                object_key=asset.clean_key,
            )
        except ObjectOperationError as error:
            raise ProductInfrastructureError("product media is unavailable") from error
        return ProductPrivateMedia(body=body, media_type=asset.media_type)

    async def _authorized_private_asset(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        asset_id: UUID,
    ) -> tuple[Product, ProductAsset]:
        account = await self.member_access.current_account(session, actor_id, lock=True)
        if account is None:
            raise ProductNotFoundError("product media unavailable")
        product = await self.repository.get_product(session, product_id=product_id, lock=True)
        if product is None:
            raise ProductNotFoundError("product media unavailable")
        is_owner = actor_id == product.founder_id
        if not is_owner:
            if (
                account.role not in {"reviewer", "admin"}
                or not account.verified
                or account.suspended_at is not None
                or product.status != "submitted"
                or await self.repository.get_pending_submission(
                    session, product_id=product.id, lock=True
                )
                is None
            ):
                raise ProductNotFoundError("product media unavailable")
        asset = await self.repository.get_asset(
            session, product_id=product.id, asset_id=asset_id, lock=True
        )
        if (
            asset is None
            or asset.state != "clean"
            or asset.attached_at is None
            or asset.clean_key is None
        ):
            raise ProductNotFoundError("product media unavailable")
        return product, asset

    async def get_draft(
        self, session: AsyncSession, *, actor_id: UUID, product_id: UUID
    ) -> ProductDraft:
        """Return a draft to its founder only, hiding absent and foreign products alike."""

        account = await self.member_access.current_account(session, actor_id)
        if account is None:
            raise ProductForbiddenError("product access is forbidden")
        product = await self.repository.get_draft(
            session, product_id=product_id, founder_id=actor_id
        )
        if product is None:
            raise ProductNotFoundError("product unavailable")
        require_product_owner(actor_id=actor_id, founder_id=product.founder_id)
        return _draft_view(product)

    async def owner_detail(
        self, session: AsyncSession, *, actor_id: UUID, product_id: UUID
    ) -> OwnerProductDetail:
        """Recheck account and ownership before projecting private content."""

        account = await self.member_access.current_account(session, actor_id)
        if account is None:
            raise ProductForbiddenError("product access is forbidden")
        product = await self.repository.get_owned_product(
            session, product_id=product_id, founder_id=actor_id
        )
        if product is None:
            raise ProductNotFoundError("product unavailable")
        topics = await self.repository.get_product_topics(session, product_id=product.id)
        assets = await self.repository.get_attached_clean_assets(session, product_id=product.id)
        submission = await self.repository.get_pending_submission(session, product_id=product.id)
        return OwnerProductDetail(
            product=_draft_view(product),
            topics=tuple(
                ProductTopicSelection(
                    topic_id=topic.topic_id,
                    display_name=topic.selected_label,
                    position=topic.position,
                )
                for topic in topics
            ),
            assets=tuple(_asset_view(asset) for asset in assets),
            submission=_submission_view(submission) if submission is not None else None,
            review_outcome=(
                OwnerReviewOutcome(
                    status=decision.outcome,
                    feedback=decision.feedback,
                )
                if (
                    decision := await self.repository.get_latest_review_decision(
                        session, product_id=product.id
                    )
                )
                is not None
                else None
            ),
        )

    async def owner_list(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        first: int = 20,
        after: str | None = None,
    ) -> OwnerProductPage:
        """Return a bounded list of only this account's private products."""

        account = await self.member_access.current_account(session, actor_id)
        if account is None:
            raise ProductForbiddenError("product access is forbidden")
        if not 1 <= first <= 50:
            raise ProductValidationError("invalid page size", fields=("first",))
        products = await self.repository.list_owner_products(
            session,
            founder_id=actor_id,
            limit=first + 1,
            after=_parse_read_cursor(after) if after is not None else None,
        )
        return OwnerProductPage(
            items=tuple(_draft_view(product) for product in products[:first]),
            next_cursor=(
                _read_cursor(products[first - 1].updated_at, products[first - 1].id)
                if len(products) > first
                else None
            ),
        )

    async def staff_queue(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        first: int = 20,
        after: str | None = None,
    ) -> StaffQueuePage:
        """Authorize live staff state and page only current pending periods."""

        require_staff_reviewer(await self.member_access.current_account(session, actor_id))
        if not 1 <= first <= 50:
            raise ProductValidationError("invalid page size", fields=("first",))
        cursor = _parse_read_cursor(after) if after is not None else None
        rows = await self.repository.list_pending_queue(session, limit=first + 1, after=cursor)
        visible = rows[:first]
        founder_states = await self.member_access.founder_states(
            session, [product.founder_id for _, product in visible]
        )
        duplicates = await self.repository.duplicate_website_keys(
            session,
            website_keys={product.website_key for _, product in visible if product.website_key},
        )
        items = tuple(
            StaffQueueItem(
                product=_draft_view(product),
                submission=_submission_view(period),
                possible_duplicate=product.website_key in duplicates,
                founder_suspended=(
                    founder_states.get(product.founder_id) is None
                    or founder_states[product.founder_id].suspended_at is not None
                ),
            )
            for period, product in visible
        )
        next_cursor = _queue_cursor(visible[-1][0]) if len(rows) > first and visible else None
        return StaffQueuePage(items=items, next_cursor=next_cursor)

    async def staff_detail(
        self, session: AsyncSession, *, actor_id: UUID, product_id: UUID
    ) -> StaffProductDetail:
        """Recheck a current pending period before showing complete review data."""

        require_staff_reviewer(await self.member_access.current_account(session, actor_id))
        product = await self.repository.get_product(session, product_id=product_id)
        if product is None or product.status not in {"submitted", "approved"}:
            raise ProductNotFoundError("product unavailable")
        period = (
            await self.repository.get_pending_submission(session, product_id=product_id)
            if product.status == "submitted"
            else await self.repository.get_latest_submission(session, product_id=product_id)
        )
        if period is None:
            raise ProductNotFoundError("product unavailable")
        if product.status == "approved" and period.state != "approved":
            raise ProductNotFoundError("product unavailable")
        topics = await self.repository.get_product_topics(session, product_id=product_id)
        assets = await self.repository.get_attached_clean_assets(session, product_id=product_id)
        founder_states = await self.member_access.founder_states(session, [product.founder_id])
        duplicates = await self.repository.duplicate_website_keys(
            session, website_keys={product.website_key} if product.website_key else set()
        )
        return StaffProductDetail(
            product=OwnerProductDetail(
                product=_draft_view(product),
                topics=tuple(
                    ProductTopicSelection(topic.topic_id, topic.selected_label, topic.position)
                    for topic in topics
                ),
                assets=tuple(_asset_view(asset) for asset in assets),
                submission=_submission_view(period),
            ),
            submission=_submission_view(period),
            possible_duplicate=product.website_key in duplicates,
            founder_suspended=(
                founder_states.get(product.founder_id) is None
                or founder_states[product.founder_id].suspended_at is not None
            ),
        )

    async def approved_review_page(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        first: int = 20,
        after: str | None = None,
    ) -> ApprovedReviewPage:
        """Find private, currently approved products for verified staff only."""

        require_staff_reviewer(await self.member_access.current_account(session, actor_id))
        if not 1 <= first <= 50:
            raise ProductValidationError("invalid page size", fields=("first",))
        cursor = _parse_read_cursor(after) if after is not None else None
        rows = await self.repository.list_approved_reviews(session, limit=first + 1, after=cursor)
        visible = rows[:first]
        items = tuple(
            ApprovedReviewItem(
                product=_draft_view(product),
                submission=_submission_view(period),
                approved_at=period.closed_at,
            )
            for period, product in visible
            if period.closed_at is not None
        )
        next_cursor = (
            _read_cursor(items[-1].approved_at, items[-1].product.id)
            if len(rows) > first and items
            else None
        )
        return ApprovedReviewPage(items=items, next_cursor=next_cursor)

    async def topic_choices(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID | None,
        query: str | None = None,
        first: int = 20,
    ) -> list[TopicChoice]:
        """Offer launched canonical names plus only the caller's own private proposals."""

        if not 1 <= first <= 50:
            raise ProductValidationError("invalid page size", fields=("first",))
        from app.modules.products.repository import TopicRepository

        topics = TopicRepository()
        launched = await topics.list_topic_choices(session, query=query, limit=first)
        choices = {choice.topic_id: choice for choice in launched}
        if actor_id is not None:
            account = await self.member_access.current_account(session, actor_id)
            if account is not None:
                for choice in await topics.list_owner_proposals(
                    session, founder_id=actor_id, query=query
                ):
                    choices.setdefault(choice.topic_id, choice)
        return sorted(choices.values(), key=lambda choice: choice.display_name.casefold())[:first]

    async def delete_draft(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        expected_version: int,
        storage: ProductDeleteStorage,
    ) -> None:
        """Delete only an owned private draft after storage preflight and durable purge."""

        account = await self.member_access.current_account(session, actor_id, lock=True)
        require_active_founder(account)
        async with session.begin_nested():
            product = await self.repository.get_owned_product(
                session, product_id=product_id, founder_id=actor_id, lock=True
            )
            if product is None:
                raise ProductNotFoundError("product unavailable")
            require_product_owner(actor_id=actor_id, founder_id=product.founder_id)
            require_draft_status(product.status)
            require_expected_version(current=product.version, expected=expected_version)
            require_product_not_reviewed(
                has_decisions=await self.repository.has_review_decisions(
                    session, product_id=product.id
                )
            )
            try:
                await storage.get_product_private(
                    account_id=actor_id,
                    product_id=product.id,
                    object_key=f"product-clean/{actor_id.hex}/{product.id.hex}/{uuid7().hex}",
                )
            except ObjectNotFound:
                # A missing probe key proves the private bucket responded successfully.
                pass
            except ObjectOperationError as error:
                raise ProductInfrastructureError("product storage is unavailable") from error

            now = self.clock()
            assets = await self.repository.get_product_assets(
                session, product_id=product.id, lock=True
            )
            for asset in assets:
                available_at = now
                if asset.expires_at is not None:
                    available_at = max(available_at, asset.expires_at + self.ASSET_CLEANUP_GRACE)
                await self._record_asset_purge(
                    session,
                    product=product,
                    actor_id=actor_id,
                    asset=asset,
                    available_at=available_at,
                )
            await self._record_event(session, product, event_type="product.deleted.v1", now=now)
            await self.repository.delete_product(session, product=product)

    async def save_draft(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        expected_version: int,
        content: ProductContentInput,
        topic_names: list[str] | None = None,
    ) -> ProductDraft:
        """Apply a partial content update only to the current owner's expected draft version."""

        account = await self.member_access.current_account(session, actor_id, lock=True)
        require_active_founder(account)
        async with session.begin_nested():
            product = await self.repository.get_draft(
                session, product_id=product_id, founder_id=actor_id, lock=True
            )
            if product is None:
                raise ProductNotFoundError("product unavailable")
            require_product_owner(actor_id=actor_id, founder_id=product.founder_id)
            require_expected_version(current=product.version, expected=expected_version)
            current = {
                "name": product.name,
                "pitch": product.pitch,
                "description": product.description,
                "website_url": product.website_url,
            }
            current.update(content.model_dump(exclude_unset=True))
            candidate = ProductContentInput.model_validate(current)
            topics_changed = await self._replace_topics(
                session, product_id=product.id, topic_names=topic_names
            )
            if not topics_changed and all(
                getattr(product, field) == getattr(candidate, field) for field in current
            ):
                return _draft_view(product)
            website_key = (
                canonical_website_key(candidate.website_url)
                if candidate.website_url is not None
                else None
            )
            now = self.clock()
            saved = await self.repository.save_draft(
                session,
                product=product,
                content=candidate,
                website_key=website_key,
                now=now,
            )
            await self._record_event(session, saved, event_type="product.saved.v1", now=now)
            return _draft_view(saved)

    async def submit_draft(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        expected_version: int,
    ) -> SubmissionPeriod:
        """Submit one complete current draft, or return its existing period on retry."""

        account = await self.member_access.current_account(session, actor_id, lock=True)
        account = require_active_founder(account)
        if not account.verified:
            raise ProductForbiddenError("verified email is required to submit")
        async with session.begin_nested():
            product = await self.repository.get_owned_product(
                session, product_id=product_id, founder_id=actor_id, lock=True
            )
            if product is None:
                raise ProductNotFoundError("product unavailable")
            require_product_owner(actor_id=actor_id, founder_id=product.founder_id)
            if product.status == "submitted":
                current = await self.repository.get_pending_submission(
                    session, product_id=product.id, lock=True
                )
                if current is not None:
                    return _submission_view(current)
                raise ProductConflictError("product submission is no longer pending")
            if product.status not in {"draft", "changes_requested"}:
                raise ProductConflictError("product is not eligible for submission")
            require_expected_version(current=product.version, expected=expected_version)
            validate_submission_content(_product_content(product))
            missing = await self.repository.submission_gaps(session, product_id=product.id)
            if missing:
                raise ProductValidationError(
                    "submission must include a logo, screenshot, and topic", fields=missing
                )
            if await self.repository.count_pending(session, founder_id=actor_id) >= 3:
                raise ProductQuotaError("pending submission limit reached")
            now = self.clock()
            submitted = await self.repository.set_product_state(
                session, product=product, status="submitted", now=now
            )
            period = await self.repository.create_submission(
                session,
                product_id=product.id,
                product_version=submitted.version,
                submitted_at=now,
            )
            await self._record_event(session, submitted, event_type="product.submitted.v1", now=now)
            return _submission_view(period)

    async def create_asset_intent(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        intent: ProductAssetIntentInput,
        storage: ProductAssetStorage,
    ) -> ProductAssetUpload:
        """Issue and persist a bounded upload only for the active draft owner."""

        account = await self.member_access.current_account(session, actor_id, lock=True)
        require_active_founder(account)
        async with session.begin_nested():
            product = await self.repository.get_owned_product(
                session, product_id=product_id, founder_id=actor_id, lock=True
            )
            if product is None:
                raise ProductNotFoundError("product unavailable")
            require_product_owner(actor_id=actor_id, founder_id=product.founder_id)
            require_editable_status(product.status)
            now = self.clock()
            pending_count = await self.repository.count_pending_assets(
                session, product_id=product.id, now=now
            )
            if pending_count >= self.PENDING_ASSET_LIMIT:
                raise ProductQuotaError("pending asset upload limit reached")
            asset_id = uuid7()
            expires_at = now + timedelta(seconds=self.ASSET_UPLOAD_EXPIRY_SECONDS)
            upload = await storage.create_product_staging_upload(
                account_id=actor_id,
                product_id=product.id,
                asset_id=asset_id,
                content_type=intent.content_type,
                size=intent.size,
                expires_in=self.ASSET_UPLOAD_EXPIRY_SECONDS,
            )
            asset = await self.repository.create_asset(
                session,
                asset_id=asset_id,
                product_id=product.id,
                kind=intent.kind,
                staging_key=upload.object_key,
                media_type=intent.content_type,
                byte_count=intent.size,
                expires_at=expires_at,
            )
            await self._record_asset_purge(
                session,
                product=product,
                actor_id=actor_id,
                asset=asset,
                available_at=expires_at + self.ASSET_CLEANUP_GRACE,
            )
            await self._record_event(
                session, product, event_type="product.asset_changed.v1", now=now
            )
            return ProductAssetUpload(asset=_asset_view(asset), upload=upload)

    async def complete_asset(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        asset_id: UUID,
        storage: ProductAssetStorage,
    ) -> ProductAssetResult:
        """Validate staged bytes and promote them without making them publicly readable."""

        account = await self.member_access.current_account(session, actor_id, lock=True)
        require_active_founder(account)
        async with session.begin_nested():
            product = await self.repository.get_owned_product(
                session, product_id=product_id, founder_id=actor_id, lock=True
            )
            if product is None:
                raise ProductNotFoundError("product unavailable")
            require_product_owner(actor_id=actor_id, founder_id=product.founder_id)
            require_editable_status(product.status)
            asset = await self.repository.get_asset(
                session, product_id=product.id, asset_id=asset_id, lock=True
            )
            if asset is None:
                raise ProductNotFoundError("asset unavailable")
            if asset.state == "clean":
                return _asset_view(asset)
            now = self.clock()
            if asset.state != "pending" or asset.expires_at is None or asset.expires_at <= now:
                raise ProductConflictError("asset upload is no longer pending")
            try:
                clean = await storage.finalize_product_staging(
                    account_id=actor_id,
                    product_id=product.id,
                    asset_id=asset.id,
                    declared_content_type=asset.media_type,
                )
            except (ObjectNotFound, ObjectValidationError):
                failed = await self.repository.mark_asset_failed(session, asset=asset)
                await self._record_event(
                    session, product, event_type="product.asset_changed.v1", now=now
                )
                return _asset_view(failed)
            except ObjectOperationError as error:
                raise ProductInfrastructureError("asset upload could not be completed") from error
            clean_asset = await self.repository.mark_asset_clean(
                session,
                asset=asset,
                clean_key=clean.object_key,
                media_type=clean.media_type,
                byte_count=clean.byte_count,
            )
            await self._record_event(
                session, product, event_type="product.asset_changed.v1", now=now
            )
            return _asset_view(clean_asset)

    async def transfer_asset(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        asset_id: UUID,
        body: bytes,
        content_type: str,
        storage: ProductAssetStorage,
    ) -> None:
        """Recheck product eligibility and pending asset state under the completion locks."""

        account = await self.member_access.current_account(session, actor_id, lock=True)
        require_active_founder(account)
        async with session.begin_nested():
            product = await self.repository.get_owned_product(
                session, product_id=product_id, founder_id=actor_id, lock=True
            )
            if product is None:
                raise ProductNotFoundError("product unavailable")
            require_product_owner(actor_id=actor_id, founder_id=product.founder_id)
            require_editable_status(product.status)
            asset = await self.repository.get_asset(
                session, product_id=product.id, asset_id=asset_id, lock=True
            )
            if asset is None:
                raise ProductNotFoundError("asset unavailable")
            now = self.clock()
            if asset.state != "pending" or asset.expires_at is None or asset.expires_at <= now:
                raise ProductConflictError("asset upload is no longer pending")
            supported_types = {"image/jpeg", "image/png", "image/webp"}
            if (
                not 1 <= asset.byte_count <= 5 * 1024 * 1024
                or asset.media_type not in supported_types
            ):
                raise ProductConflictError("asset intent must be recreated")
            if (
                not body
                or len(body) > asset.byte_count
                or len(body) > 5 * 1024 * 1024
                or content_type != asset.media_type
            ):
                raise ProductValidationError(
                    "asset bytes do not match their declaration", fields=("asset",)
                )
            try:
                await storage.put_staging(
                    object_key=asset.staging_key,
                    body=body,
                    content_type=content_type,
                )
            except ObjectValidationError as error:
                raise ProductValidationError(
                    "asset bytes are invalid", fields=("asset",)
                ) from error
            except ObjectOperationError as error:
                raise ProductInfrastructureError("asset upload could not be stored") from error

    async def attach_assets(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        expected_version: int,
        logo_asset_id: UUID | None,
        screenshot_asset_ids: tuple[UUID, ...],
    ) -> ProductDraft:
        """Attach only clean assets owned by this draft and atomically replace ordering."""

        account = await self.member_access.current_account(session, actor_id, lock=True)
        require_active_founder(account)
        if len(screenshot_asset_ids) > 10 or len(set(screenshot_asset_ids)) != len(
            screenshot_asset_ids
        ):
            raise ProductConflictError("invalid product asset selection")
        selected: dict[UUID, int | None] = {}
        if logo_asset_id is not None:
            selected[logo_asset_id] = None
        for position, asset_id in enumerate(screenshot_asset_ids, start=1):
            if asset_id in selected:
                raise ProductConflictError("an asset cannot fill multiple positions")
            selected[asset_id] = position
        async with session.begin_nested():
            product = await self.repository.get_owned_product(
                session, product_id=product_id, founder_id=actor_id, lock=True
            )
            if product is None:
                raise ProductNotFoundError("product unavailable")
            require_product_owner(actor_id=actor_id, founder_id=product.founder_id)
            require_editable_status(product.status)
            require_expected_version(current=product.version, expected=expected_version)
            assets = await self.repository.get_assets(
                session, product_id=product.id, asset_ids=set(selected)
            )
            if len(assets) != len(selected):
                raise ProductNotFoundError("asset unavailable")
            by_id = {asset.id: asset for asset in assets}
            for selected_asset_id, selected_position in selected.items():
                asset = by_id[selected_asset_id]
                expected_kind = "logo" if selected_position is None else "screenshot"
                if asset.state != "clean" or asset.kind != expected_kind:
                    raise ProductConflictError("only clean matching assets can be attached")
            now = self.clock()
            detached = await self.repository.replace_asset_attachments(
                session,
                product_id=product.id,
                selected_positions=selected,
                now=now,
            )
            for asset in detached:
                await self._record_asset_purge(
                    session,
                    product=product,
                    actor_id=actor_id,
                    asset=asset,
                    available_at=now + self.ASSET_CLEANUP_GRACE,
                )
            saved = await self.repository.set_product_state(
                session, product=product, status=product.status, now=now
            )
            await self._record_event(session, saved, event_type="product.asset_changed.v1", now=now)
            return _draft_view(saved)

    async def _record_asset_purge(
        self,
        session: AsyncSession,
        *,
        product: Product,
        actor_id: UUID,
        asset: ProductAsset,
        available_at: datetime,
    ) -> None:
        """Persist delayed cleanup for abandoned or DB-orphaned upload objects."""

        clean_key = asset.staging_key.replace("product-staging/", "product-clean/", 1)
        try:
            key_id, encrypted_payload = self.payload_codec.encode(
                {
                    "account_id": actor_id,
                    "product_id": product.id,
                    "asset_id": asset.id,
                    "staging_key": asset.staging_key,
                    "clean_key": clean_key,
                }
            )
            await self.outbox_repository.add(
                session,
                OutboxEvent(
                    event_type="product.media_purge.v1",
                    aggregate_id=product.id,
                    key_id=key_id,
                    encrypted_payload=encrypted_payload,
                    available_at=available_at,
                ),
            )
        except Exception as exc:
            raise ProductInfrastructureError("asset cleanup could not be scheduled") from exc

    async def handle_outbox_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
        storage: ProductEventStorage | None = None,
    ) -> None:
        """Acknowledge known product state events and execute safe private media purges."""

        if event_type in self.PRODUCT_STATE_EVENTS:
            return
        if event_type != "product.media_purge.v1":
            raise PermanentEventError("product event type is not supported")
        try:
            account_id = UUID(_required_event_string(payload, "account_id"))
            product_id = UUID(_required_event_string(payload, "product_id"))
            asset_id = UUID(_required_event_string(payload, "asset_id"))
            staging_key = _required_event_string(payload, "staging_key")
            clean_key = _required_event_string(payload, "clean_key")
        except ValueError as error:
            raise PermanentEventError("product media purge payload is invalid") from error
        if product_id != aggregate_id:
            raise PermanentEventError("product media purge aggregate does not match payload")
        object_suffix = f"{account_id.hex}/{product_id.hex}/{asset_id.hex}"
        if staging_key != f"product-staging/{object_suffix}" or clean_key != (
            f"product-clean/{object_suffix}"
        ):
            raise PermanentEventError("product media purge key is outside its asset scope")
        event_storage = storage or self.event_storage
        if event_storage is None:
            raise ProductInfrastructureError("product media storage is unavailable")

        product = await self.repository.get_owned_product(
            session, product_id=product_id, founder_id=account_id, lock=True
        )
        asset = (
            await self.repository.get_asset(
                session, product_id=product_id, asset_id=asset_id, lock=True
            )
            if product is not None
            else None
        )
        keep_clean_object = bool(
            asset is not None
            and asset.state == "clean"
            and asset.attached_at is not None
            and asset.clean_key == clean_key
        )
        if asset is not None and not keep_clean_object and asset.state in {"pending", "clean"}:
            await self.repository.mark_asset_failed(session, asset=asset)
        await event_storage.delete_product_private(
            account_id=account_id, product_id=product_id, object_key=staging_key
        )
        if not keep_clean_object:
            await event_storage.delete_product_private(
                account_id=account_id, product_id=product_id, object_key=clean_key
            )

    async def save_pending(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        expected_version: int,
        content: ProductContentInput,
        topic_names: list[str] | None = None,
    ) -> SubmittedProduct:
        """Save only complete edits to an open period without changing its queue time."""

        account = await self.member_access.current_account(session, actor_id, lock=True)
        require_active_founder(account)
        async with session.begin_nested():
            product = await self.repository.get_owned_product(
                session, product_id=product_id, founder_id=actor_id, lock=True
            )
            if product is None:
                raise ProductNotFoundError("product unavailable")
            if product.status != "submitted":
                raise ProductConflictError("product is no longer pending")
            require_expected_version(current=product.version, expected=expected_version)
            period = await self.repository.get_pending_submission(
                session, product_id=product_id, lock=True
            )
            if period is None:
                raise ProductConflictError("product is no longer pending")
            candidate_values = {
                "name": product.name,
                "pitch": product.pitch,
                "description": product.description,
                "website_url": product.website_url,
            }
            candidate_values.update(content.model_dump(exclude_unset=True))
            candidate = ProductContentInput.model_validate(candidate_values)
            validate_submission_content(candidate)
            if topic_names is not None and not topic_names:
                raise ProductValidationError(
                    "a pending product needs at least one topic", fields=("topics",)
                )
            await self._replace_topics(session, product_id=product.id, topic_names=topic_names)
            missing = await self.repository.submission_gaps(session, product_id=product.id)
            if missing:
                raise ProductValidationError(
                    "submission must include a logo, screenshot, and topic", fields=missing
                )
            website_key = canonical_website_key(candidate.website_url or "")
            now = self.clock()
            saved = await self.repository.set_product_state(
                session,
                product=product,
                status="submitted",
                now=now,
                content=candidate,
                website_key=website_key,
            )
            await self.repository.update_submission_version(
                session, submission=period, product_version=saved.version
            )
            await self._record_event(session, saved, event_type="product.saved.v1", now=now)
            return _submitted_view(saved)

    async def _replace_topics(
        self, session: AsyncSession, *, product_id: UUID, topic_names: list[str] | None
    ) -> bool:
        """Resolve a supplied selection without exposing another founder's proposal."""

        if topic_names is None:
            return False
        labels = validate_topic_names(topic_names) if topic_names else []
        from app.modules.products.repository import TopicRepository

        topics = TopicRepository()
        selections = [
            await topics.get_or_create_topic(session, label.display_name) for label in labels
        ]
        return await self.repository.replace_product_topics(
            session, product_id=product_id, selections=selections
        )

    async def withdraw_submission(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        submission_id: UUID,
        expected_version: int,
    ) -> ProductDraft:
        """Explicitly return an owned pending product to private draft, even if suspended."""

        account = await self.member_access.current_account(session, actor_id, lock=True)
        if account is None:
            raise ProductForbiddenError("product access is forbidden")
        async with session.begin_nested():
            product = await self.repository.get_owned_product(
                session, product_id=product_id, founder_id=actor_id, lock=True
            )
            if product is None:
                raise ProductNotFoundError("product unavailable")
            if product.status != "submitted":
                raise ProductConflictError("product is no longer pending")
            require_expected_version(current=product.version, expected=expected_version)
            period = await self.repository.get_pending_submission(
                session, product_id=product_id, lock=True
            )
            if period is None or period.id != submission_id:
                raise ProductConflictError("submission period has changed")
            now = self.clock()
            draft = await self.repository.set_product_state(
                session, product=product, status="draft", now=now
            )
            await self.repository.close_submission(session, submission=period, closed_at=now)
            await self._record_event(session, draft, event_type="product.withdrawn.v1", now=now)
            return _draft_view(draft)

    async def _record_event(
        self,
        session: AsyncSession,
        product: Product,
        *,
        event_type: str,
        now: datetime,
    ) -> None:
        try:
            key_id, encrypted_payload = self.payload_codec.encode(
                {"product_id": product.id, "version": product.version}
            )
            await self.outbox_repository.add(
                session,
                OutboxEvent(
                    event_type=event_type,
                    aggregate_id=product.id,
                    key_id=key_id,
                    encrypted_payload=encrypted_payload,
                    available_at=now,
                ),
            )
        except Exception as exc:
            raise ProductInfrastructureError("product update could not be completed") from exc


def _draft_view(product: Product) -> ProductDraft:
    return ProductDraft(
        id=product.id,
        founder_id=product.founder_id,
        status=product.status,
        version=product.version,
        content=ProductContentInput(
            name=product.name,
            pitch=product.pitch,
            description=product.description,
            website_url=product.website_url,
        ),
        website_key=product.website_key,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def _review_request_fingerprint(
    *,
    product_id: UUID,
    submission_id: UUID,
    expected_version: int,
    outcome: str,
    feedback: str | None,
) -> str:
    """Hash normalized command fields so key replay cannot change its meaning."""

    payload = json.dumps(
        {
            "product_id": str(product_id),
            "submission_id": str(submission_id),
            "expected_version": expected_version,
            "outcome": outcome,
            "feedback": feedback,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _asset_view(asset: ProductAsset) -> ProductAssetResult:
    return ProductAssetResult(
        id=asset.id,
        kind=cast(Literal["logo", "screenshot"], asset.kind),
        state=asset.state,
        media_type=cast(Literal["image/jpeg", "image/png", "image/webp"], asset.media_type),
        byte_count=asset.byte_count,
    )


def _required_event_string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError("product event payload is invalid")
    return value


def _product_content(product: Product) -> ProductContentInput:
    return ProductContentInput(
        name=product.name,
        pitch=product.pitch,
        description=product.description,
        website_url=product.website_url,
    )


def _submitted_view(product: Product) -> SubmittedProduct:
    return SubmittedProduct(
        id=product.id,
        founder_id=product.founder_id,
        status=product.status,
        version=product.version,
        content=_product_content(product),
        website_key=product.website_key,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def _submission_view(submission: ProductSubmission) -> SubmissionPeriod:
    return SubmissionPeriod(
        id=submission.id,
        product_id=submission.product_id,
        submitted_at=submission.submitted_at,
        product_version=submission.product_version,
    )


def _queue_cursor(submission: ProductSubmission) -> str:
    return _read_cursor(submission.submitted_at, submission.id)


def _read_cursor(timestamp: datetime, item_id: UUID) -> str:
    return f"{timestamp.isoformat()}|{item_id}"


def _parse_read_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        timestamp_text, submission_text = value.split("|", maxsplit=1)
        timestamp = datetime.fromisoformat(timestamp_text)
        submission_id = UUID(submission_text)
        if timestamp.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as error:
        raise ProductValidationError("invalid cursor", fields=("after",)) from error
    return timestamp, submission_id


def validate_submission_content(content: ProductContentInput) -> ProductContentInput:
    """Require all text and website fields before a draft can be submitted."""

    missing = tuple(
        field
        for field in ("name", "pitch", "description", "website_url")
        if getattr(content, field) is None
    )
    if missing:
        raise ProductValidationError("submission content is incomplete", fields=missing)
    return content


def validate_topic_names(names: list[str]) -> list[TopicLabel]:
    """Trim, bound, and de-duplicate founder topic choices without leaking canonical casing."""

    if not 1 <= len(names) <= 3:
        raise ProductValidationError("choose between one and three topics", fields=("topics",))
    labels: list[TopicLabel] = []
    seen: set[str] = set()
    for name in names:
        display_name = name.strip()
        name_key = display_name.casefold()
        if not display_name or len(display_name) > 40:
            raise ProductValidationError(
                "topic must contain 1 to 40 characters", fields=("topics",)
            )
        if name_key in seen:
            raise ProductValidationError("topic choices must be unique", fields=("topics",))
        seen.add(name_key)
        labels.append(TopicLabel(display_name=display_name, name_key=name_key))
    return labels


def canonical_website_key(value: str) -> str:
    """Normalize only URL components that do not identify a different website link."""

    try:
        content = ProductContentInput(website_url=value)
    except ValidationError as exc:
        raise ProductValidationError(
            "website_url must be a valid HTTPS URL", fields=("website_url",)
        ) from exc
    if content.website_url is None:
        raise ProductValidationError(
            "website_url must be a valid HTTPS URL", fields=("website_url",)
        )
    try:
        parsed = urlsplit(content.website_url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ProductValidationError(
            "website_url must be a valid HTTPS URL", fields=("website_url",)
        ) from exc
    if (
        parsed.scheme.casefold() != "https"
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in value)
    ):
        raise ProductValidationError(
            "website_url must be a valid HTTPS URL", fields=("website_url",)
        )
    normalized_port = f":{port}" if port is not None and port != 443 else ""
    normalized_host = f"[{host.casefold()}]" if ":" in host else host.casefold()
    netloc = normalized_host + normalized_port
    path = "" if parsed.path in ("", "/") else parsed.path
    return _replace_url(parsed, netloc=netloc, path=path, query=parsed.query, fragment="").geturl()


def canonical_topic_key(value: str) -> str:
    """Return the trimmed, case-folded key used for equivalent topic names."""

    return value.strip().casefold()


def _replace_url(
    parsed: SplitResult, *, netloc: str, path: str, query: str, fragment: str
) -> SplitResult:
    return parsed._replace(netloc=netloc, path=path, query=query, fragment=fragment)


def _product_media_path(product_id: UUID, asset_id: UUID) -> str:
    return f"/api/v1/products/{product_id}/assets/{asset_id}"
