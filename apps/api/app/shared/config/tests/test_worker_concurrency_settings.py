"""Validation for bounded worker and mail delivery concurrency."""

from __future__ import annotations

import pytest
from app.shared.config.settings import ConfigurationError, load_settings


@pytest.mark.parametrize("name", ["WORKER_CONCURRENCY", "WORKER_EMAIL_CONCURRENCY"])
@pytest.mark.parametrize("value", ["0", "-1", "999"])
def test_worker_concurrency_rejects_out_of_range_values(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError) as error:
        load_settings({f"LAUNCHPAD_{name}": value})

    assert f"LAUNCHPAD_{name}" in str(error.value)
    assert value not in str(error.value)


def test_worker_concurrency_has_safe_bounded_defaults() -> None:
    settings = load_settings({"LAUNCHPAD_TRUSTED_WEB_ORIGINS": "http://localhost:8080"})

    assert settings.worker_concurrency == 16
    assert settings.worker_email_concurrency == 4
