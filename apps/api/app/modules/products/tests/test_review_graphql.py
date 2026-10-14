"""Schema and read-boundary contracts for product review GraphQL fields."""

from __future__ import annotations

import pytest
from graphql import GraphQLObjectType
from strawberry import Schema

from app.graphql import Query, validate_read_query


def test_review_schema_exposes_owner_outcome_and_private_approved_discovery() -> None:
    schema = Schema(query=Query)._schema
    root = schema.query_type
    assert root is not None
    assert "approvedReviews" in root.fields
    detail = schema.get_type("ProductDetail")
    assert isinstance(detail, GraphQLObjectType) and "reviewOutcome" in detail.fields
    assert schema.mutation_type is None
    assert schema.subscription_type is None


@pytest.mark.parametrize(
    "query",
    [
        "query { approvedReviews(first: 10) { items { product { id } } nextCursor } }",
        'query { reviewProduct(id: "00000000-0000-0000-0000-000000000001") '
        "{ product { summary { id } reviewOutcome { status feedback } } } }",
    ],
)
def test_review_root_allowlist_accepts_private_read_operations(query: str) -> None:
    validate_read_query(query)
