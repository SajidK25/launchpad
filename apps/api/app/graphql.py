"""One bounded, read-only GraphQL endpoint for profiles and private products."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

import strawberry
from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute
from graphql import GraphQLError, OperationType, parse
from graphql.language.ast import FieldNode, OperationDefinitionNode, SelectionSetNode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from strawberry.fastapi import GraphQLRouter
from strawberry.http import GraphQLHTTPResponse
from strawberry.types.execution import ExecutionResult

from app.modules.auth.sessions import MemberContext, SessionService, UnauthenticatedError
from app.modules.auth.staff import AuthAccessService
from app.modules.launches.graphql import LaunchQuery
from app.modules.launches.service import LaunchBookingService
from app.modules.notifications.graphql import LaunchPreferenceQuery, NotificationQuery
from app.modules.notifications.service import NotificationService
from app.modules.products.graphql import ProductQuery, PublicProductQuery
from app.modules.products.policies import ProductForbiddenError, ProductNotFoundError
from app.modules.products.service import ProductService, ProductValidationError
from app.modules.users.graphql import ProfileQuery
from app.modules.users.service import ProfileService
from app.modules.votes.graphql import VoteQuery
from app.modules.votes.policies import VoteForbiddenError, VoteReadValidationError
from app.modules.votes.repository import VoteRepository
from app.modules.votes.service import (
    RankingRedis,
    VoteRankingProductAccess,
    VoteRankingProjectionService,
    VoteReadService,
)
from app.shared.config.settings import Settings
from app.shared.email.codec import EmailPayloadCodec

_ALLOWED_ROOT_FIELDS = frozenset(
    {
        "viewerProfile",
        "publicProfile",
        "viewerProducts",
        "viewerProduct",
        "reviewQueue",
        "reviewProduct",
        "approvedReviews",
        "topicChoices",
        "viewerNotificationInbox",
        "viewerLaunchBookings",
        "viewerLaunchNotificationPreferences",
        "publicProduct",
        "publicLaunches",
        "publicProductCatalog",
        "publicCatalogTopics",
        "dailyProductRanking",
        "pendingVoteReviews",
    }
)
_MAX_QUERY_LENGTH = 8192
_MAX_REQUEST_BYTES = 16384
_MAX_QUERY_DEPTH = 6
_MAX_QUERY_FIELDS = 60


@strawberry.type
class Query(
    ProfileQuery,
    ProductQuery,
    PublicProductQuery,
    NotificationQuery,
    LaunchQuery,
    LaunchPreferenceQuery,
    VoteQuery,
):
    """The application's single read root; no mutation or subscription exists."""


@strawberry.type
class ProductsWithoutLaunchesQuery(ProfileQuery, ProductQuery, NotificationQuery):
    """Composed product read root for environments before launch rollout."""


@strawberry.type
class LaunchesWithoutProductsQuery(
    ProfileQuery,
    PublicProductQuery,
    NotificationQuery,
    LaunchQuery,
    LaunchPreferenceQuery,
    VoteQuery,
):
    """Composed launch read root without private product reads."""


@strawberry.type
class ProfileOnlyQuery(ProfileQuery, NotificationQuery):
    """Read root used while the products feature is disabled."""


class PrivateReadRouter(GraphQLRouter):
    """Ensure execution errors never echo private database or storage values."""

    async def process_result(
        self, request: Request, result: ExecutionResult
    ) -> GraphQLHTTPResponse:
        response = await super().process_result(request, result)
        encoded_errors = cast(list[dict[str, Any]], response.get("errors") or [])
        for encoded, error in zip(encoded_errors, result.errors or [], strict=True):
            if isinstance(error.original_error, PermissionError):
                encoded["message"] = "authentication required"
            elif isinstance(error.original_error, ProductForbiddenError):
                encoded["message"] = "product access is forbidden"
            elif isinstance(error.original_error, ProductNotFoundError):
                encoded["message"] = "product unavailable"
            elif isinstance(error.original_error, ProductValidationError):
                encoded["message"] = "invalid product query"
            elif isinstance(error.original_error, VoteForbiddenError):
                encoded["message"] = "vote review access is forbidden"
            elif isinstance(error.original_error, VoteReadValidationError):
                encoded["message"] = "invalid vote query"
            else:
                encoded["message"] = "request could not be completed"
        return response


def build_router(
    context_getter: Callable[..., Any],
    *,
    include_products: bool = True,
    include_launches: bool | None = None,
) -> GraphQLRouter:
    launch_reads_enabled = include_products if include_launches is None else include_launches
    query_type = (
        Query
        if include_products and launch_reads_enabled
        else ProductsWithoutLaunchesQuery
        if include_products
        else LaunchesWithoutProductsQuery
        if launch_reads_enabled
        else ProfileOnlyQuery
    )
    router = PrivateReadRouter(
        strawberry.Schema(query=query_type),
        path="/graphql",
        context_getter=context_getter,
        allow_queries_via_get=False,
        graphql_ide=None,
    )
    router.routes[:] = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.methods == {"POST"}
    ]
    return router


