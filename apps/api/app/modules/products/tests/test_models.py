"""Mapping-level guards for the private product schema."""

from typing import cast

from sqlalchemy import Table

from app.modules.auth.models import Account, AccountAdminAction
from app.modules.notifications.models import Notification
from app.modules.products.models import (
    Product,
    ProductAsset,
    ProductReviewDecision,
    ProductSubmission,
    ProductTopic,
    Topic,
)


def test_product_mappings_own_all_private_tables() -> None:
    assert {
        Product.__tablename__,
        ProductSubmission.__tablename__,
        Topic.__tablename__,
        ProductTopic.__tablename__,
        ProductAsset.__tablename__,
        ProductReviewDecision.__tablename__,
    } == {
        "products",
        "product_submissions",
        "topics",
        "product_topics",
        "product_assets",
        "product_review_decisions",
    }
    assert Notification.__tablename__ == "notifications"
    assert "role" in Account.__table__.columns
    assert "suspended_at" in Account.__table__.columns
    assert AccountAdminAction.__tablename__ == "account_admin_actions"


def test_product_launched_at_index_is_partial_on_launched_rows() -> None:
    index = next(
        index
        for index in cast(Table, Product.__table__).indexes
        if index.name == "ix_products_launched_at"
    )
    assert [column.name for column in index.columns] == ["launched_at"]
    assert str(index.dialect_options["postgresql"]["where"]) == "status = 'launched'"
