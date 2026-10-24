"""Composed product/profile schema and strict read-query validation."""

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from graphql import GraphQLSchema
from strawberry import Schema

from app.graphql import (
    ProfileOnlyQuery,
    Query,
    build_router,
    validate_read_query,
)
from app.main import create_app
from app.modules.auth.sessions import MemberContext
from app.shared.config.settings import Settings
from app.shared.db.database import Database


def _query_fields(schema: Any) -> set[str]:
    query = cast(GraphQLSchema, schema._schema).query_type
    assert query is not None
    return set(query.fields)


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
        "approvedReviews",
        "topicChoices",
        "viewerNotificationInbox",
        "viewerLaunchBookings",
        "viewerLaunchNotificationPreferences",
        "publicProduct",
        "publicLaunches",
        "publicProductCatalog",
        "publicCatalogTopics",
    }
    assert schema.mutation_type is None
    assert schema.subscription_type is None


def test_public_launches_is_exposed_with_public_product_reads() -> None:
    schema: GraphQLSchema = Schema(query=Query)._schema
    root = schema.query_type
    assert root is not None
    assert "publicLaunches" in root.fields
    assert "publicProductCatalog" in root.fields
    assert "publicCatalogTopics" in root.fields


def test_feature_off_graphql_schema_keeps_profiles_without_product_fields() -> None:
    schema: GraphQLSchema = Schema(query=ProfileOnlyQuery)._schema

    root = schema.query_type
    assert root is not None
    assert set(root.fields) == {
        "viewerProfile",
        "publicProfile",
        "viewerNotificationInbox",
    }
    assert "viewerProducts" not in root.fields
    assert schema.mutation_type is None


def test_router_can_exclude_products_from_composed_schema() -> None:
    async def context_getter(request: Request, response: Response) -> dict[str, object]:
        return {}

    router = build_router(context_getter, include_products=False)

    assert _query_fields(router.schema) == {
        "viewerProfile",
        "publicProfile",
        "viewerNotificationInbox",
    }


def test_router_can_exclude_launch_reads_while_products_remain_enabled() -> None:
    async def context_getter(request: Request, response: Response) -> dict[str, object]:
        return {}

    router = build_router(context_getter, include_products=True, include_launches=False)

    assert _query_fields(router.schema) == {
        "viewerProfile",
        "publicProfile",
        "viewerProducts",
        "viewerProduct",
        "reviewQueue",
        "reviewProduct",
        "approvedReviews",
        "topicChoices",
        "viewerNotificationInbox",
    }


def test_router_composes_public_product_and_launch_reads_without_private_products() -> None:
    async def context_getter(request: Request, response: Response) -> dict[str, object]:
        return {}

    router = build_router(context_getter, include_products=False, include_launches=True)

    assert _query_fields(router.schema) == {
        "viewerProfile",
        "publicProfile",
        "viewerNotificationInbox",
        "viewerLaunchBookings",
        "viewerLaunchNotificationPreferences",
        "publicProduct",
        "publicLaunches",
        "publicProductCatalog",
        "publicCatalogTopics",
    }


