"""Contracts for safe local runtime configuration."""

from __future__ import annotations

import pytest
from app.shared.config.settings import ConfigurationError, load_settings


def test_documented_local_defaults_need_no_external_credentials() -> None:
    """Local settings must be usable with only safe development defaults."""

    settings = load_settings(
        {"LAUNCHPAD_TRUSTED_WEB_ORIGINS": "http://localhost:8080,http://127.0.0.1:8080"}
    )

    assert settings.environment == "development"
    assert settings.products_enabled is False
    assert "@postgres:" in str(settings.database_url)
    assert settings.storage_endpoint_url.host == "minio"
    assert settings.storage_provider == "minio"
    assert settings.storage_region == "us-east-1"
    assert settings.review_writes_enabled is True


def test_local_review_writes_can_be_disabled_independently() -> None:
    settings = load_settings(
        {
            "LAUNCHPAD_REVIEW_WRITES_ENABLED": "false",
            "LAUNCHPAD_PRODUCTS_ENABLED": "true",
            "LAUNCHPAD_TRUSTED_WEB_ORIGINS": "http://localhost:8080",
        }
    )

    assert settings.review_writes_enabled is False
    assert settings.products_enabled is True


def test_trusted_web_origins_parse_into_canonical_values() -> None:
    settings = load_settings(
        {"LAUNCHPAD_TRUSTED_WEB_ORIGINS": ("http://localhost:8080, http://127.0.0.1:8080")}
    )

    assert settings.trusted_web_origins == (
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    )


def test_trusted_web_origins_normalize_trailing_slash_and_deduplicate() -> None:
    settings = load_settings(
        {"LAUNCHPAD_TRUSTED_WEB_ORIGINS": ("http://localhost:8080/,http://localhost:8080")}
    )

    assert settings.trusted_web_origins == ("http://localhost:8080",)


def test_missing_trusted_web_origins_fails_closed() -> None:
    with pytest.raises(ConfigurationError) as error:
        load_settings({})

    assert "LAUNCHPAD_TRUSTED_WEB_ORIGINS" in str(error.value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://localhost:8080,",
        "http://user:pass@localhost:8080",
        "http://localhost:8080/path",
        "http://localhost:8080?debug=true",
        "http://localhost:8080#fragment",
        "http://*.localhost:8080",
        "ftp://localhost:8080",
        "http://localhost:not-a-port",
    ],
)
def test_malformed_trusted_web_origins_are_rejected_without_echoing_values(value: str) -> None:
    with pytest.raises(ConfigurationError) as error:
        load_settings({"LAUNCHPAD_TRUSTED_WEB_ORIGINS": value})

    assert "LAUNCHPAD_TRUSTED_WEB_ORIGINS" in str(error.value)
    if value:
        assert value not in str(error.value)


def test_production_does_not_inject_local_origins() -> None:
    settings = load_settings(
        {
            "LAUNCHPAD_ENVIRONMENT": "production",
            "LAUNCHPAD_STORAGE_PROVIDER": "r2",
            "LAUNCHPAD_STORAGE_REGION": "auto",
            "LAUNCHPAD_STORAGE_ENDPOINT_URL": "https://account123.r2.cloudflarestorage.com",
            "LAUNCHPAD_STORAGE_ACCESS_KEY_ID": "runtime-user",
            "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY": "runtime-secret",
            "LAUNCHPAD_MAIL_WEB_ORIGIN": "https://launchpad.example",
            "LAUNCHPAD_MAIL_SENDER": "noreply@launchpad.example",
            "LAUNCHPAD_SMTP_HOST": "smtp.example",
            "LAUNCHPAD_SMTP_PORT": "587",
            "LAUNCHPAD_SMTP_USE_TLS": "true",
            "LAUNCHPAD_OUTBOX_KEY_ID": "production-v1",
            "LAUNCHPAD_OUTBOX_KEY": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=",
            "LAUNCHPAD_PUBLIC_UPLOAD_ENDPOINT_URL": "https://uploads.example",
            "LAUNCHPAD_TRUSTED_WEB_ORIGINS": "https://launchpad.example",
        }
    )

    assert settings.trusted_web_origins == ("https://launchpad.example",)
    assert settings.storage_provider == "r2"
    assert settings.storage_region == "auto"
    assert settings.products_enabled is False
    assert settings.review_writes_enabled is False


