"""Typed notification inbox projections for private read boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

NotificationKind = Literal[
    "review_approved",
    "review_rejected",
    "review_changes_requested",
    "launch_reminder",
    "launch_live",
    "launch_failed",
]


LAUNCH_PREFERENCE_FIELDS = (
    "reminder_email",
    "reminder_in_site",
    "live_email",
    "live_in_site",
    "failure_email",
    "failure_in_site",
)


class LaunchNotificationPreferences(BaseModel):
    """Six independent default-on launch notice channels."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reminder_email: bool = True
    reminder_in_site: bool = True
    live_email: bool = True
    live_in_site: bool = True
    failure_email: bool = True
    failure_in_site: bool = True


class LaunchNotificationPreferenceUpdate(BaseModel):
    """Complete strict REST update for all independent launch channels."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reminder_email: bool
    reminder_in_site: bool
    live_email: bool
    live_in_site: bool
    failure_email: bool
    failure_in_site: bool


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
