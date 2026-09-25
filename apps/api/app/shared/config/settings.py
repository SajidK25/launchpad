"""Validated settings with safe local defaults and separate storage credentials."""

from __future__ import annotations

import os
from base64 import b64decode
from binascii import Error as Base64Error
from collections.abc import Mapping, Sequence
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    AnyHttpUrl,
    AnyUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PostgresDsn,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)


class ConfigurationError(ValueError):
    """Safe configuration error that names fields but never includes their values."""


class Settings(BaseModel):
    """Application settings loaded from `LAUNCHPAD_`-prefixed environment variables."""

    model_config = ConfigDict(extra="ignore")

    environment: Literal["development", "test", "check", "production"] = "development"
    database_url: PostgresDsn = PostgresDsn(
        "postgresql://launchpad_development:launchpad_development_password@postgres:5432/launchpad_development"
    )
    storage_endpoint_url: AnyHttpUrl = AnyHttpUrl("http://minio:9000")
    redis_url: AnyUrl = AnyUrl("redis://redis:6379/0")
    storage_bucket: str = "launchpad-private"
    storage_access_key_id: SecretStr | None = None
    storage_secret_access_key: SecretStr | None = None
    bootstrap_storage_access_key_id: SecretStr | None = None
    bootstrap_storage_secret_access_key: SecretStr | None = None
    mail_web_origin: AnyHttpUrl | None = None
    mail_sender: EmailStr | None = None
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_use_tls: bool | None = None
    smtp_username: SecretStr | None = None
    smtp_password: SecretStr | None = None
    outbox_key_id: str | None = None
    outbox_key: SecretStr | None = None
    trusted_web_origins: tuple[str, ...] = ()
    public_upload_endpoint_url: AnyHttpUrl | None = None
    session_cookie_name: Literal["__Host-launchpad_session"] = "__Host-launchpad_session"
    session_cookie_secure: Literal[True] = True
    session_cookie_samesite: Literal["lax"] = "lax"
    session_idle_seconds: Literal[86400] = 86400
    session_absolute_seconds: Literal[604800] = 604800

    @field_validator("trusted_web_origins", mode="before")
    @classmethod
    def normalize_trusted_web_origins(cls, value: object) -> tuple[str, ...]:
        """Parse and canonicalize the explicit browser-origin allowlist."""

        if isinstance(value, str):
            entries: Sequence[object] = value.split(",")
        elif isinstance(value, (list, tuple)):
            entries = value
        else:
            raise ValueError("trusted web origins must be a comma-separated list")

        normalized: list[str] = []
        for entry in entries:
            if not isinstance(entry, str):
                raise ValueError("trusted web origins must be strings")
            candidate = entry.strip()
            if not candidate:
                raise ValueError("trusted web origins must not contain blank entries")
            parsed = urlsplit(candidate)
            try:
                port = parsed.port
            except ValueError as error:
                raise ValueError("trusted web origin has an invalid port") from error
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
                or (parsed.hostname and "*" in parsed.hostname)
            ):
                raise ValueError("trusted web origin is not an origin")
            host = parsed.hostname.lower()
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            canonical = f"{parsed.scheme.lower()}://{host}"
            if port is not None:
                canonical = f"{canonical}:{port}"
            if canonical not in normalized:
                normalized.append(canonical)
        return tuple(normalized)

    @model_validator(mode="after")
    def apply_or_validate_storage_credentials(self) -> Settings:
        """Use known local-only credentials or require explicitly separated credentials."""

        if self.environment == "development":
            if self.storage_access_key_id is None:
                self.storage_access_key_id = SecretStr("launchpad_development_minio_runtime")
            if self.storage_secret_access_key is None:
                self.storage_secret_access_key = SecretStr(
                    "launchpad_development_minio_runtime_password"
                )
            if self.bootstrap_storage_access_key_id is None:
                self.bootstrap_storage_access_key_id = SecretStr("launchpad_development_minio")
            if self.bootstrap_storage_secret_access_key is None:
                self.bootstrap_storage_secret_access_key = SecretStr(
                    "launchpad_development_minio_password"
                )

        runtime_fields = (self.storage_access_key_id, self.storage_secret_access_key)
        if any(value is None or not value.get_secret_value() for value in runtime_fields):
            raise ValueError("storage runtime credentials must be configured")

        bootstrap_fields = (
            self.bootstrap_storage_access_key_id,
            self.bootstrap_storage_secret_access_key,
        )
        if any(value is not None for value in bootstrap_fields) and any(
            value is None or not value.get_secret_value() for value in bootstrap_fields
        ):
            raise ValueError("storage bootstrap credentials must be supplied together")
        if (
            self.bootstrap_storage_access_key_id is not None
            and self.storage_access_key_id == self.bootstrap_storage_access_key_id
        ):
            raise ValueError("storage runtime and bootstrap access keys must be separate")

        if self.environment in {"development", "test", "check"}:
            if self.mail_web_origin is None:
                local_origin = (
                    "http://localhost:8080"
                    if self.environment == "development"
                    else "http://web:8080"
                )
                self.mail_web_origin = AnyHttpUrl(local_origin)
            if self.mail_sender is None:
                self.mail_sender = TypeAdapter(EmailStr).validate_python("noreply@example.com")
            if self.smtp_host is None:
                self.smtp_host = "mailpit"
            if self.smtp_port is None:
                self.smtp_port = 1025
            if self.smtp_use_tls is None:
                self.smtp_use_tls = False
            if self.outbox_key_id is None:
                self.outbox_key_id = "local-v1"
            if self.outbox_key is None:
                self.outbox_key = SecretStr("MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
            if self.public_upload_endpoint_url is None:
                local_upload_endpoint = (
                    "http://localhost:9000"
                    if self.environment == "development"
                    else "http://minio:9000"
                )
                self.public_upload_endpoint_url = AnyHttpUrl(local_upload_endpoint)

        return self


def load_settings(environment: Mapping[str, str] | None = None) -> Settings:
    """Load settings from an environment mapping with safe validation errors."""

    if environment is None:
        source: Mapping[str, str] = os.environ
    else:
        source = environment
    fields = {
        field_name: source[environment_name]
        for field_name in Settings.model_fields
        if (environment_name := f"LAUNCHPAD_{field_name.upper()}") in source
    }
    try:
        settings = Settings.model_validate(fields)
    except ValidationError as error:
        raise _configuration_error(error) from None
    _validate_identity_settings(settings)
    return settings


def _validate_identity_settings(settings: Settings) -> None:
    """Fail closed on missing/unsafe mail and encryption configuration without echoing values."""

    missing = [
        name
        for name, value in (
            ("LAUNCHPAD_MAIL_WEB_ORIGIN", settings.mail_web_origin),
            ("LAUNCHPAD_MAIL_SENDER", settings.mail_sender),
            ("LAUNCHPAD_SMTP_HOST", settings.smtp_host),
            ("LAUNCHPAD_SMTP_PORT", settings.smtp_port),
            ("LAUNCHPAD_SMTP_USE_TLS", settings.smtp_use_tls),
            ("LAUNCHPAD_OUTBOX_KEY_ID", settings.outbox_key_id),
            ("LAUNCHPAD_OUTBOX_KEY", settings.outbox_key),
            ("LAUNCHPAD_TRUSTED_WEB_ORIGINS", settings.trusted_web_origins),
            ("LAUNCHPAD_PUBLIC_UPLOAD_ENDPOINT_URL", settings.public_upload_endpoint_url),
        )
        if value is None or value == "" or value == ()
    ]
    if missing:
        raise ConfigurationError(f"Invalid configuration: {', '.join(missing)}")

    assert settings.mail_web_origin is not None
    assert settings.public_upload_endpoint_url is not None
    assert settings.outbox_key is not None
    assert settings.outbox_key_id is not None
    assert settings.smtp_host is not None

    for name, url in (
        ("LAUNCHPAD_MAIL_WEB_ORIGIN", settings.mail_web_origin),
        ("LAUNCHPAD_PUBLIC_UPLOAD_ENDPOINT_URL", settings.public_upload_endpoint_url),
    ):
        if url.path not in ("", "/") or url.query or url.fragment or url.username or url.password:
            raise ConfigurationError(f"Invalid configuration: {name}")
        if settings.environment == "production" and url.scheme != "https":
            raise ConfigurationError(f"Invalid configuration: {name}")

    try:
        key = b64decode(settings.outbox_key.get_secret_value(), validate=True)
    except (Base64Error, ValueError):
        key = b""
    if len(key) != 32:
        raise ConfigurationError("Invalid configuration: LAUNCHPAD_OUTBOX_KEY")
    if settings.environment == "production" and key in {b"0" * 32, b"1" * 32}:
        raise ConfigurationError("Invalid configuration: LAUNCHPAD_OUTBOX_KEY")
    if (
        not settings.outbox_key_id.isascii()
        or not settings.outbox_key_id.replace("-", "").isalnum()
    ):
        raise ConfigurationError("Invalid configuration: LAUNCHPAD_OUTBOX_KEY_ID")
    if settings.environment == "production" and not settings.smtp_use_tls:
        raise ConfigurationError("Invalid configuration: LAUNCHPAD_SMTP_USE_TLS")
    if settings.environment == "production" and settings.smtp_host == "mailpit":
        raise ConfigurationError("Invalid configuration: LAUNCHPAD_SMTP_HOST")
    if (settings.smtp_username is None) != (settings.smtp_password is None):
        raise ConfigurationError(
            "Invalid configuration: LAUNCHPAD_SMTP_USERNAME, LAUNCHPAD_SMTP_PASSWORD"
        )


def _configuration_error(error: ValidationError) -> ConfigurationError:
    """Translate Pydantic errors to a field-only message without values."""

    field_names = sorted(
        f"LAUNCHPAD_{location[0].upper()}"
        for issue in error.errors()
        if (location := issue["loc"]) and isinstance(location[0], str)
    )
    if not field_names:
        field_names = [
            "LAUNCHPAD_STORAGE_ACCESS_KEY_ID",
            "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY",
            "LAUNCHPAD_BOOTSTRAP_STORAGE_ACCESS_KEY_ID",
            "LAUNCHPAD_BOOTSTRAP_STORAGE_SECRET_ACCESS_KEY",
        ]
    return ConfigurationError(f"Invalid configuration: {', '.join(field_names)}")
