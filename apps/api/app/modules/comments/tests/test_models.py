"""Mapping contracts for immutable comments and retry receipts."""

from typing import cast

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table

from app.modules.comments.models import Comment, CommentIdempotencyReceipt


def test_comment_mappings_have_approved_fields_constraints_and_indexes() -> None:
    comment_table = cast(Table, Comment.__table__)
    receipt_table = cast(Table, CommentIdempotencyReceipt.__table__)

    assert set(comment_table.columns.keys()) == {
        "id",
        "product_id",
        "author_account_id",
        "depth",
        "parent_id",
        "parent_depth",
        "body",
        "body_fingerprint",
        "moderation_status",
        "created_at",
    }
    assert set(receipt_table.columns.keys()) == {
        "id",
        "author_account_id",
        "idempotency_key",
        "request_fingerprint",
        "comment_id",
        "created_at",
    }

    assert {
        "ck_comments_depth",
        "ck_comments_topology",
        "ck_comments_body",
        "ck_comments_body_fingerprint",
        "ck_comments_moderation_status",
    } <= {
        constraint.name
        for constraint in comment_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_comment_receipts_key",
        "ck_comment_receipts_fingerprint",
    } <= {
        constraint.name
        for constraint in receipt_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ix_comments_visible_product_created",
        "ix_comments_visible_parent_created",
        "ix_comments_author_created",
        "ix_comments_duplicate_lookup",
    } == {index.name for index in comment_table.indexes}
    assert {
        "uq_comment_receipts_author_key",
        "ix_comment_receipts_comment",
    } == {index.name for index in receipt_table.indexes}


def test_comment_parent_and_owner_foreign_keys_are_restrictive() -> None:
    comment_table = cast(Table, Comment.__table__)
    receipt_table = cast(Table, CommentIdempotencyReceipt.__table__)

    comment_foreign_keys = {
        constraint.name: constraint
        for constraint in comment_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    receipt_foreign_keys = {
        constraint.name: constraint
        for constraint in receipt_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert set(comment_foreign_keys) == {
        "fk_comments_product",
        "fk_comments_author",
        "fk_comments_parent",
    }
    assert set(receipt_foreign_keys) == {
        "fk_comment_receipts_author",
        "fk_comment_receipts_comment",
    }
    assert all(
        element.ondelete == "RESTRICT"
        for constraint in (*comment_foreign_keys.values(), *receipt_foreign_keys.values())
        for element in constraint.elements
    )
    parent = comment_foreign_keys["fk_comments_parent"]
    assert [column.name for column in parent.columns] == [
        "parent_id",
        "product_id",
        "parent_depth",
    ]
    assert [element.target_fullname for element in parent.elements] == [
        "comments.id",
        "comments.product_id",
        "comments.depth",
    ]


def test_comment_mappings_do_not_store_private_attribution_or_mutation_state() -> None:
    comment_columns = set(cast(Table, Comment.__table__).columns.keys())
    assert (
        not {
            "author_email",
            "author_display_name",
            "author_photo_key",
            "updated_at",
            "deleted_at",
            "edited_at",
        }
        & comment_columns
    )
