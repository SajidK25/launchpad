"""Product content rules that are independent of transport and persistence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from urllib.parse import SplitResult, urlsplit
from uuid import UUID

from app.modules.auth.staff import AccountState
from app.modules.products.models import Product, ProductSubmission
from app.modules.products.policies import (
    ProductConflictError,
    ProductForbiddenError,
    ProductInfrastructureError,
    ProductNotFoundError,
    ProductQuotaError,
    require_active_founder,
    require_expected_version,
    require_product_owner,
)
from app.modules.products.schemas import ProductContentInput
from app.shared.events.outbox import OutboxEvent, OutboxRepository
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.modules.products.repository import ProductRepository


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


class ProductPayloadCodec(Protocol):
    """Encrypt minimal product event payloads before outbox persistence."""

    def encode(self, payload: Mapping[str, object]) -> tuple[str, bytes]: ...


class ProductEvents(Protocol):
    """Transactional outbox interface used by the products feature."""

    async def add(self, session: AsyncSession, event: OutboxEvent) -> UUID: ...


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


class ProductService:
    """Create, load, and version private drafts under live account authorization."""

    DRAFT_LIMIT = 10

    def __init__(
        self,
        *,
        member_access: ProductMemberAccess,
        outbox_repository: ProductEvents | None = None,
        payload_codec: ProductPayloadCodec,
        repository: ProductRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if repository is None:
            from app.modules.products.repository import ProductRepository

            repository = ProductRepository()
        self.repository = repository
        self.member_access = member_access
        self.outbox_repository = outbox_repository or OutboxRepository()
        self.payload_codec = payload_codec
        self.clock = clock or (lambda: datetime.now(UTC))

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

    async def save_draft(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        expected_version: int,
        content: ProductContentInput,
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
            if all(getattr(product, field) == getattr(candidate, field) for field in current):
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

    async def save_pending(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        expected_version: int,
        content: ProductContentInput,
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
