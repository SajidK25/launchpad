"""Explicit input contracts for private product content."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

_HTTP_URL = TypeAdapter(AnyHttpUrl)
ProductStatus = Literal["draft", "submitted", "changes_requested", "approved", "rejected"]


class ProductContentInput(BaseModel):
    """Optional draft fields; blank values are represented as missing content."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=80)
    pitch: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    website_url: str | None = Field(default=None, max_length=2048)

    @field_validator("name", "pitch", "description", mode="before")
    @classmethod
    def trim_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("pitch")
    @classmethod
    def require_single_line_pitch(cls, value: str | None) -> str | None:
        if value is not None and ("\n" in value or "\r" in value):
            raise ValueError("pitch must be a single line")
        return value

    @field_validator("website_url", mode="before")
    @classmethod
    def trim_optional_website(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("website_url")
    @classmethod
    def require_https_website(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            _HTTP_URL.validate_python(value)
            parsed = urlsplit(value)
            hostname = parsed.hostname
            parsed.port
        except ValueError as exc:
            raise ValueError("website_url must be a valid HTTPS URL") from exc
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.netloc
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(character.isspace() for character in value)
        ):
            raise ValueError("website_url must be a valid HTTPS URL")
        return value


class ProductSaveInput(ProductContentInput):
    """Versioned partial content update with optional full topic replacement."""

    version: int = Field(ge=0, strict=True)
    topic_names: list[str] | None = Field(default=None, max_length=3)

    @field_validator("topic_names", mode="before")
    @classmethod
    def reject_explicit_null_topics(cls, value: object) -> object:
        if value is None:
            raise ValueError("topic_names must be a list when supplied")
        return value

    def changed_content(self) -> ProductContentInput:
        """Pass only supplied content fields to the aggregate save service."""

        return ProductContentInput.model_validate(
            self.model_dump(exclude_unset=True, exclude={"version", "topic_names"})
        )


class ProductVersionInput(BaseModel):
    """Expected version for an explicit state transition."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0, strict=True)


class ProductWithdrawInput(ProductVersionInput):
    """Target the exact active queue period being withdrawn."""

    submission_id: UUID


class ReviewDecisionInput(BaseModel):
    """Version-bound staff decision request with an outcome-specific feedback contract."""

    model_config = ConfigDict(extra="forbid")

    submission_id: UUID
    expected_version: int = Field(ge=0, strict=True)
    outcome: Literal["approved", "rejected", "changes_requested"]
    feedback: str | None = Field(default=None, max_length=2000)

    @field_validator("feedback", mode="before")
    @classmethod
    def normalize_feedback(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def validate_feedback_for_outcome(self) -> ReviewDecisionInput:
        if self.outcome == "approved" and self.feedback is not None:
            raise ValueError("approval cannot include feedback")
        if self.outcome != "approved" and not self.feedback:
            raise ValueError("a reason is required for this outcome")
        return self


class ReviewDecisionResponse(BaseModel):
    """Safe result of a staff review command."""

    decision_id: UUID
    product_id: UUID
    submission_id: UUID
    status: Literal["approved", "rejected", "changes_requested"]
    version: int


class ProductStateResponse(BaseModel):
    """Owner-safe product identity and optimistic version."""

    id: UUID
    status: ProductStatus
    version: int


class ProductSubmitResponse(BaseModel):
    """Owner-safe current queue period without private content."""

    submission_id: UUID
    product_id: UUID
    product_version: int


class ProductAssetIntentInput(BaseModel):
    """Bounded declaration for one private logo or screenshot upload."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["logo", "screenshot"]
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    size: int = Field(gt=0, le=5 * 1024 * 1024, strict=True)


class ProductAssetIntentResponse(BaseModel):
    """Short-lived upload capability; never includes a storage object key."""

    asset_id: UUID
    upload_url: str
    fields: dict[str, str]
    expires_in: int
    upload_method: Literal["POST", "PUT"]
    upload_transport: Literal["storage_form", "authenticated_api"]
    upload_headers: dict[str, str]


class ProductAssetCompleteResponse(BaseModel):
    """Safe status of an image that passed byte-level validation."""

    asset_id: UUID
    kind: Literal["logo", "screenshot"]
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    byte_count: int
    state: Literal["clean", "failed"]


class ProductAssetAttachmentInput(BaseModel):
    """Full versioned replacement for a draft's ordered private media selection."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0, strict=True)
    logo_asset_id: UUID | None
    screenshot_asset_ids: list[UUID] = Field(max_length=10)
