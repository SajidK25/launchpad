from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from scripts import validate_r2


class _Body:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def read(self, size: int = -1) -> bytes:
        return self.value[:size]

    def close(self) -> None:
        return None


class _Response:
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _S3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def head_bucket(self, **_: Any) -> None:
        return None

    def put_object(self, *, Key: str, Body: bytes, **_: Any) -> None:
        self.objects[Key] = Body

    def head_object(self, *, Key: str, **_: Any) -> dict[str, int]:
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, *, Key: str, **_: Any) -> dict[str, Any]:
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "GetObject",
            )
        return {"Body": _Body(self.objects[Key]), "ContentType": "image/png"}

    def delete_object(self, *, Key: str, **_: Any) -> None:
        self.deleted.append(Key)
        self.objects.pop(Key, None)


@pytest.fixture
def validation_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAUNCHPAD_R2_VALIDATION_ENABLED", "1")
    monkeypatch.setenv("LAUNCHPAD_R2_VALIDATION_BUCKET", "launchpad-validation")
    monkeypatch.setenv("LAUNCHPAD_R2_PRODUCTION_BUCKET", "launchpad-production-media")
    monkeypatch.setenv("LAUNCHPAD_R2_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("LAUNCHPAD_R2_ENDPOINT_URL", f"https://{'a' * 32}.r2.cloudflarestorage.com")
    monkeypatch.setenv("LAUNCHPAD_R2_ACCESS_KEY_ID", "validation-key")
    monkeypatch.setenv("LAUNCHPAD_R2_SECRET_ACCESS_KEY", "validation-secret")


def test_validation_requires_explicit_flag_and_refuses_production_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LAUNCHPAD_R2_VALIDATION_ENABLED", raising=False)
    with pytest.raises(validate_r2.ValidationConfigurationError):
        validate_r2.validate()

    monkeypatch.setenv("LAUNCHPAD_R2_VALIDATION_ENABLED", "1")
    monkeypatch.setenv("LAUNCHPAD_R2_VALIDATION_BUCKET", "launchpad-production-media")
    monkeypatch.setenv("LAUNCHPAD_R2_PRODUCTION_BUCKET", "launchpad-production-media")
    with pytest.raises(validate_r2.ValidationConfigurationError):
        validate_r2.validate()


@pytest.mark.parametrize("bucket", ["prod-media", "production-launchpad"])
def test_production_named_validation_target_is_refused(
    validation_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    bucket: str,
) -> None:
    monkeypatch.setenv("LAUNCHPAD_R2_VALIDATION_BUCKET", bucket)
    with pytest.raises(validate_r2.ValidationConfigurationError):
        validate_r2.validate()


def test_validation_only_proxies_finalizes_reads_and_deletes_generated_keys(
    validation_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _S3()

    def make_client(*_: Any, **__: Any) -> _S3:
        return client

    monkeypatch.setattr(validate_r2.boto3, "client", make_client)

    validate_r2.validate()

    assert len(client.deleted) == 2
    assert all(key.startswith(("profile-staging/", "profile-clean/")) for key in client.deleted)
    assert not client.objects


def test_validation_refuses_an_endpoint_for_a_different_account(
    validation_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAUNCHPAD_R2_ENDPOINT_URL", "https://different.r2.cloudflarestorage.com")

    with pytest.raises(validate_r2.ValidationConfigurationError):
        validate_r2.validate()


def test_explicit_validation_fails_when_protected_credentials_are_missing(
    validation_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LAUNCHPAD_R2_SECRET_ACCESS_KEY")

    with pytest.raises(validate_r2.ValidationConfigurationError):
        validate_r2.validate()
