"""Read-only Strawberry profile composition."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import strawberry
from graphql import OperationType, parse
from graphql.language.ast import OperationDefinitionNode
from strawberry.fastapi import GraphQLRouter

from app.modules.users.service import ProfileResult, ProfileService

_ALLOWED_ROOT_FIELDS = frozenset({"viewerProfile", "publicProfile"})
_MAX_QUERY_DEPTH = 4


@strawberry.type
class PublicProfile:
    account_id: UUID
    display_name: str
    bio: str
    links: list[str]
    photo_url: str | None


@strawberry.type
class ViewerProfile(PublicProfile):
    visibility: str
    version: int


def build_router(context_getter: Any) -> GraphQLRouter:
    @strawberry.type
    class Query:
        @strawberry.field
        async def viewer_profile(self, info: strawberry.Info) -> ViewerProfile:
            context = info.context
            member = context.get("member")
            if member is None:
                raise PermissionError("authentication required")
            async with context["session_factory"]() as session:
                service = context["service_factory"](member)
                result = await service.get_owner(
                    session, actor_id=member.account_id, account_id=member.account_id
                )
            return _viewer(result)

        @strawberry.field
        async def public_profile(
            self, info: strawberry.Info, account_id: UUID
        ) -> PublicProfile | None:
            context = info.context
            async with context["session_factory"]() as session:
                service: ProfileService = context["service_factory"](context.get("member"))
                result = await service.get_public(session, account_id=account_id)
            return _public(result)

    schema = strawberry.Schema(query=Query)
    return GraphQLRouter(
        schema,
        path="/graphql",
        context_getter=context_getter,
        allow_queries_via_get=False,
        graphql_ide=None,
    )


def validate_read_query(query: str) -> None:
    """Allow only one bounded read operation exposed by this schema."""

    document = parse(query)
    operations = [d for d in document.definitions if isinstance(d, OperationDefinitionNode)]
    if len(operations) != 1 or len(operations) != len(document.definitions):
        raise ValueError("one operation without fragments is required")
    operation = operations[0]
    if operation.operation is not OperationType.QUERY:
        raise ValueError("only query operations are allowed")
    _validate_selection_set(operation.selection_set, depth=1, root=True)


def _validate_selection_set(selection_set: Any, *, depth: int, root: bool = False) -> None:
    if depth > _MAX_QUERY_DEPTH:
        raise ValueError("query depth exceeds limit")
    seen_root_fields: set[str] = set()
    for field in selection_set.selections:
        if field.kind != "field" or field.alias is not None:
            raise ValueError("only direct profile fields are allowed")
        name = field.name.value
        if name.startswith("__") or (root and name not in _ALLOWED_ROOT_FIELDS):
            raise ValueError("query field is not allowed")
        if root and name in seen_root_fields:
            raise ValueError("duplicate root fields are not allowed")
        seen_root_fields.add(name)
        if field.selection_set is not None:
            _validate_selection_set(field.selection_set, depth=depth + 1)


def _public(result: ProfileResult | None) -> PublicProfile | None:
    if result is None or result.profile.display_name is None or result.profile.bio is None:
        return None
    return PublicProfile(
        account_id=result.profile.account_id,
        display_name=result.profile.display_name,
        bio=result.profile.bio,
        links=result.links,
        photo_url=(
            f"/api/v1/profiles/{result.profile.account_id}/photo"
            if result.profile.photo_key
            else None
        ),
    )


def _viewer(result: ProfileResult) -> ViewerProfile:
    return ViewerProfile(
        account_id=result.profile.account_id,
        display_name=result.profile.display_name or "",
        bio=result.profile.bio or "",
        links=result.links,
        photo_url=(
            f"/api/v1/profiles/{result.profile.account_id}/photo"
            if result.profile.photo_key
            else None
        ),
        visibility=result.profile.visibility,
        version=result.profile.version,
    )
