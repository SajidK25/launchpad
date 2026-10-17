"""Booking command validation and safe domain failures."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


class LaunchError(ValueError):
    """Base class for launch booking failures."""


class LaunchForbiddenError(LaunchError):
    """The current account cannot manage this booking."""


class LaunchNotFoundError(LaunchError):
    """The booking or product is unavailable to this founder."""


class LaunchConflictError(LaunchError):
    """The request conflicts with current launch state or capacity."""


def utc_now(value: datetime) -> datetime:
    """Require an aware clock value and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("launch clock must be timezone-aware")
    return value.astimezone(UTC)


def require_eligible_date(value: date, *, now: datetime) -> datetime:
    """Return UTC midnight for tomorrow through day 90 inclusive."""

    current_date = utc_now(now).date()
    if value <= current_date or value > current_date + timedelta(days=90):
        raise LaunchConflictError("launch date must be tomorrow through 90 days ahead (UTC)")
    return datetime.combine(value, datetime.min.time(), tzinfo=UTC)


def require_before_launch(launch_at: datetime, *, now: datetime) -> None:
    """Enforce the immutable original midnight boundary for changes and cancellation."""

    if utc_now(now) >= utc_now(launch_at):
        raise LaunchConflictError("booking can no longer be changed")