def test_production_requires_explicit_r2_provider_region_and_endpoint() -> None:
    environment = {
        "LAUNCHPAD_ENVIRONMENT": "production",
        "LAUNCHPAD_STORAGE_PROVIDER": "r2",
        "LAUNCHPAD_STORAGE_REGION": "auto",
        "LAUNCHPAD_STORAGE_ENDPOINT_URL": "https://account123.r2.cloudflarestorage.com",
        "LAUNCHPAD_STORAGE_ACCESS_KEY_ID": "runtime-user",
        "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY": "runtime-secret",
        "LAUNCHPAD_MAIL_WEB_ORIGIN": "https://launchpad.example",
        "LAUNCHPAD_MAIL_SENDER": "noreply@launchpad.example",
        "LAUNCHPAD_SMTP_HOST": "smtp.example",
        "LAUNCHPAD_SMTP_PORT": "587",
        "LAUNCHPAD_SMTP_USE_TLS": "true",
        "LAUNCHPAD_OUTBOX_KEY_ID": "production-v1",
        "LAUNCHPAD_OUTBOX_KEY": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=",
        "LAUNCHPAD_PUBLIC_UPLOAD_ENDPOINT_URL": "https://uploads.example",
        "LAUNCHPAD_TRUSTED_WEB_ORIGINS": "https://launchpad.example",
    }

    invalid_storage = (
        (
            {
                key: value
                for key, value in environment.items()
                if key != "LAUNCHPAD_STORAGE_PROVIDER"
            },
            "LAUNCHPAD_STORAGE_PROVIDER",
        ),
        (
            {key: value for key, value in environment.items() if key != "LAUNCHPAD_STORAGE_REGION"},
            "LAUNCHPAD_STORAGE_REGION",
        ),
        (
            {
                key: value
                for key, value in environment.items()
                if key != "LAUNCHPAD_STORAGE_ENDPOINT_URL"
            },
            "LAUNCHPAD_STORAGE_ENDPOINT_URL",
        ),
        ({**environment, "LAUNCHPAD_STORAGE_PROVIDER": "minio"}, "LAUNCHPAD_STORAGE_PROVIDER"),
        ({**environment, "LAUNCHPAD_STORAGE_REGION": "us-east-1"}, "LAUNCHPAD_STORAGE_REGION"),
        (
            {
                **environment,
                "LAUNCHPAD_STORAGE_ENDPOINT_URL": "http://account123.r2.cloudflarestorage.com",
            },
            "LAUNCHPAD_STORAGE_ENDPOINT_URL",
        ),
        (
            {**environment, "LAUNCHPAD_STORAGE_ENDPOINT_URL": "https://uploads.example"},
            "LAUNCHPAD_STORAGE_ENDPOINT_URL",
        ),
    )
    for invalid_environment, field_name in invalid_storage:
        with pytest.raises(ConfigurationError, match=field_name) as error:
            load_settings(invalid_environment)
        assert "account123" not in str(error.value)


def test_production_worker_requires_resend_key_but_api_does_not() -> None:
    environment = {
        "LAUNCHPAD_ENVIRONMENT": "production",
        "LAUNCHPAD_STORAGE_PROVIDER": "r2",
        "LAUNCHPAD_STORAGE_REGION": "auto",
        "LAUNCHPAD_STORAGE_ENDPOINT_URL": "https://account123.r2.cloudflarestorage.com",
        "LAUNCHPAD_STORAGE_ACCESS_KEY_ID": "runtime-user",
        "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY": "runtime-secret",
        "LAUNCHPAD_MAIL_WEB_ORIGIN": "https://launchpad.example",
        "LAUNCHPAD_MAIL_SENDER": "noreply@launchpad.example",
        "LAUNCHPAD_OUTBOX_KEY_ID": "production-v1",
        "LAUNCHPAD_OUTBOX_KEY": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=",
        "LAUNCHPAD_PUBLIC_UPLOAD_ENDPOINT_URL": "https://uploads.example",
        "LAUNCHPAD_TRUSTED_WEB_ORIGINS": "https://launchpad.example",
    }

    api_settings = load_settings(environment)
    assert api_settings.resend_api_key is None

    with pytest.raises(ConfigurationError, match="LAUNCHPAD_RESEND_API_KEY"):
        load_settings(environment, require_worker_mail=True)

    worker_settings = load_settings(
        {**environment, "LAUNCHPAD_RESEND_API_KEY": "re_test_key"},
        require_worker_mail=True,
    )
    assert worker_settings.resend_api_key is not None


