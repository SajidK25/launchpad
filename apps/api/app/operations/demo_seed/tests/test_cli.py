"""Target safety checks run before any application dependency is opened."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.operations.demo_seed.cli import (
    DemoSeedTargetError,
    authorize_target,
    encode_credentials,
    parse_args,
    read_root_owned_marker,
    resolve_credentials,
)


def test_accepts_only_the_fixed_local_development_target() -> None:
    authorize_target(
        environment="development",
        target_id="local-development",
        confirm_no_customer_data=False,
    )
    with pytest.raises(DemoSeedTargetError, match="must be local-development"):
        authorize_target(
            environment="development",
            target_id="some-other-target",
            confirm_no_customer_data=True,
        )


@pytest.mark.parametrize("environment", ["production", "unknown"])
def test_rejects_unapproved_targets_before_reading_marker(environment: str) -> None:
    marker_reads: list[Path] = []

    def marker_reader(path: Path) -> str:
        marker_reads.append(path)
        raise DemoSeedTargetError("missing marker")

    with pytest.raises(DemoSeedTargetError):
        authorize_target(
            environment=environment,
            target_id="launchpad-demo-staging",
            confirm_no_customer_data=False,
            marker_reader=marker_reader,
        )
    assert marker_reads == []


def test_production_requires_matching_marker_and_explicit_attestation() -> None:
    calls: list[Path] = []

    def marker_reader(path: Path) -> str:
        calls.append(path)
        return "launchpad-demo-staging"

    with pytest.raises(DemoSeedTargetError, match="confirm"):
        authorize_target(
            environment="production",
            target_id="launchpad-demo-staging",
            confirm_no_customer_data=False,
            marker_reader=marker_reader,
        )
    assert calls == []
    authorize_target(
        environment="production",
        target_id="launchpad-demo-staging",
        confirm_no_customer_data=True,
        marker_reader=marker_reader,
    )
    assert len(calls) == 1
    with pytest.raises(DemoSeedTargetError, match="does not match"):
        authorize_target(
            environment="production",
            target_id="another-vm",
            confirm_no_customer_data=True,
            marker_reader=marker_reader,
        )


def test_marker_reader_fails_closed_for_missing_or_untrusted_files(tmp_path: Path) -> None:
    with pytest.raises(DemoSeedTargetError, match="unavailable"):
        read_root_owned_marker(tmp_path / "missing")
    marker = tmp_path / "marker"
    marker.write_text("launchpad-demo-staging\n", encoding="utf-8")
    marker.chmod(0o600)
    with pytest.raises(DemoSeedTargetError, match="not trusted"):
        read_root_owned_marker(marker)


def test_parser_requires_explicit_target_and_rotation_keys() -> None:
    assert parse_args(["seed", "--target-id", "local-development"]).command == "seed"
    with pytest.raises(SystemExit):
        parse_args(["cleanup"])
    rotate = parse_args(
        ["rotate-credentials", "--target-id", "local-development", "--account-key", "founder-01"]
    )
    assert rotate.account_key == ["founder-01"]


def test_credentials_are_unique_and_existing_passwords_remain_stable() -> None:
    keys = ["founder-01", "founder-02", "reviewer"]
    credentials, generated = resolve_credentials(keys)
    assert set(generated) == set(keys)
    assert len(set(credentials.values())) == len(keys)
    existing = encode_credentials(credentials)
    replay, replay_generated = resolve_credentials(keys, existing)
    assert replay == credentials
    assert replay_generated == {}
    partial, partial_new = resolve_credentials(
        keys, encode_credentials({"founder-01": credentials["founder-01"]})
    )
    assert partial["founder-01"] == credentials["founder-01"]
    assert set(partial_new) == {"founder-02", "reviewer"}


def test_credentials_reject_unknown_keys_and_malformed_input() -> None:
    with pytest.raises(ValueError, match="unknown account key"):
        resolve_credentials(["founder-01"], '{"founder-02":"a sufficiently long password"}')
    with pytest.raises(ValueError, match="invalid"):
        resolve_credentials(["founder-01"], "not-json")
