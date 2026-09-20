"""Contracts for safe local runtime configuration."""

from __future__ import annotations

import pytest
from app.shared.config.settings import ConfigurationError, load_settings


def test_documented_local_defaults_need_no_external_credentials() -> None:
    """Local settings must be usable with only safe development defaults."""

    settings = load_settings({})

    assert settings.environment == "development"
    assert "@postgres:" in str(settings.database_url)
    assert settings.storage_endpoint_url.host == "minio"


def test_missing_runtime_credentials_outside_development_are_actionable_and_safe() -> None:
    """Production-like settings must not substitute local credentials or echo secret inputs."""

    with pytest.raises(ConfigurationError) as error:
        load_settings(
            {
                "LAUNCHPAD_ENVIRONMENT": "production",
                "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY": "T3_SECRET_SENTINEL",
            }
        )

    assert "LAUNCHPAD_STORAGE_ACCESS_KEY_ID" in str(error.value)
    assert "T3_SECRET_SENTINEL" not in str(error.value)


def test_runtime_credentials_never_fall_back_to_bootstrap_credentials() -> None:
    """Production-like runtime settings must stay separate from bootstrap access."""

    with pytest.raises(ConfigurationError) as error:
        load_settings(
            {
                "LAUNCHPAD_ENVIRONMENT": "test",
                "LAUNCHPAD_BOOTSTRAP_STORAGE_ACCESS_KEY_ID": "bootstrap-user",
                "LAUNCHPAD_BOOTSTRAP_STORAGE_SECRET_ACCESS_KEY": "T3_BOOTSTRAP_SECRET",
            }
        )

    assert "LAUNCHPAD_STORAGE_ACCESS_KEY_ID" in str(error.value)
    assert "T3_BOOTSTRAP_SECRET" not in str(error.value)


def test_invalid_database_url_names_the_variable_without_echoing_it() -> None:
    """Malformed configuration must be actionable without leaking its supplied value."""

    with pytest.raises(ConfigurationError) as error:
        load_settings({"LAUNCHPAD_DATABASE_URL": "not-a-url-T3_DATABASE_SECRET"})

    assert "LAUNCHPAD_DATABASE_URL" in str(error.value)
    assert "T3_DATABASE_SECRET" not in str(error.value)
