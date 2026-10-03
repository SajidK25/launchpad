"""Notification policy decisions owned by the notifications feature."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

NotificationKind = Literal["review_approved", "review_rejected", "review_changes_requested"]


def review_notification_kind(outcome: str) -> NotificationKind:
    """Map an accepted review outcome to its stable inbox kind."""

    kinds: dict[str, NotificationKind] = {
        "approved": "review_approved",
        "rejected": "review_rejected",
        "changes_requested": "review_changes_requested",
    }
    try:
        return kinds[outcome]
    except KeyError as exc:
        raise ValueError("unsupported review outcome") from exc


def can_read_notification(*, recipient_account_id: UUID, account_id: UUID) -> bool:
    """Allow notification reads only to the account named as the recipient."""

    return recipient_account_id == account_id
