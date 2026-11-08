"""Bounded public discussion GraphQL projections."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import strawberry
from fastapi import FastAPI
from fastapi.testclient import TestClient
from strawberry.types.execution import ExecutionResult

from app.graphql import build_router
from app.modules.auth.sessions import MemberContext
from app.modules.comments.graphql import CommentQuery
from app.modules.comments.policies import CommentNotFoundError, CommentValidationError
from app.modules.comments.service import (
    CommentDiscussionPage,
    CommentEntry,
    CommentReplyPage,
    CommentThread,
)

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


class _Attribution:
    def __init__(self, missing: UUID | None = None) -> None:
        self.calls: list[tuple[UUID, ...]] = []
        self.missing = missing

    async def batch(self, _session: object, account_ids: tuple[UUID, ...]) -> dict[UUID, object]:
        self.calls.append(account_ids)
        return {
            account_id: SimpleNamespace(
                account_id=account_id,
                display_name=f"Author {index}",
                has_photo=True,
                public_profile_url=(f"/public/{account_id}" if index == 0 else None),
            )
            for index, account_id in enumerate(account_ids)
            if account_id != self.missing
        }


class _Service:
    def __init__(
        self,
        *,
        unavailable: bool = False,
        invalid: bool = False,
        missing: UUID | None = None,
    ) -> None:
        self.product_id = uuid4()
        self.root_author = uuid4()
        self.reply_author = missing or uuid4()
        self.root_id = uuid4()
        self.reply_id = uuid4()
        self.unavailable = unavailable
        self.invalid = invalid
        self.attribution_access = _Attribution(missing)

    async def discussion(self, _session: object, **_kwargs: object) -> CommentDiscussionPage:
        if self.unavailable:
            raise CommentNotFoundError("private product detail")
        if self.invalid:
            raise CommentValidationError("private cursor detail")
        root = CommentEntry(self.root_id, self.product_id, self.root_author, None, "Root", NOW)
        reply = CommentEntry(
            self.reply_id,
            self.product_id,
            self.reply_author,
            self.root_id,
            "Reply",
            NOW + timedelta(seconds=1),
        )
        return CommentDiscussionPage((CommentThread(root, 4, (reply,)),), "next")

    async def replies(self, _session: object, **_kwargs: object) -> CommentReplyPage:
        reply = CommentEntry(
            self.reply_id,
            self.product_id,
            self.reply_author,
            self.root_id,
            "Reply",
            NOW,
        )
        return CommentReplyPage((reply,), "earlier")


def _context(service: _Service, member: MemberContext | None = None) -> dict[str, object]:
    @asynccontextmanager
    async def session_factory() -> AsyncIterator[object]:
        yield object()

    return {
        "member": member,
        "request_id": "comments-test",
        "session_factory": session_factory,
        "comment_service_factory": lambda: service,
    }


def _execute(service: _Service, member: MemberContext | None = None) -> ExecutionResult:
    schema = strawberry.Schema(query=CommentQuery)
    return asyncio.run(
        schema.execute(
            """query Discussion($productId: UUID!) {
              productDiscussion(productId: $productId) {
                items {
                  id productId parentId body createdAt replyCount
                  author { accountId displayName avatarUrl publicProfileUrl }
                  replies { id body author { accountId displayName avatarUrl } }
                }
                nextCursor
              }
            }""",
            context_value=_context(service, member),
            variable_values={"productId": str(service.product_id)},
        )
    )


def test_discussion_is_identical_for_guests_and_members_and_batches_attribution() -> None:
    service = _Service()
    guest = _execute(service)
    member = _execute(service, MemberContext(uuid4(), True, uuid4(), role="member"))

    assert guest.errors is None
    assert member.errors is None
    assert guest.data == member.data
    assert service.attribution_access.calls == [
        (service.root_author, service.reply_author),
        (service.root_author, service.reply_author),
    ]
    page = cast(dict[str, object], cast(dict[str, object], guest.data)["productDiscussion"])
    thread = cast(dict[str, object], cast(list[object], page["items"])[0])
    assert thread["replyCount"] == 4
    assert thread["author"] == {
        "accountId": str(service.root_author),
        "displayName": "Author 0",
        "avatarUrl": (
            f"/api/v1/products/{service.product_id}/comment-authors/{service.root_author}/photo"
        ),
        "publicProfileUrl": f"/public/{service.root_author}",
    }


def test_reply_page_uses_one_attribution_batch_and_bounded_cursor_shape() -> None:
    service = _Service()
    schema = strawberry.Schema(query=CommentQuery)
    result = asyncio.run(
        schema.execute(
            """query Replies($productId: UUID!, $parentId: UUID!) {
              commentReplies(
                productId: $productId
                parentId: $parentId
                first: 20
              ) {
                items { id parentId author { displayName avatarUrl } }
                earlierCursor
              }
            }""",
            context_value=_context(service),
            variable_values={
                "productId": str(service.product_id),
                "parentId": str(service.root_id),
            },
        )
    )

    assert result.errors is None
    assert service.attribution_access.calls == [(service.reply_author,)]
    page = cast(dict[str, object], cast(dict[str, object], result.data)["commentReplies"])
    assert page["earlierCursor"] == "earlier"


def test_unavailable_discussion_preserves_typed_error_for_transport_sanitizer() -> None:
    result = _execute(_Service(unavailable=True))

    assert result.errors
    assert isinstance(result.errors[0].original_error, CommentNotFoundError)


def test_incomplete_current_attribution_fails_without_anonymous_projection() -> None:
    missing = uuid4()
    result = _execute(_Service(missing=missing))

    assert result.data is None
    assert result.errors
    assert result.errors[0].message == "request could not be completed"


def test_application_transport_sanitizes_unavailable_and_invalid_discussion() -> None:
    async def context() -> dict[str, object]:
        return _context(service)

    app = FastAPI()
    app.include_router(build_router(context), prefix="/api/v1")
    with TestClient(app) as client:
        service = _Service(unavailable=True)
        unavailable = client.post(
            "/api/v1/graphql",
            json={
                "query": (
                    f'query {{ productDiscussion(productId: "{service.product_id}") '
                    "{ items { id } } }"
                )
            },
        )
        assert unavailable.json()["errors"][0]["message"] == "discussion unavailable"

        service = _Service(invalid=True)
        invalid = client.post(
            "/api/v1/graphql",
            json={
                "query": (
                    f'query {{ productDiscussion(productId: "{service.product_id}") '
                    "{ items { id } } }"
                )
            },
        )
        assert invalid.json()["errors"][0]["message"] == "invalid discussion query"


def test_comment_schema_contains_only_bounded_read_roots() -> None:
    schema = strawberry.Schema(query=CommentQuery).as_str()

    assert "productDiscussion(productId: UUID!, first: Int! = 20, after: String = null)" in schema
    assert (
        "commentReplies(productId: UUID!, parentId: UUID!, first: Int! = 20, "
        "before: String = null)" in schema
    )
    assert "Mutation" not in schema
    assert "Subscription" not in schema
