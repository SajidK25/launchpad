"""Fail-closed command parsing and target authorization for demo seeding."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from app.operations.demo_seed.fixtures import (
    FOUNDER_FIXTURES,
    PRIVATE_PRODUCT_FIXTURES,
    PUBLIC_PRODUCT_FIXTURES,
    PrivateProductFixture,
    PublicProductFixture,
    fixture_asset_path,
)

LOCAL_TARGET_ID = "local-development"
DEFAULT_TARGET_MARKER = Path("/etc/launchpad/demo-seed-target")
_ACCOUNT_KEY = re.compile(r"^(?:founder-[0-9]{2}|reviewer)$")


class DemoSeedTargetError(RuntimeError):
    """A seed operation was directed at an unapproved target."""


def read_root_owned_marker(path: Path) -> str:
    """Read a root-owned, non-writable marker without following symlinks."""

    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise DemoSeedTargetError("demo target marker is unavailable") from error
    try:
        details = os.fstat(descriptor)
        if (
            details.st_uid != 0
            or not stat.S_ISREG(details.st_mode)
            or details.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise DemoSeedTargetError("demo target marker is not trusted")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as marker:
            target_id = marker.read(121).strip()
    finally:
        os.close(descriptor)
    if not target_id or len(target_id) > 120 or "\n" in target_id:
        raise DemoSeedTargetError("demo target marker is invalid")
    return target_id


def authorize_target(
    *,
    environment: str,
    target_id: str,
    confirm_no_customer_data: bool,
    marker_path: Path = DEFAULT_TARGET_MARKER,
    marker_reader: Callable[[Path], str] = read_root_owned_marker,
) -> None:
    """Authorize local development or the explicitly marked demo VM only."""

    if environment in {"development", "test", "check"}:
        if target_id != LOCAL_TARGET_ID:
            raise DemoSeedTargetError("development seed target must be local-development")
        return
    if environment != "production":
        raise DemoSeedTargetError("demo seeding is disabled for this environment")
    if target_id in {"", LOCAL_TARGET_ID} or len(target_id) > 120 or target_id != target_id.strip():
        raise DemoSeedTargetError("production demo target ID is invalid")
    if not confirm_no_customer_data:
        raise DemoSeedTargetError("confirm that the designated VM contains no customer data")
    if marker_reader(marker_path) != target_id:
        raise DemoSeedTargetError("target ID does not match the root-owned demo marker")


def build_parser() -> argparse.ArgumentParser:
    """Build the intentionally narrow operator command interface."""

    parser = argparse.ArgumentParser(prog="launchpad-demo-seed")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("seed", "cleanup", "rotate-credentials"):
        command = commands.add_parser(name)
        command.add_argument("--target-id", required=True)
        command.add_argument("--confirm-no-customer-data", action="store_true")
        if name == "rotate-credentials":
            command.add_argument("--account-key", action="append", required=True)
    return parser


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse operator arguments without opening application dependencies."""

    return build_parser().parse_args(arguments)


def resolve_credentials(
    account_keys: Sequence[str], existing_payload: str | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """Reuse saved passwords and generate unique random passwords for missing keys."""

    if len(account_keys) != len(set(account_keys)) or any(
        _ACCOUNT_KEY.fullmatch(key) is None for key in account_keys
    ):
        raise ValueError("credential account keys are invalid")
    existing: dict[str, str] = {}
    if existing_payload is not None:
        if len(existing_payload.encode("utf-8")) > 32_768:
            raise ValueError("credential input exceeds the allowed size")
        try:
            decoded = json.loads(existing_payload)
        except json.JSONDecodeError as error:
            raise ValueError("credential input is invalid") from error
        if not isinstance(decoded, dict) or any(
            not isinstance(key, str)
            or _ACCOUNT_KEY.fullmatch(key) is None
            or not isinstance(password, str)
            or len(password) < 24
            or len(password) > 256
            for key, password in decoded.items()
        ):
            raise ValueError("credential input is invalid")
        existing = decoded
    if set(existing) - set(account_keys):
        raise ValueError("credential input contains an unknown account key")
    credentials = dict(existing)
    generated: dict[str, str] = {}
    for key in account_keys:
        if key not in credentials:
            password = secrets.token_urlsafe(32)
            credentials[key] = password
            generated[key] = password
    return credentials, generated


def encode_credentials(credentials: Mapping[str, str]) -> str:
    """Serialize credentials deterministically for the host wrapper only."""

    return json.dumps(credentials, sort_keys=True, separators=(",", ":")) + "\n"


def load_fixture_media() -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Read the complete checked-in image bundle before opening write dependencies."""

    profile_media = {
        fixture.avatar_key: fixture_asset_path(fixture.avatar_key).read_bytes()
        for fixture in FOUNDER_FIXTURES
    }
    product_media: dict[str, bytes] = {}
    fixtures: tuple[PrivateProductFixture | PublicProductFixture, ...] = (
        *PRIVATE_PRODUCT_FIXTURES,
        *PUBLIC_PRODUCT_FIXTURES,
    )
    for fixture in fixtures:
        prefix = (
            f"private-{fixture.seed_key.removeprefix('product-private-')}"
            if fixture.seed_key.startswith("product-private-")
            else fixture.seed_key.removeprefix("product-")
        )
        for kind in ("logo", "screenshot"):
            key = f"{prefix}-{kind}"
            asset = fixture_asset_path(key)
            body = asset.read_bytes()
            if not 1 <= len(body) <= 5 * 1024 * 1024:
                raise ValueError("demo media fixture is outside the allowed size")
            product_media[key] = body
    for key, body in profile_media.items():
        if not 1 <= len(body) <= 5 * 1024 * 1024:
            raise ValueError("demo profile fixture is outside the allowed size")
    return profile_media, product_media
