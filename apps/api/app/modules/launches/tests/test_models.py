"""Mapping contracts for persisted launch bookings and notice preferences."""

from typing import cast

from app.modules.launches.models import LaunchBooking
from app.modules.notifications.models import LaunchNotificationPreference, Notification
from app.modules.products.models import Product, ProductReviewDecision
from sqlalchemy import CheckConstraint, Table


def test_launch_booking_mapping_has_retained_identity_and_hot_path_indexes() -> None:
    table = cast(Table, LaunchBooking.__table__)
    assert {
        "id",
        "product_id",
        "founder_id",
        "launch_date",
        "launch_at",
        "state",
        "idempotency_key",
        "request_fingerprint",
        "closed_by_idempotency_key",
        "close_request_fingerprint",
        "failure_reason",
        "created_at",
        "closed_at",
    } <= set(table.columns.keys())
    assert {
        "uq_launch_bookings_active_product",
        "ix_launch_bookings_founder_date_active",
        "ix_launch_bookings_due",
        "uq_launch_bookings_founder_idempotency",
        "uq_launch_bookings_founder_close_idempotency",
    } <= {index.name for index in table.indexes}


def test_launch_preferences_default_all_independent_channels_on() -> None:
    table = cast(Table, LaunchNotificationPreference.__table__)
    assert {
        "reminder_email",
        "reminder_in_site",
        "live_email",
        "live_in_site",
        "failure_email",
        "failure_in_site",
    } <= set(table.columns.keys())
    assert all(
        table.c[field].server_default is not None
        for field in (
            "reminder_email",
            "reminder_in_site",
            "live_email",
            "live_in_site",
            "failure_email",
            "failure_in_site",
        )
    )


def test_product_and_notification_mappings_add_launch_state_without_dropping_review() -> None:
    product_columns = cast(Table, Product.__table__).columns
    assert {"launched_at", "launch_failure_reason"} <= set(product_columns.keys())
    decision_check = next(
        cast(CheckConstraint, constraint).sqltext
        for constraint in cast(Table, ProductReviewDecision.__table__).constraints
        if constraint.name == "ck_product_review_decisions_transition"
    )
    assert "scheduled" in str(decision_check)

    notification = cast(Table, Notification.__table__)
    assert notification.c.review_decision_id.nullable
    assert "launch_booking_id" in notification.columns
    assert "uq_notifications_review_decision" in {index.name for index in notification.indexes}
    assert "uq_notifications_launch_booking_kind" in {index.name for index in notification.indexes}
