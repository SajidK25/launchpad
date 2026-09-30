"""Composed product/profile schema and strict read-query validation."""

from uuid import uuid4

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from graphql import GraphQLSchema
from strawberry import Schema

from app.graphql import Query, build_router, validate_read_query
from app.modules.auth.sessions import MemberContext


def test_composed_schema_preserves_profiles_and_adds_private_product_reads() -> None:
    schema: GraphQLSchema = Schema(query=Query)._schema
    root = schema.query_type
    assert root is not None
    assert set(root.fields) == {
        "viewerProfile",
        "publicProfile",
        "viewerProducts",
        "viewerProduct",
        "reviewQueue",
        "reviewProduct",
        "topicChoices",
    }
    assert schema.mutation_type is None
    assert schema.subscription_type is None


@pytest.mark.parametrize(
    "query",
    [
        "mutation { viewerProducts { nextCursor } }",
        "query { __schema { queryType { name } } }",
        "query { renamed: viewerProducts { nextCursor } }",
        "query { viewerProducts { items { ...Fields } } } fragment Fields on ProductSummary { id }",
        "query { viewerProducts(first: 1) { items { id } } viewerProducts { nextCursor } }",
        "query { reviewQueue @skip(if: true) { items { product { id } } } }",
        "query { viewerProducts { items { id } } } " + " " * 8192,
    ],
)
def test_composed_validator_rejects_unsafe_documents(query: str) -> None:
    with pytest.raises(ValueError):
        validate_read_query(query)


def test_composed_validator_accepts_existing_profile_and_bounded_product_roots() -> None:
    validate_read_query(
        "query { viewerProfile { accountId displayName bio links photoUrl visibility version } }"
    )
    validate_read_query(
        "query { viewerProducts(first: 10) { items { id version } nextCursor } "
        "topicChoices(first: 10) { id displayName } }"
    )


def test_composed_router_is_post_only_and_redacts_unexpected_read_errors() -> None:
    class SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    class BrokenProductService:
        async def owner_list(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("private-database-value")

    async def context_getter(request: Request, response: Response) -> dict[str, object]:
        return {
            "member": MemberContext(account_id=uuid4(), verified=True, session_id=uuid4()),
            "session_factory": SessionContext,
            "product_service_factory": BrokenProductService,
        }

    router = build_router(context_getter)
    assert [
        (route.path, route.methods) for route in router.routes if isinstance(route, APIRoute)
    ] == [("/graphql", {"POST"})]
    assert len(router.routes) == 1
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        assert client.get("/api/v1/graphql").status_code == 405
        response = client.post(
            "/api/v1/graphql",
            json={"query": "query { viewerProducts { nextCursor } }"},
        )
    assert response.status_code == 200
    assert response.json()["data"] is None
    assert response.json()["errors"][0]["message"] == "request could not be completed"
    assert "private-database-value" not in response.text