def context_getter(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    session_service: SessionService,
    profile_service_factory: Callable[[MemberContext | None], ProfileService],
    payload_codec: EmailPayloadCodec,
    ranking_redis: RankingRedis | None = None,
) -> Callable[..., Any]:
    """Validate the request before resolving a fresh session-bound read context."""

    async def context(request: Request, response: Response) -> dict[str, Any]:
        if request.method != "POST":
            raise HTTPException(status_code=405, detail="POST required")
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > _MAX_REQUEST_BYTES:
                    raise HTTPException(status_code=400, detail="query is not allowed")
            except ValueError as error:
                raise HTTPException(status_code=400, detail="query is not allowed") from error
        body = await request.body()
        if len(body) > _MAX_REQUEST_BYTES:
            raise HTTPException(status_code=400, detail="query is not allowed")
        try:
            payload = json.loads(body)
            query = payload.get("query") if isinstance(payload, dict) else None
            if not isinstance(query, str):
                raise ValueError("query is required")
            validate_read_query(query)
        except (GraphQLError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=400, detail="query is not allowed") from error
        secret = request.cookies.get(settings.session_cookie_name)
        async with session_factory() as session:
            member: MemberContext | None = None
            if secret:
                try:
                    member = await session_service.resolve(session, session_secret=secret)
                except UnauthenticatedError:
                    secret = None
        response.headers["Cache-Control"] = "no-store"
        request_id = uuid4().hex
        response.headers["X-Request-ID"] = request_id

        def product_service_factory() -> ProductService:
            return ProductService(member_access=AuthAccessService(), payload_codec=payload_codec)

        def launch_booking_service_factory() -> LaunchBookingService:
            return LaunchBookingService(
                member_access=AuthAccessService(),
                product_access=product_service_factory(),
                payload_codec=payload_codec,
            )

        def vote_read_service_factory() -> VoteReadService:
            products = cast(VoteRankingProductAccess, product_service_factory())
            repository = VoteRepository(
                score_half_life_seconds=settings.vote_score_half_life_seconds
            )
            projection = (
                VoteRankingProjectionService(
                    products=products,
                    repository=repository,
                    redis=ranking_redis,
                )
                if ranking_redis is not None
                else None
            )
            return VoteReadService(
                products=products,
                repository=repository,
                projection=projection,
            )

        return {
            "member": member,
            "request_id": request_id,
            "session_secret": secret,
            "session_factory": session_factory,
            "service_factory": profile_service_factory,
            "product_service_factory": product_service_factory,
            "launch_booking_service_factory": launch_booking_service_factory,
            "vote_read_service_factory": vote_read_service_factory,
            "notification_service_factory": lambda: NotificationService(
                member_access=AuthAccessService(), payload_codec=payload_codec
            ),
        }

    return context


def validate_read_query(query: str) -> None:
    """Reject unsafe or unbounded documents before GraphQL execution."""

    if not query or len(query) > _MAX_QUERY_LENGTH:
        raise ValueError("query size exceeds limit")
    document = parse(query)
    operations = [d for d in document.definitions if isinstance(d, OperationDefinitionNode)]
    if len(operations) != 1 or len(operations) != len(document.definitions):
        raise ValueError("one operation without fragments is required")
    operation = operations[0]
    if operation.operation is not OperationType.QUERY or operation.directives:
        raise ValueError("only query operations are allowed")
    count = [0]
    _validate_selection_set(operation.selection_set, depth=1, root=True, count=count)


def _validate_selection_set(
    selection_set: SelectionSetNode, *, depth: int, root: bool = False, count: list[int]
) -> None:
    if depth > _MAX_QUERY_DEPTH:
        raise ValueError("query depth exceeds limit")
    seen_root_fields: set[str] = set()
    for field in selection_set.selections:
        if not isinstance(field, FieldNode) or field.alias is not None or field.directives:
            raise ValueError("only direct fields are allowed")
        count[0] += 1
        if count[0] > _MAX_QUERY_FIELDS:
            raise ValueError("query field count exceeds limit")
        name = field.name.value
        if name.startswith("__") or (root and name not in _ALLOWED_ROOT_FIELDS):
            raise ValueError("query field is not allowed")
        if root and name in seen_root_fields:
            raise ValueError("duplicate root fields are not allowed")
        seen_root_fields.add(name)
        if field.selection_set is not None:
            _validate_selection_set(field.selection_set, depth=depth + 1, count=count)
