from typing import Any, cast

from app.shared.storage.provision import _configure_upload_cors, _runtime_policy


class _S3:
    def __init__(self) -> None:
        self.configuration: dict[str, Any] | None = None

    def put_bucket_cors(self, *, Bucket: str, CORSConfiguration: dict[str, Any]) -> None:
        self.configuration = CORSConfiguration


def test_upload_cors_is_exact_origin_and_post_only() -> None:
    client = _S3()
    _configure_upload_cors(client, "private", "https://launchpad.example")
    assert client.configuration == {
        "CORSRules": [
            {
                "AllowedOrigins": ["https://launchpad.example"],
                "AllowedMethods": ["POST"],
                "AllowedHeaders": ["Content-Type", "x-amz-*"],
                "MaxAgeSeconds": 300,
            }
        ]
    }


def test_runtime_policy_has_no_unbounded_bucket_listing() -> None:
    statements = cast(list[dict[str, object]], _runtime_policy("private")["Statement"])
    assert not any(
        "s3:ListBucket" in cast(list[str], statement["Action"]) for statement in statements
    )
