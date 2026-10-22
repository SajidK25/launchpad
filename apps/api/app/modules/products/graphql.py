"""Private product fields for the composed read-only GraphQL schema."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date as Date
from datetime import datetime
from typing import cast
from uuid import UUID

import strawberry
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.sessions import MemberContext
from app.modules.auth.staff import AccountState
from app.modules.products.policies import (
    ProductForbiddenError,
    ProductNotFoundError,
    require_staff_reviewer,
)
from app.modules.products.service import ApprovedReviewPage as ApprovedReviewResultPage
from app.modules.products.service import (
    OwnerProductDetail,
    OwnerReviewOutcome,
    ProductAssetResult,
    ProductDraft,
    ProductService,
    ProductValidationError,
    PublicProductProjection,
    StaffProductDetail,
    SubmissionPeriod,
)
from app.modules.products.service import PublicLaunchPage as PublicLaunchResultPage


@strawberry.type
class ProductSummary:
    id: UUID
    status: str
    version: int
    name: str | None
    pitch: str | None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class ProductPage:
    items: list[ProductSummary]
    next_cursor: str | None


@strawberry.type
class ProductTopic:
    id: UUID
    display_name: str
    position: int


@strawberry.type
class TopicChoice:
    id: UUID
    display_name: str


@strawberry.type
class ProductAsset:
    id: UUID
    kind: str
    media_type: str
    byte_count: int
    url: str


@strawberry.type
class Submission:
    id: UUID
    submitted_at: datetime
    product_version: int


@strawberry.type
class ProductDetail:
    summary: ProductSummary
    description: str | None
    website_url: str | None
    topics: list[ProductTopic]
    assets: list[ProductAsset]
    submission: Submission | None
    review_outcome: ReviewOutcome | None


@strawberry.type
class ReviewEntry:
    product: ProductSummary
    submission: Submission
    possible_duplicate: bool
    founder_suspended: bool


@strawberry.type
class ReviewPage:
    items: list[ReviewEntry]
    next_cursor: str | None


@strawberry.type
class ReviewDetail:
    product: ProductDetail
    submission: Submission
    possible_duplicate: bool
    founder_suspended: bool


@strawberry.type
class ReviewOutcome:
    """Founder-visible result only; excludes reviewer identity and request metadata."""

    status: str
    feedback: str | None


@strawberry.type
class ApprovedReviewEntry:
    product: ProductSummary
    submission: Submission
    approved_at: datetime


@strawberry.type
class ApprovedReviewPage:
    items: list[ApprovedReviewEntry]
    next_cursor: str | None


@strawberry.type
class PublicProductAsset:
    id: UUID
    kind: str
    media_type: str
    byte_count: int
    url: str


@strawberry.type
class PublicProduct:
    id: UUID
    name: str
    pitch: str
    description: str
    website_url: str
    launched_at: datetime
    logo: PublicProductAsset | None
    screenshots: list[PublicProductAsset]
    topics: list[str]


@strawberry.type
class PublicLaunchCard:
    id: UUID
    name: str
    pitch: str
    logo_url: str | None
    topics: list[str]


@strawberry.type
class PublicLaunchPage:
    today_date: Date
    selected_date: Date
    items: list[PublicLaunchCard]
    next_cursor: str | None


def _member(info: strawberry.Info) -> MemberContext:
    member: MemberContext | None = info.context.get("member")
    if member is None:
        raise PermissionError("authentication required")
    return member


def _staff(info: strawberry.Info) -> MemberContext:
    member = _member(info)
    require_staff_reviewer(
        AccountState(
            account_id=member.account_id,
            verified=member.verified,
            role=member.role,
            suspended_at=member.suspended_at,
        )
    )
    return member


def _service(info: strawberry.Info) -> ProductService:
    return cast(ProductService, info.context["product_service_factory"]())


@asynccontextmanager
async def _safe_read() -> AsyncIterator[None]:
    """Keep private exception values out of GraphQL responses and server logs."""

    try:
        yield
    except (PermissionError, ProductForbiddenError, ProductNotFoundError, ProductValidationError):
        raise
    except Exception:
        raise RuntimeError("request could not be completed") from None


def _summary(product: ProductDraft) -> ProductSummary:
    return ProductSummary(
        id=product.id,
        status=product.status,
        version=product.version,
        name=product.content.name,
        pitch=product.content.pitch,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def _submission(period: SubmissionPeriod) -> Submission:
    return Submission(
        id=period.id,
        submitted_at=period.submitted_at,
        product_version=period.product_version,
    )


async def _detail(
    info: strawberry.Info,
    *,
    service: ProductService,
    member: MemberContext,
    result: OwnerProductDetail,
    session: AsyncSession,
) -> ProductDetail:
    # The read service selects only validated private attachments. Each URL is
    # independently session-bound and rechecked when downloaded.
    assets = [
        ProductAsset(
            id=asset.id,
            kind=asset.kind,
            media_type=asset.media_type,
            byte_count=asset.byte_count,
            url=await service.sign_private_asset_url(
                session,
                actor_id=member.account_id,
                session_secret=info.context["session_secret"],
                product_id=result.product.id,
                asset_id=asset.id,
            ),
        )
        for asset in result.assets
    ]
    return ProductDetail(
        summary=_summary(result.product),
        description=result.product.content.description,
        website_url=result.product.content.website_url,
        topics=[
            ProductTopic(
                id=topic.topic_id, display_name=topic.display_name, position=topic.position
            )
            for topic in result.topics
        ],
        assets=assets,
        submission=_submission(result.submission) if result.submission is not None else None,
        review_outcome=(
            _review_outcome(result.review_outcome) if result.review_outcome is not None else None
        ),
    )


def _review_outcome(result: OwnerReviewOutcome) -> ReviewOutcome:
    return ReviewOutcome(
        status=result.status,
        feedback=result.feedback,
    )


@strawberry.type
class PublicProductQuery:
    """Anonymous launched-only public projection owned by products."""

    @strawberry.field
    async def public_product(self, info: strawberry.Info, id: UUID) -> PublicProduct | None:
        """Read the explicit public projection only after persisted publication."""

        async with _safe_read():
            async with info.context["session_factory"]() as session:
                result: PublicProductProjection | None = await _service(info).public_projection(
                    cast(AsyncSession, session), product_id=id
                )
            if result is None:
                return None

            def asset(item: ProductAssetResult | None) -> PublicProductAsset | None:
                if item is None:
                    return None
                return PublicProductAsset(
                    id=item.id,
                    kind=item.kind,
                    media_type=item.media_type,
                    byte_count=item.byte_count,
                    url=f"/api/v1/products/{result.id}/assets/{item.id}/public",
                )

            return PublicProduct(
                id=result.id,
                name=result.name,
                pitch=result.pitch,
                description=result.description,
                website_url=result.website_url,
                launched_at=result.launched_at,
                logo=asset(result.logo),
                screenshots=[cast(PublicProductAsset, asset(item)) for item in result.screenshots],
                topics=list(result.topics),
            )

    @strawberry.field
    async def public_launches(
        self,
        info: strawberry.Info,
        date: Date | None = None,
        first: int = 20,
        after: str | None = None,
    ) -> PublicLaunchPage:
        """Read one anonymous, launched-only date page."""

        async with _safe_read():
            async with info.context["session_factory"]() as session:
                page: PublicLaunchResultPage = await _service(info).public_launches(
                    cast(AsyncSession, session),
                    requested_date=date,
                    first=first,
                    after=after,
                )
            return PublicLaunchPage(
                today_date=page.today_date,
                selected_date=page.selected_date,
                items=[
                    PublicLaunchCard(
                        id=item.id,
                        name=item.name,
                        pitch=item.pitch,
                        logo_url=(
                            f"/api/v1/products/{item.id}/assets/{item.logo.id}/public"
                            if item.logo is not None
                            else None
                        ),
                        topics=list(item.topics),
                    )
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )


@strawberry.type
class ProductQuery:
    """Owner and staff read fields; services recheck live policy in each transaction."""

    @strawberry.field
    async def viewer_products(
        self, info: strawberry.Info, first: int = 20, after: str | None = None
    ) -> ProductPage:
        async with _safe_read():
            member = _member(info)
            async with info.context["session_factory"]() as session:
                page = await _service(info).owner_list(
                    session, actor_id=member.account_id, first=first, after=after
                )
            return ProductPage(
                items=[_summary(item) for item in page.items], next_cursor=page.next_cursor
            )

    @strawberry.field
    async def viewer_product(self, info: strawberry.Info, id: UUID) -> ProductDetail | None:
        async with _safe_read():
            member = _member(info)
            async with info.context["session_factory"]() as session:
                service = _service(info)
                try:
                    result = await service.owner_detail(
                        session, actor_id=member.account_id, product_id=id
                    )
                except ProductNotFoundError:
                    return None
                return await _detail(
                    info, service=service, member=member, result=result, session=session
                )

    @strawberry.field
    async def review_queue(
        self, info: strawberry.Info, first: int = 20, after: str | None = None
    ) -> ReviewPage:
        async with _safe_read():
            member = _staff(info)
            async with info.context["session_factory"]() as session:
                page = await _service(info).staff_queue(
                    session, actor_id=member.account_id, first=first, after=after
                )
            return ReviewPage(
                items=[
                    ReviewEntry(
                        product=_summary(item.product),
                        submission=_submission(item.submission),
                        possible_duplicate=item.possible_duplicate,
                        founder_suspended=item.founder_suspended,
                    )
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )

    @strawberry.field
    async def review_product(self, info: strawberry.Info, id: UUID) -> ReviewDetail | None:
        async with _safe_read():
            member = _staff(info)
            async with info.context["session_factory"]() as session:
                service = _service(info)
                try:
                    result: StaffProductDetail = await service.staff_detail(
                        session, actor_id=member.account_id, product_id=id
                    )
                except ProductNotFoundError:
                    return None
                product = await _detail(
                    info, service=service, member=member, result=result.product, session=session
                )
            return ReviewDetail(
                product=product,
                submission=_submission(result.submission),
                possible_duplicate=result.possible_duplicate,
                founder_suspended=result.founder_suspended,
            )

    @strawberry.field
    async def approved_reviews(
        self, info: strawberry.Info, first: int = 20, after: str | None = None
    ) -> ApprovedReviewPage:
        async with _safe_read():
            member = _staff(info)
            async with info.context["session_factory"]() as session:
                page: ApprovedReviewResultPage = await _service(info).approved_review_page(
                    session, actor_id=member.account_id, first=first, after=after
                )
            return ApprovedReviewPage(
                items=[
                    ApprovedReviewEntry(
                        product=_summary(item.product),
                        submission=_submission(item.submission),
                        approved_at=item.approved_at,
                    )
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )

    @strawberry.field
    async def topic_choices(
        self, info: strawberry.Info, first: int = 20, query: str | None = None
    ) -> list[TopicChoice]:
        async with _safe_read():
            member: MemberContext | None = info.context.get("member")
            async with info.context["session_factory"]() as session:
                choices = await _service(info).topic_choices(
                    session,
                    actor_id=member.account_id if member is not None else None,
                    query=query,
                    first=first,
                )
            return [
                TopicChoice(id=choice.topic_id, display_name=choice.display_name)
                for choice in choices
            ]
