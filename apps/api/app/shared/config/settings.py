"""Validated settings with safe local defaults and separate storage credentials."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    AnyUrl,
    BaseModel,
    ConfigDict,
    PostgresDsn,
    SecretStr,
    ValidationError,
    model_validator,
)


class ConfigurationError(ValueError):
    """Safe configuration error that names fields but never includes their values."""


class Settings(BaseModel):
    """Application settings loaded from `LAUNCHPAD_`-prefixed environment variables."""

    model_config = ConfigDict(extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
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

        required_fields = (
            self.storage_access_key_id,
            self.storage_secret_access_key,
            self.bootstrap_storage_access_key_id,
            self.bootstrap_storage_secret_access_key,
        )
        if any(value is None or not value.get_secret_value() for value in required_fields):
            raise ValueError("storage runtime and bootstrap credentials must be configured")

        if self.storage_access_key_id == self.bootstrap_storage_access_key_id:
            raise ValueError("storage runtime and bootstrap access keys must be separate")

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
        return Settings.model_validate(fields)
    except ValidationError as error:
        raise _configuration_error(error) from None


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