@pytest.mark.parametrize("products_enabled", [False, True])
@pytest.mark.parametrize("launches_enabled", [False, True])
def test_app_mounts_product_rest_and_graphql_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, products_enabled: bool, launches_enabled: bool
) -> None:
    import sys

    main = cast(Any, sys.modules["app.main"])
    settings = Settings(
        products_enabled=products_enabled,
        launches_enabled=launches_enabled,
        review_writes_enabled=False,
        trusted_web_origins=("http://localhost:8080",),
    )
    monkeypatch.setattr(main, "load_settings", lambda: settings)

    databases: list[Database] = []
    connect = Database.connect

    def connect_and_capture(database_url: str) -> Database:
        database = connect(database_url)
        databases.append(database)
        return database

    monkeypatch.setattr(main.Database, "connect", connect_and_capture)
    graph_fields: list[set[str]] = []
    build_users = main.users_router

    def build_users_and_capture(**kwargs: Any) -> tuple[Any, Any]:
        profile_routes, graphql_routes = build_users(**kwargs)
        graph_fields.append(_query_fields(graphql_routes.schema))
        return profile_routes, graphql_routes

    monkeypatch.setattr(main, "users_router", build_users_and_capture)
    try:
        application = create_app()
        paths = set(application.openapi()["paths"])
        product_route_present = "/api/v1/me/products" in paths
        launch_route_present = "/api/v1/me/products/{product_id}/launch-booking" in paths
        preference_route_present = "/api/v1/me/launch-notification-preferences" in paths
        notification_route_present = "/api/v1/me/notifications/{notification_id}/read" in paths

        assert product_route_present is products_enabled
        assert launch_route_present is launches_enabled
        assert preference_route_present is launches_enabled
        assert notification_route_present
        assert graph_fields == [
            (
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
                }
                if products_enabled and launches_enabled
                else {
                    "viewerProfile",
                    "publicProfile",
                    "viewerProducts",
                    "viewerProduct",
                    "reviewQueue",
                    "reviewProduct",
                    "approvedReviews",
                    "topicChoices",
                    "viewerNotificationInbox",
                }
                if products_enabled
                else {
                    "viewerProfile",
                    "publicProfile",
                    "viewerNotificationInbox",
                    "viewerLaunchBookings",
                    "viewerLaunchNotificationPreferences",
                    "publicProduct",
                    "publicLaunches",
                    "publicProductCatalog",
                    "publicCatalogTopics",
                }
                if launches_enabled
                else {"viewerProfile", "publicProfile", "viewerNotificationInbox"}
            )
        ]
    finally:
        for database in databases:
            asyncio.run(database.close())


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
    validate_read_query(
        "query { publicLaunches(first: 10) { todayDate items { id name pitch logoUrl topics } } }"
    )
    validate_read_query(
        'query { publicProductCatalog(search: "launch", topicIds: []) '
        "{ items { id name pitch topics } nextCursor } }"
    )
    validate_read_query(
        'query { publicCatalogTopics(query: "cloud", selectedIds: []) '
        "{ choices { id displayName } selected { id displayName } } }"
    )


def test_composed_router_is_post_only_and_redacts_unexpected_read_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="launchpad.graphql")

    class SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    class BrokenProductService:
        async def owner_list(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("private-database-value")

        async def public_product_catalog(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("private-catalog-database-value")

    async def context_getter(request: Request, response: Response) -> dict[str, object]:
        return {
            "member": MemberContext(account_id=uuid4(), verified=True, session_id=uuid4()),
            "session_factory": SessionContext,
            "product_service_factory": BrokenProductService,
            "request_id": "review-test-request-id",
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
        catalog_response = client.post(
            "/api/v1/graphql",
            json={"query": "query { publicProductCatalog { items { id } } }"},
        )
    assert response.status_code == 200
    assert response.json()["data"] is None
    assert response.json()["errors"][0]["message"] == "request could not be completed"
    assert "private-database-value" not in response.text
    assert catalog_response.json()["data"] is None
    assert catalog_response.json()["errors"][0]["message"] == "request could not be completed"
    assert "private-catalog-database-value" not in catalog_response.text
    diagnostic = next(
        record
        for record in caplog.records
        if getattr(record, "operation", None) == "viewerProducts"
    )
    diagnostic_values = cast(Any, diagnostic)
    assert diagnostic_values.component == "graphql"
    assert diagnostic_values.outcome == "failed"
    assert diagnostic_values.request_id == "review-test-request-id"
    assert diagnostic_values.context == {"exception_type": "RuntimeError"}
    assert "private-database-value" not in str(diagnostic_values.context)
    catalog_diagnostic = next(
        record
        for record in caplog.records
        if getattr(record, "operation", None) == "publicProductCatalog"
    )
    catalog_diagnostic_values = cast(Any, catalog_diagnostic)
    assert catalog_diagnostic_values.component == "graphql"
    assert catalog_diagnostic_values.outcome == "failed"
    assert catalog_diagnostic_values.request_id == "review-test-request-id"
    assert catalog_diagnostic_values.context == {"exception_type": "RuntimeError"}
    assert "private-catalog-database-value" not in str(catalog_diagnostic_values.context)
