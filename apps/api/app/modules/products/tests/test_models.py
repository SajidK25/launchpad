"""Mapping-level guards for the private product schema."""

from app.modules.auth.models import Account, AccountAdminAction
from app.modules.products.models import (
    Product,
    ProductAsset,
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
    } == {"products", "product_submissions", "topics", "product_topics", "product_assets"}
    assert "role" in Account.__table__.columns
    assert "suspended_at" in Account.__table__.columns
    assert AccountAdminAction.__tablename__ == "account_admin_actions"
