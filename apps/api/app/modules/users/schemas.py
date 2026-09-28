"""Explicit REST contracts for profile actions and reads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProfilePatchRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    bio: str | None = Field(default=None, max_length=160)
    links: list[str] | None = Field(default=None, max_length=20)
    photo_upload_id: UUID | None = None
    version: int = Field(ge=0)


class ProfileResponse(BaseModel):
    account_id: UUID
    display_name: str | None
    bio: str | None
    photo_url: str | None
    links: list[str]
    visibility: str
    published_at: datetime | None
    version: int
    became_private: bool = False


class PhotoUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size: int = Field(gt=0, le=5 * 1024 * 1024)


class PhotoUploadResponse(BaseModel):
    upload_id: UUID
    upload_url: str
    fields: dict[str, str]
    expires_in: int


class PhotoCompleteResponse(BaseModel):
    upload_id: UUID
    media_type: str
    byte_count: int
