"""REST contracts for confirmed discussion commands and live admission."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CommentCreateInput(BaseModel):
    """Plain-text member input; domain normalization remains authoritative."""

    model_config = ConfigDict(extra="forbid")

    body: str


class CommentResponse(BaseModel):
    """One server-confirmed immutable entry."""

    id: UUID
    product_id: UUID
    parent_id: UUID | None
    body: str
    created_at: datetime
    replayed: bool


class CommentLiveTicketResponse(BaseModel):
    """Short-lived public ticket scoped to one current product."""

    ticket: str
    expires_at: datetime
