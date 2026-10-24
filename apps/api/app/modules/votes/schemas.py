"""Bounded HTTP request and response schemas for vote commands."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class VoteInput(BaseModel):
    """Target product for a member cast command."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID


class VoteResponse(BaseModel):
    """Confirmed vote state returned only after the transaction commits."""

    vote_id: UUID
    product_id: UUID
    active: bool
    cast_at: datetime
    replayed: bool