def test_production_resend_key_is_rejected_outside_worker_configuration() -> None:
    with pytest.raises(ConfigurationError, match="LAUNCHPAD_RESEND_API_KEY"):
        load_settings(
            {
                "LAUNCHPAD_ENVIRONMENT": "production",
                "LAUNCHPAD_STORAGE_PROVIDER": "r2",
                "LAUNCHPAD_STORAGE_REGION": "auto",
                "LAUNCHPAD_STORAGE_ENDPOINT_URL": "https://account123.r2.cloudflarestorage.com",
                "LAUNCHPAD_STORAGE_ACCESS_KEY_ID": "runtime-user",
                "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY": "runtime-secret",
                "LAUNCHPAD_MAIL_WEB_ORIGIN": "https://launchpad.example",
                "LAUNCHPAD_MAIL_SENDER": "noreply@launchpad.example",
                "LAUNCHPAD_OUTBOX_KEY_ID": "production-v1",
                "LAUNCHPAD_OUTBOX_KEY": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=",
                "LAUNCHPAD_PUBLIC_UPLOAD_ENDPOINT_URL": "https://uploads.example",
                "LAUNCHPAD_TRUSTED_WEB_ORIGINS": "https://launchpad.example",
                "LAUNCHPAD_RESEND_API_KEY": "re_test_key",
            }
        )


def test_production_worker_rejects_blank_resend_key_and_invalid_sender() -> None:
    base = {
        "LAUNCHPAD_ENVIRONMENT": "production",
        "LAUNCHPAD_STORAGE_PROVIDER": "r2",
        "LAUNCHPAD_STORAGE_REGION": "auto",
        "LAUNCHPAD_STORAGE_ENDPOINT_URL": "https://account123.r2.cloudflarestorage.com",
        "LAUNCHPAD_STORAGE_ACCESS_KEY_ID": "runtime-user",
        "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY": "runtime-secret",
        "LAUNCHPAD_MAIL_WEB_ORIGIN": "https://launchpad.example",
        "LAUNCHPAD_OUTBOX_KEY_ID": "production-v1",
        "LAUNCHPAD_OUTBOX_KEY": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=",
        "LAUNCHPAD_PUBLIC_UPLOAD_ENDPOINT_URL": "https://uploads.example",
        "LAUNCHPAD_TRUSTED_WEB_ORIGINS": "https://launchpad.example",
        "LAUNCHPAD_RESEND_API_KEY": " ",
    }

    with pytest.raises(ConfigurationError, match="LAUNCHPAD_RESEND_API_KEY"):
        load_settings(
            {**base, "LAUNCHPAD_MAIL_SENDER": "noreply@launchpad.example"},
            require_worker_mail=True,
        )
    with pytest.raises(ConfigurationError, match="LAUNCHPAD_RESEND_API_KEY"):
        load_settings(
            {
                **base,
                "LAUNCHPAD_RESEND_API_KEY": "invalid-key",
                "LAUNCHPAD_MAIL_SENDER": "noreply@launchpad.example",
            },
            require_worker_mail=True,
        )
    with pytest.raises(ConfigurationError, match="LAUNCHPAD_MAIL_SENDER"):
        load_settings(
            {
                **base,
                "LAUNCHPAD_RESEND_API_KEY": "re_test_key",
                "LAUNCHPAD_MAIL_SENDER": "invalid sender",
            },
            require_worker_mail=True,
        )


def test_products_feature_can_be_enabled_explicitly() -> None:
    settings = load_settings(
        {
            "LAUNCHPAD_PRODUCTS_ENABLED": "true",
            "LAUNCHPAD_TRUSTED_WEB_ORIGINS": "http://localhost:8080",
        }
    )

    assert settings.products_enabled is True


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


def test_isolated_check_environment_uses_its_explicit_credentials() -> None:
    """The quality Compose project must not inherit development defaults."""

    settings = load_settings(
        {
            "LAUNCHPAD_ENVIRONMENT": "check",
            "LAUNCHPAD_STORAGE_ACCESS_KEY_ID": "check-runtime",
            "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY": "check-runtime-secret",
            "LAUNCHPAD_BOOTSTRAP_STORAGE_ACCESS_KEY_ID": "check-bootstrap",
            "LAUNCHPAD_BOOTSTRAP_STORAGE_SECRET_ACCESS_KEY": "check-bootstrap-secret",
            "LAUNCHPAD_TRUSTED_WEB_ORIGINS": "http://web:8080",
        }
    )

    assert settings.environment == "check"
    assert settings.storage_access_key_id is not None
    assert settings.storage_access_key_id.get_secret_value() == "check-runtime"


def test_invalid_database_url_names_the_variable_without_echoing_it() -> None:
    """Malformed configuration must be actionable without leaking its supplied value."""

    with pytest.raises(ConfigurationError) as error:
        load_settings({"LAUNCHPAD_DATABASE_URL": "not-a-url-T3_DATABASE_SECRET"})

    assert "LAUNCHPAD_DATABASE_URL" in str(error.value)
    assert "T3_DATABASE_SECRET" not in str(error.value)
