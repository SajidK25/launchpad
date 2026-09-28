"""Dedicated, repeatable local infrastructure preparation command."""

from __future__ import annotations

import asyncio
import os
import sys

from app.shared.config.settings import ConfigurationError, load_settings
from app.shared.db.database import Database, DatabasePreparationError
from app.shared.storage.provision import StorageProvisioner, StorageProvisioningError


async def prepare() -> None:
    """Validate configuration, then serialize database and private-storage preparation."""

    settings = load_settings()
    bootstrap_access_key_id = settings.bootstrap_storage_access_key_id
    bootstrap_secret_access_key = settings.bootstrap_storage_secret_access_key
    runtime_access_key_id = settings.storage_access_key_id
    runtime_secret_access_key = settings.storage_secret_access_key
    if (
        bootstrap_access_key_id is None
        or bootstrap_secret_access_key is None
        or runtime_access_key_id is None
        or runtime_secret_access_key is None
    ):
        raise ConfigurationError("Invalid configuration: storage credentials")
    database = Database.connect(str(settings.database_url))
    try:
        provisioner = StorageProvisioner(
            endpoint_url=str(settings.storage_endpoint_url),
            bootstrap_access_key_id=bootstrap_access_key_id.get_secret_value(),
            bootstrap_secret_access_key=bootstrap_secret_access_key.get_secret_value(),
            runtime_access_key_id=runtime_access_key_id.get_secret_value(),
            runtime_secret_access_key=runtime_secret_access_key.get_secret_value(),
            # The local MinIO image used by checks does not implement PutBucketCors;
            # production preparation must apply the exact configured web origin.
            upload_origin=(
                str(settings.mail_web_origin) if settings.environment == "production" else None
            ),
        )
        bucket_name = os.environ.get("LAUNCHPAD_STORAGE_BUCKET", "launchpad-private")
        await database.prepare_with(lambda: provisioner.prepare(bucket_name))
    finally:
        await database.close()


def main() -> None:
    """Exit nonzero with a safe diagnostic when preparation cannot complete."""

    try:
        asyncio.run(prepare())
    except (ConfigurationError, DatabasePreparationError, StorageProvisioningError) as error:
        print(f"Preparation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
