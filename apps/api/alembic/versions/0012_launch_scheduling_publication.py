"""Add durable launch bookings, preferences, and publication state."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_launch_schedule"
down_revision: str | None = "0011_profile_upload_declarations"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("launched_at", sa.DateTime(timezone=True)))
    op.add_column("products", sa.Column("launch_failure_reason", sa.Text()))
    op.drop_constraint("ck_products_status", "products", type_="check")
    op.create_check_constraint(
        "ck_products_status",
        "products",
        "status IN ('draft', 'submitted', 'changes_requested', 'approved', 'rejected', "
        "'scheduled', 'launched')",
    )
    op.create_check_constraint(
        "ck_products_launched_at",
        "products",
        "(status = 'launched' AND launched_at IS NOT NULL) OR "
        "(status <> 'launched' AND launched_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_products_launch_failure_reason",
        "products",
        "launch_failure_reason IS NULL OR "
        "launch_failure_reason IN ('missed_day', 'suspension_blocked')",
    )

    op.drop_constraint(
        "ck_product_review_decisions_transition", "product_review_decisions", type_="check"
    )
    op.create_check_constraint(
        "ck_product_review_decisions_transition",
        "product_review_decisions",
        "(from_status = 'submitted' AND outcome IN "
        "('approved', 'rejected', 'changes_requested')) OR "
        "(from_status = 'approved' AND outcome = 'changes_requested') OR "
        "(from_status = 'scheduled' AND outcome = 'changes_requested')",
    )

    op.create_table(
        "launch_bookings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "founder_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("launch_date", sa.Date(), nullable=False),
        sa.Column("launch_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("closed_by_idempotency_key", sa.Text()),
        sa.Column("close_request_fingerprint", sa.Text()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('scheduled', 'replaced', 'cancelled', 'launched', 'missed_day', "
            "'suspension_blocked', 'returned_for_changes')",
            name="ck_launch_bookings_state",
        ),
        sa.CheckConstraint(
            "(state = 'scheduled' AND closed_at IS NULL) OR "
            "(state <> 'scheduled' AND closed_at IS NOT NULL)",
            name="ck_launch_bookings_closed",
        ),
        sa.CheckConstraint(
            "launch_at = (launch_date::timestamp AT TIME ZONE 'UTC')",
            name="ck_launch_bookings_utc_midnight",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 255 AND "
            "idempotency_key = trim(idempotency_key) AND "
            "length(request_fingerprint) = 64",
            name="ck_launch_bookings_idempotency",
        ),
        sa.CheckConstraint(
            "(closed_by_idempotency_key IS NULL AND close_request_fingerprint IS NULL) OR "
            "(closed_by_idempotency_key IS NOT NULL AND "
            "length(closed_by_idempotency_key) BETWEEN 1 AND 255 AND "
            "closed_by_idempotency_key = trim(closed_by_idempotency_key) AND "
            "length(close_request_fingerprint) = 64)",
            name="ck_launch_bookings_close_idempotency",
        ),
        sa.CheckConstraint(
            "(state IN ('missed_day', 'suspension_blocked') AND failure_reason IS NOT NULL) OR "
            "(state NOT IN ('missed_day', 'suspension_blocked') AND failure_reason IS NULL)",
            name="ck_launch_bookings_failure_reason",
        ),
        sa.CheckConstraint(
            "failure_reason IS NULL OR failure_reason IN ('missed_day', 'suspension_blocked')",
            name="ck_launch_bookings_failure_reason_value",
        ),
    )
    op.create_index(
        "uq_launch_bookings_active_product",
        "launch_bookings",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("state = 'scheduled'"),
    )
    op.create_index(
        "ix_launch_bookings_founder_date_active",
        "launch_bookings",
        ["founder_id", "launch_date"],
        postgresql_where=sa.text("state = 'scheduled'"),
    )
    op.create_index(
        "ix_launch_bookings_due",
        "launch_bookings",
        ["state", "launch_at"],
        postgresql_where=sa.text("state = 'scheduled'"),
    )
    op.create_index(
        "uq_launch_bookings_founder_idempotency",
        "launch_bookings",
        ["founder_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "uq_launch_bookings_founder_close_idempotency",
        "launch_bookings",
        ["founder_id", "closed_by_idempotency_key"],
        unique=True,
        postgresql_where=sa.text("closed_by_idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "launch_notification_preferences",
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("reminder_email", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reminder_in_site", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("live_email", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("live_in_site", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failure_email", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failure_in_site", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.drop_constraint("notifications_review_decision_id_key", "notifications", type_="unique")
    op.alter_column("notifications", "review_decision_id", nullable=True)
    op.add_column("notifications", sa.Column("launch_booking_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_notifications_launch_booking_id_launch_bookings",
        "notifications",
        "launch_bookings",
        ["launch_booking_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_kind",
        "notifications",
        "(review_decision_id IS NOT NULL AND launch_booking_id IS NULL AND "
        "kind IN ('review_approved', 'review_rejected', 'review_changes_requested')) OR "
        "(review_decision_id IS NULL AND launch_booking_id IS NOT NULL AND "
        "kind IN ('launch_reminder', 'launch_live', 'launch_failed'))",
    )
    op.create_check_constraint(
        "ck_notifications_source",
        "notifications",
        "(review_decision_id IS NULL) <> (launch_booking_id IS NULL)",
    )
    op.create_index(
        "uq_notifications_review_decision",
        "notifications",
        ["review_decision_id"],
        unique=True,
        postgresql_where=sa.text("review_decision_id IS NOT NULL"),
    )
    op.create_index(
        "uq_notifications_launch_booking_kind",
        "notifications",
        ["launch_booking_id", "kind"],
        unique=True,
        postgresql_where=sa.text("launch_booking_id IS NOT NULL"),
    )


def downgrade() -> None:
    raise RuntimeError("Launch bookings and publication history require an explicit retention plan")
