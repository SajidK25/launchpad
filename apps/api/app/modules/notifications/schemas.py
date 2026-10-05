"""Typed notification inbox projections for private read boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

NotificationKind = Literal["review_approved", "review_rejected", "review_changes_requested"]


@dataclass(frozen=True, slots=True)
class NotificationItem:
    """Founder-safe notice with its owner-authorized product destination."""

    id: UUID
    product_id: UUID
    kind: NotificationKind
    created_at: datetime
    read_at: datetime | None


@dataclass(frozen=True, slots=True)
class NotificationInbox:
    """One bounded inbox page plus its authoritative unread total."""

    items: tuple[NotificationItem, ...]
    unread_count: int
    next_cursor: str | None
