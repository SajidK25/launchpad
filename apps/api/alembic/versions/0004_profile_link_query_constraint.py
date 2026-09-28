"""Allow policy-compliant query strings in public profile links."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_profile_link_query"
down_revision: str = "0003_profile_link_hardening"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_profile_links_https", "profile_links", type_="check")
    op.create_check_constraint(
        "ck_profile_links_https",
        "profile_links",
        "url ~ '^https://[^/@?#[:space:]]+(/[^?#[:space:]]*)?(\\?[^#[:space:]]*)?$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_profile_links_https", "profile_links", type_="check")
    op.create_check_constraint(
        "ck_profile_links_https",
        "profile_links",
        "url ~ '^https://[^/@?#[:space:]]+(/[^?#[:space:]]*)?$'",
    )
