"""Mapping shape for immutable review decisions and founder notices."""

from typing import cast

from sqlalchemy import Table

from app.modules.notifications.models import Notification
from app.modules.products.models import Product, ProductReviewDecision, ProductSubmission


def test_review_mappings_expose_required_private_constraints() -> None:
    product_checks = {constraint.name for constraint in cast(Table, Product.__table__).constraints}
    submission_checks = {
        constraint.name for constraint in cast(Table, ProductSubmission.__table__).constraints
    }
    decision_checks = {
        constraint.name for constraint in cast(Table, ProductReviewDecision.__table__).constraints
    }
    notification_checks = {
        constraint.name for constraint in cast(Table, Notification.__table__).constraints
    }

    assert {"ck_products_status", "ck_products_submitted_fields"} <= product_checks
    assert {"ck_product_submissions_state", "ck_product_submissions_closed"} <= submission_checks
    assert {
        "ck_product_review_decisions_transition",
        "ck_product_review_decisions_feedback",
        "ck_product_review_decisions_version",
    } <= decision_checks
    assert "ck_notifications_kind" in notification_checks

    review_indexes = {index.name for index in cast(Table, ProductReviewDecision.__table__).indexes}
    notice_indexes = {index.name for index in cast(Table, Notification.__table__).indexes}
    submission_indexes = {
        index.name for index in cast(Table, ProductSubmission.__table__).indexes
    }
    assert {
        "uq_product_review_decisions_submission_from",
        "uq_product_review_decisions_actor_key",
        "ix_product_review_decisions_submission_created",
    } <= review_indexes
    assert {
        "ix_notifications_recipient_created",
        "ix_notifications_unread_recipient",
        "ix_notifications_product_id",
    } <= notice_indexes
    assert "ix_product_submissions_approved_page" in submission_indexes
