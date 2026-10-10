from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deploy_production.sh"
COMMIT = "a" * 40
API_DIGEST = "1" * 64
WEB_DIGEST = "2" * 64


def valid_manifest() -> dict[str, Any]:
    run_id = 123456789
    attempt = 2
    schema = "head_20261009"
    return {
        "manifest_version": 1,
        "repository": "SajidK25/launchpad",
        "commit": COMMIT,
        "release_id": f"{run_id}-{attempt}-{COMMIT}",
        "platform": "linux/amd64",
        "schema_revision": schema,
        "workflow": {
            "repository": "SajidK25/launchpad",
            "run_id": run_id,
            "run_attempt": attempt,
            "event": "push",
            "ref": "refs/heads/main",
            "head_sha": COMMIT,
            "conclusion": "success",
        },
        "verification": {"quality": "success", "images": "success"},
        "images": {
            "api": {
                "package": "ghcr.io/sajidk25/launchpad-api",
                "digest": f"sha256:{API_DIGEST}",
                "commit": COMMIT,
                "schema_revision": schema,
                "platform": "linux/amd64",
            },
            "web": {
                "package": "ghcr.io/sajidk25/launchpad-web",
                "digest": f"sha256:{WEB_DIGEST}",
                "commit": COMMIT,
                "schema_revision": schema,
                "platform": "linux/amd64",
            },
        },
    }


@pytest.fixture
def deploy_environment(tmp_path: Path) -> dict[str, str]:
    state = tmp_path / "state"
    state.mkdir()
    (state / "current-release.json").write_text(
        json.dumps({"commit": "b" * 40, "sentinel": "previous-success"})
    )
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps(valid_manifest()))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/sh\nprintf 'called\\n' >> \"$FAKE_DOCKER_LOG\"\nexit 99\n")
    docker.chmod(0o700)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "LAUNCHPAD_PRODUCTION_STATE_DIR": str(state),
            "LAUNCHPAD_DEPLOY_LOCK_TIMEOUT_SECONDS": "1",
            "LAUNCHPAD_DEPLOY_MANIFEST": str(manifest),
            "FAKE_DOCKER_LOG": str(docker_log),
            "LAUNCHPAD_TEST_SECRET": "manifest-test-secret-sentinel",
        }
    )
    return env


def run_deploy(
    env: dict[str, str], manifest_path: Path | None = None
) -> subprocess.CompletedProcess[str]:
    path = manifest_path or Path(env["LAUNCHPAD_DEPLOY_MANIFEST"])
    return subprocess.run(
        ["bash", str(SCRIPT), str(path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_manifest_version_must_be_an_integer_not_a_json_boolean_or_float(
    deploy_environment: dict[str, str],
) -> None:
    manifest_path = Path(deploy_environment["LAUNCHPAD_DEPLOY_MANIFEST"])
    manifest = valid_manifest()
    manifest["manifest_version"] = 1.0
    manifest_path.write_text(json.dumps(manifest))

    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    assert "Release manifest failed validation" in result.stderr
    assert not Path(deploy_environment["FAKE_DOCKER_LOG"]).exists()


def test_valid_verified_manifest_is_accepted_and_persisted_without_advancing_current_release(
    deploy_environment: dict[str, str],
) -> None:
    result = run_deploy(deploy_environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "manifest verified" in result.stdout.lower()
    assert "manifest-test-secret-sentinel" not in result.stdout + result.stderr
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    attempt = json.loads((state_dir / "last-deployment.json").read_text())
    assert attempt["stage"] == "verified"
    assert attempt["status"] == "verified"
    assert attempt["commit"] == COMMIT
    assert attempt["workflow_run_id"] == 123456789
    assert attempt["schema_revision"] == "head_20261009"
    assert attempt["api_image"].endswith(API_DIGEST)
    assert attempt["web_image"].endswith(WEB_DIGEST)
    assert json.loads((state_dir / "current-release.json").read_text()) == {
        "commit": "b" * 40,
        "sentinel": "previous-success",
    }
    assert not Path(deploy_environment["FAKE_DOCKER_LOG"]).exists()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("images.api.digest", "latest"),
        ("images.api.digest", "sha256:" + "a" * 63),
        ("images.api.package", "ghcr.io/other/launchpad-api"),
        ("platform", "linux/arm64"),
        ("schema_revision", "head; touch /tmp/manifest-injection"),
        ("repository", "SajidK25/launchpad; touch /tmp/manifest-injection"),
        ("manifest_version", True),
    ],
    ids=(
        "mutable-tag",
        "malformed-digest",
        "wrong-package",
        "wrong-platform",
        "schema-shell",
        "repo-shell",
        "boolean-version",
    ),
)
def test_unsafe_manifest_fields_fail_before_docker_and_persist_safe_failure_state(
    deploy_environment: dict[str, str], path: str, value: Any
) -> None:
    manifest_path = Path(deploy_environment["LAUNCHPAD_DEPLOY_MANIFEST"])
    manifest = valid_manifest()
    target: dict[str, Any] = manifest
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    manifest_path.write_text(json.dumps(manifest))

    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    assert "Release manifest failed validation" in result.stderr
    assert "manifest-test-secret-sentinel" not in result.stdout + result.stderr
    assert not Path(deploy_environment["FAKE_DOCKER_LOG"]).exists()
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    attempt = json.loads((state_dir / "last-deployment.json").read_text())
    assert attempt["stage"] == "validating_manifest"
    assert attempt["status"] == "failed"
    assert "manifest-test-secret-sentinel" not in json.dumps(attempt)
    assert json.loads((state_dir / "current-release.json").read_text())["commit"] == "b" * 40


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("workflow.head_sha", "c" * 40),
        ("release_id", "987654321-2-" + COMMIT),
        ("images.api.commit", "c" * 40),
        ("images.web.schema_revision", "different_revision"),
        ("images.api.platform", "linux/arm64"),
    ],
)
def test_divergent_workflow_release_and_image_identity_is_rejected(
    deploy_environment: dict[str, str], path: str, value: str
) -> None:
    manifest_path = Path(deploy_environment["LAUNCHPAD_DEPLOY_MANIFEST"])
    manifest = valid_manifest()
    target: dict[str, Any] = manifest
    for part in path.split(".")[:-1]:
        target = target[part]
    target[path.split(".")[-1]] = value
    manifest_path.write_text(json.dumps(manifest))

    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    assert "Release manifest failed validation" in result.stderr
    assert not Path(deploy_environment["FAKE_DOCKER_LOG"]).exists()


def test_lock_contention_does_not_mutate_deployment_state(
    deploy_environment: dict[str, str],
) -> None:
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    original_current = (state_dir / "current-release.json").read_text()
    lock_path = state_dir / "deployment.lock"
    lock_path.write_text("lock-marker\n")
    original_lock_mtime = lock_path.stat().st_mtime_ns
    holder = subprocess.Popen(["flock", "--exclusive", str(lock_path), "sleep", "2"])
    try:
        time.sleep(0.05)
        result = run_deploy(deploy_environment)
    finally:
        holder.wait(timeout=4)

    assert result.returncode != 0
    assert "shared operation lock" in result.stderr
    assert not (state_dir / "last-deployment.json").exists()
    assert (state_dir / "current-release.json").read_text() == original_current
    assert lock_path.read_text() == "lock-marker\n"
    assert lock_path.stat().st_mtime_ns == original_lock_mtime
    assert not Path(deploy_environment["FAKE_DOCKER_LOG"]).exists()
