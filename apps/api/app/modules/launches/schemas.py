"""Strict REST request and response contracts for launch bookings."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LaunchBookingInput(BaseModel):
    """Founder-selected UTC calendar date and expected product version."""

    model_config = ConfigDict(extra="forbid")

    launch_date: date
    expected_version: int = Field(ge=0, strict=True)


class LaunchBookingResponse(BaseModel):
    """Safe booking identity plus the product lifecycle result."""

    booking_id: UUID
    product_id: UUID
    state: Literal["scheduled", "cancelled", "replaced"]
    launch_date: date
    launch_at: datetime
    product_status: Literal["scheduled", "approved"]
    product_version: int = Field(ge=0)
