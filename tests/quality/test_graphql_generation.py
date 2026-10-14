"""Regression checks for schema-derived nested GraphQL operation types."""

from pathlib import Path

import strawberry
from app.graphql import Query

from scripts.quality.generate_graphql_types import generate


def test_product_operations_generate_concrete_nested_types(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.graphql"
    schema_path.write_text(strawberry.Schema(query=Query).as_str())
    operations_path = Path(__file__).resolve().parents[2] / "packages/contracts/operations.graphql"

    generated = generate(schema_path, operations_path)

    assert "export type ViewerProductsQueryVariables = {\n  first?: number;" in generated
    assert "export type ViewerProductsQuery = {\n  viewerProducts: {" in generated
    assert "items: Array<{" in generated
    assert "export type ViewerProductQueryVariables = {\n  id: string;" in generated
    assert "summary: {" in generated
    assert "export const REVIEW_QUEUE_QUERY" in generated
    assert "export const REVIEW_PRODUCT_QUERY" in generated
    assert "export const TOPIC_CHOICES_QUERY" in generated
    assert "unknown" not in generated
