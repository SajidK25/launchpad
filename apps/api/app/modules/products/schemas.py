"""Explicit input contracts for private product content."""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, TypeAdapter, field_validator

_HTTP_URL = TypeAdapter(AnyHttpUrl)


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
