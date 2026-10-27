"""Contracts for the one-shot demo seed entry point."""

from __future__ import annotations

from app.operations.demo_seed.__main__ import _build_storage_probe
from app.shared.config.settings import Settings
from pydantic import AnyHttpUrl, SecretStr


def test_storage_probe_uses_configured_r2_provider_semantics() -> None:
    settings = Settings(
        storage_provider="r2",
        storage_region="auto",
        storage_endpoint_url=AnyHttpUrl("https://account.example.r2.cloudflarestorage.com"),
        storage_access_key_id=SecretStr("runtime-user"),
        storage_secret_access_key=SecretStr("runtime-secret"),
    )

    probe = _build_storage_probe(settings)

    assert probe.provider == "r2"
    assert probe.region_name == "auto"
