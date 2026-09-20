"""Establish the Launchpad operational migration baseline.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Record the baseline without creating speculative product tables."""


def downgrade() -> None:
    """Deliberately leave the baseline in place; preparation never downgrades."""
