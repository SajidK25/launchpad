from __future__ import annotations

import json
import os
import subprocess
import textwrap
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
    old_api_digest = "3" * 64
    old_web_digest = "4" * 64
    (state / "current-release.json").write_text(
        json.dumps(
            {
                "commit": "b" * 40,
                "schema_revision": "head_previous",
                "api_image": f"ghcr.io/sajidk25/launchpad-api@sha256:{old_api_digest}",
                "web_image": f"ghcr.io/sajidk25/launchpad-web@sha256:{old_web_digest}",
            }
        )
    )
    current_env = state / "current-release.env"
    current_env.write_text(
        f"LAUNCHPAD_API_DIGEST=sha256:{old_api_digest}\n"
        f"LAUNCHPAD_WEB_DIGEST=sha256:{old_web_digest}\n"
        f"LAUNCHPAD_STATE_DIR={state}\n"
    )
    (tmp_path / "compose.production.yaml").write_text("services: {}\n")
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps(valid_manifest()))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            joined = " ".join(args)
            with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as log:
                log.write(json.dumps(args) + "\\n")
            failure = os.getenv("FAKE_DOCKER_FAIL_MATCH")
            if failure and failure in joined:
                once = os.getenv("FAKE_DOCKER_FAIL_ONCE")
                if not once or not Path(once).exists():
                    if once:
                        Path(once).touch()
                    sys.exit(40)
            conflict = os.getenv("FAKE_DOCKER_CONFLICT_MATCH")
            if conflict and conflict in joined:
                if "inspect" in args:
                    print("foreign-project|wrong-resource")
                    sys.exit(0)
                sys.exit(46)
            if "volume" in args and "inspect" in args:
                logical = (
                    "postgres_data"
                    if "launchpad-production-postgres" in args
                    else "redis_data"
                )
                print(f"launchpad-production|{logical}")
            elif "network" in args and "inspect" in args:
                logical = (
                    "ingress"
                    if "_ingress" in args[-1]
                    else "host-publish"
                    if "_host-publish" in args[-1]
                    else "backend"
                )
                print(f"launchpad-production|{logical}")
            elif "ps" in args:
                if os.getenv("FAKE_FOREIGN_PROJECT_SERVICE"):
                    print(os.environ["FAKE_FOREIGN_PROJECT_SERVICE"])
                if os.getenv("FAKE_OWNED_WEB_PORT"):
                    print("127.0.0.1:18080->8080/tcp")
            marker = Path(os.environ["FAKE_MIGRATION_MARKER"])
            if "to_regclass" in joined:
                empty = os.getenv("FAKE_EMPTY_DATABASE") and not marker.exists()
                print("" if empty else "alembic_version")
            elif "version_num" in joined:
                key = "FAKE_SCHEMA_AFTER" if marker.exists() else "FAKE_SCHEMA_BEFORE"
                print(os.getenv(key, "head_20261009"))
            elif "run" in args and "migrate" in args:
                marker.write_text("migrated")
                if os.getenv("FAKE_MIGRATION_FAIL"):
                    sys.exit(41)
            elif "worker.py" in joined and "--health" in args:
                if os.getenv("FAKE_WORKER_FAIL"):
                    sys.exit(42)
            elif "scheduler.py" in joined and "--health" in args:
                if os.getenv("FAKE_SCHEDULER_FAIL"):
                    sys.exit(43)
            """
        )
    )
    docker.chmod(0o700)
    ss = bin_dir / "ss"
    ss.write_text(
        "#!/bin/sh\n"
        "[ -z \"$FAKE_PORT_CONFLICT\" ] || printf 'LISTEN 0 128 127.0.0.1:18080 0.0.0.0:*\\n'\n"
    )
    ss.chmod(0o700)
    stat = bin_dir / "stat"
    stat.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ] && [ "$2" = "%u" ] && '
        '[ "${4:-}" = "$FAKE_RUNTIME_POLICY" ]; then\n'
        "  printf '0\\n'\n"
        "  exit 0\n"
        "fi\n"
        'exec /usr/bin/stat "$@"\n'
    )
    stat.chmod(0o700)
    backup_env = tmp_path / "backup-database.env"
    backup_env.write_text(
        "LAUNCHPAD_BACKUP_DATABASE_REPOSITORY=s3:https://backup.example/db\n"
        "LAUNCHPAD_BACKUP_PASSWORD_FILE=/run/backup/password\n"
        "LAUNCHPAD_BACKUP_ACCESS_KEY_ID=backup-key\n"
        "LAUNCHPAD_BACKUP_SECRET_ACCESS_KEY=backup-secret-sentinel\n"
    )
    backup_env.chmod(0o600)
    backup_log = tmp_path / "backup.log"
    backup = bin_dir / "backup_production.sh"
    backup.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys

            with open(os.environ["FAKE_BACKUP_LOG"], "a", encoding="utf-8") as log:
                log.write(json.dumps(sys.argv[1:]) + "\\n")
            if os.getenv("LAUNCHPAD_BACKUP_SECRET_ACCESS_KEY") != "backup-secret-sentinel":
                sys.exit(44)
            if os.getenv("FAKE_BACKUP_FAIL"):
                sys.exit(45)
            print("[backup] snapshot=deadbeef01234567")
            """
        )
    )
    backup.chmod(0o700)
    curl = bin_dir / "curl"
    curl.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_CURL_LOG"\n'
        '[ -z "$FAKE_CURL_FAIL" ] || exit 22\n'
    )
    curl.chmod(0o700)
    marker = tmp_path / "migrated"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "LAUNCHPAD_PRODUCTION_STATE_DIR": str(state),
            "LAUNCHPAD_DEPLOY_LOCK_TIMEOUT_SECONDS": "1",
            "LAUNCHPAD_DEPLOY_MANIFEST": str(manifest),
            "LAUNCHPAD_PRODUCTION_COMPOSE_FILE": str(tmp_path / "compose.production.yaml"),
            "LAUNCHPAD_PRODUCTION_RELEASE_ENV": str(current_env),
            "LAUNCHPAD_PRODUCTION_RUNTIME_ENV_FILE": str(tmp_path / "runtime.env"),
            "LAUNCHPAD_DEPLOY_HEALTH_TIMEOUT_SECONDS": "2",
            "LAUNCHPAD_DEPLOY_DEPENDENCY_TIMEOUT_SECONDS": "10",
            "LAUNCHPAD_BACKUP_DATABASE_ENV_FILE": str(backup_env),
            "LAUNCHPAD_BACKUP_SCRIPT": str(backup),
            "LAUNCHPAD_DEPLOY_LOCAL_HEALTH_URL": "http://localhost/api/v1/health/ready",
            "LAUNCHPAD_DEPLOY_PUBLIC_HEALTH_URL": "https://launchpad.t99ltd.com/api/v1/health/ready",
            "FAKE_DOCKER_LOG": str(docker_log),
            "FAKE_CURL_LOG": str(tmp_path / "curl.log"),
            "FAKE_BACKUP_LOG": str(backup_log),
            "FAKE_MIGRATION_MARKER": str(marker),
            "FAKE_RUNTIME_POLICY": str(tmp_path / "runtime.env"),
            "FAKE_SCHEMA_BEFORE": "head_previous",
            "FAKE_SCHEMA_AFTER": "head_20261009",
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


def test_valid_manifest_rolls_out_and_persists_healthy_release(
    deploy_environment: dict[str, str],
) -> None:
    result = run_deploy(deploy_environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "release healthy" in result.stdout.lower()
    assert "manifest-test-secret-sentinel" not in result.stdout + result.stderr
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    attempt = json.loads((state_dir / "last-deployment.json").read_text())
    assert attempt["stage"] == "healthy"
    assert attempt["status"] == "success"
    assert attempt["commit"] == COMMIT
    assert attempt["workflow_run_id"] == 123456789
    assert attempt["schema_revision"] == "head_20261009"
    assert attempt["api_image"].endswith(API_DIGEST)
    assert attempt["web_image"].endswith(WEB_DIGEST)
    current = json.loads((state_dir / "current-release.json").read_text())
    assert current["commit"] == COMMIT
    assert current["schema_revision"] == "head_20261009"
    assert current["api_image"].endswith(API_DIGEST)
    assert current["web_image"].endswith(WEB_DIGEST)
    current_env = (state_dir / "current-release.env").read_text()
    assert "LAUNCHPAD_LAUNCHES_ENABLED=false\n" in current_env
    assert "LAUNCHPAD_DEMO_HOME_LATEST_LAUNCH_ENABLED=false\n" in current_env
    calls = [
        json.loads(line)
        for line in Path(deploy_environment["FAKE_DOCKER_LOG"]).read_text().splitlines()
    ]
    joined = [" ".join(call) for call in calls]
    assert next(
        i for i, call in enumerate(joined) if " stop api worker scheduler" in f" {call}"
    ) < next(i for i, call in enumerate(joined) if " run --rm --no-deps migrate" in f" {call}")
    assert any("worker.py --health" in call for call in joined)
    assert any("scheduler.py --health" in call for call in joined)


def test_valid_runtime_policy_persists_launch_enablement(
    deploy_environment: dict[str, str],
) -> None:
    runtime_env = Path(deploy_environment["LAUNCHPAD_PRODUCTION_RUNTIME_ENV_FILE"])
    runtime_env.write_text("LAUNCHPAD_LAUNCHES_ENABLED=true\n")
    runtime_env.chmod(0o640)

    result = run_deploy(deploy_environment)

    assert result.returncode == 0, result.stdout + result.stderr
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    release_env = state_dir / "releases" / f"{COMMIT}.env"
    assert "LAUNCHPAD_LAUNCHES_ENABLED=true\n" in release_env.read_text()
    assert "LAUNCHPAD_LAUNCHES_ENABLED=true\n" in (state_dir / "current-release.env").read_text()


def test_valid_runtime_policy_persists_demo_home_fallback(
    deploy_environment: dict[str, str],
) -> None:
    runtime_env = Path(deploy_environment["LAUNCHPAD_PRODUCTION_RUNTIME_ENV_FILE"])
    runtime_env.write_text(
        "LAUNCHPAD_LAUNCHES_ENABLED=true\nLAUNCHPAD_DEMO_HOME_LATEST_LAUNCH_ENABLED=true\n"
    )
    runtime_env.chmod(0o640)

    result = run_deploy(deploy_environment)

    assert result.returncode == 0, result.stdout + result.stderr
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    release_env = state_dir / "releases" / f"{COMMIT}.env"
    for path in (release_env, state_dir / "current-release.env"):
        content = path.read_text()
        assert "LAUNCHPAD_LAUNCHES_ENABLED=true\n" in content
        assert "LAUNCHPAD_DEMO_HOME_LATEST_LAUNCH_ENABLED=true\n" in content


@pytest.mark.parametrize(
    ("content", "mode"),
    [
        ("LAUNCHPAD_LAUNCHES_ENABLED=yes\n", 0o640),
        ("LAUNCHPAD_DEMO_HOME_LATEST_LAUNCH_ENABLED=yes\n", 0o640),
        ("LAUNCHPAD_UNKNOWN_FLAG=true\n", 0o640),
        ("LAUNCHPAD_LAUNCHES_ENABLED=true\n", 0o644),
    ],
)
def test_unsafe_runtime_policy_fails_before_docker(
    deploy_environment: dict[str, str], content: str, mode: int
) -> None:
    runtime_env = Path(deploy_environment["LAUNCHPAD_PRODUCTION_RUNTIME_ENV_FILE"])
    runtime_env.write_text(content)
    runtime_env.chmod(mode)

    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    assert "runtime policy" in result.stderr.lower()
    assert not Path(deploy_environment["FAKE_DOCKER_LOG"]).exists()
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    attempt = json.loads((state_dir / "last-deployment.json").read_text())
    assert attempt["stage"] == "validating_runtime_policy"


def test_runtime_policy_symlink_fails_before_docker(
    deploy_environment: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "runtime-target.env"
    target.write_text("LAUNCHPAD_LAUNCHES_ENABLED=true\n")
    target.chmod(0o640)
    runtime_env = Path(deploy_environment["LAUNCHPAD_PRODUCTION_RUNTIME_ENV_FILE"])
    runtime_env.symlink_to(target)

    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    assert "runtime policy" in result.stderr.lower()
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


def test_image_pull_failure_happens_before_maintenance_or_writers_stop(
    deploy_environment: dict[str, str],
) -> None:
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    original_current = (state_dir / "current-release.json").read_text()
    deploy_environment["FAKE_DOCKER_FAIL_MATCH"] = " pull "
    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    calls = Path(deploy_environment["FAKE_DOCKER_LOG"]).read_text().splitlines()
    assert any("pull" in call for call in calls)
    assert not (state_dir / "maintenance").exists()
    assert (state_dir / "current-release.json").read_text() == original_current
    attempt = json.loads((state_dir / "last-deployment.json").read_text())
    assert attempt["stage"] == "pulling_images", result.stdout + result.stderr
    assert attempt["status"] == "failed"


def test_foreign_volume_conflict_fails_preflight_before_image_pull_or_release_state(
    deploy_environment: dict[str, str],
) -> None:
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    deploy_environment["FAKE_DOCKER_CONFLICT_MATCH"] = "launchpad-production-postgres"
    result = run_deploy(deploy_environment)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "volume name is owned" in result.stderr
    calls = [
        " ".join(json.loads(line))
        for line in Path(deploy_environment["FAKE_DOCKER_LOG"]).read_text().splitlines()
    ]
    assert any("config --quiet" in call for call in calls)
    assert not any(" pull " in f" {call} " for call in calls)
    assert not (state_dir / "releases").exists()
    assert not (state_dir / "maintenance").exists()
    attempt = json.loads((state_dir / "last-deployment.json").read_text())
    assert attempt["stage"] == "preflight"


def test_unknown_service_using_production_compose_project_fails_before_mutation(
    deploy_environment: dict[str, str],
) -> None:
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    deploy_environment["FAKE_FOREIGN_PROJECT_SERVICE"] = "staging-api"
    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    assert "unknown service" in result.stderr
    calls = [
        " ".join(json.loads(line))
        for line in Path(deploy_environment["FAKE_DOCKER_LOG"]).read_text().splitlines()
    ]
    assert any("--all --filter" in call for call in calls)
    assert not any(" pull " in f" {call} " for call in calls)
    assert not (state_dir / "releases").exists()
    assert json.loads((state_dir / "last-deployment.json").read_text())["stage"] == "preflight"


def test_foreign_listener_on_production_web_port_fails_before_mutation(
    deploy_environment: dict[str, str],
) -> None:
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    deploy_environment["FAKE_PORT_CONFLICT"] = "1"
    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    assert "port is already occupied" in result.stderr
    calls = [
        " ".join(json.loads(line))
        for line in Path(deploy_environment["FAKE_DOCKER_LOG"]).read_text().splitlines()
    ]
    assert not any(" pull " in f" {call} " for call in calls)
    assert not (state_dir / "releases").exists()
    assert json.loads((state_dir / "last-deployment.json").read_text())["stage"] == "preflight"


def test_pre_migration_backup_failure_preserves_writers_and_schema(
    deploy_environment: dict[str, str],
) -> None:
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    deploy_environment["FAKE_BACKUP_FAIL"] = "1"
    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    calls = [
        " ".join(json.loads(line))
        for line in Path(deploy_environment["FAKE_DOCKER_LOG"]).read_text().splitlines()
    ]
    assert not any(" stop api worker scheduler" in f" {call}" for call in calls)
    assert not any(" run --rm --no-deps migrate" in f" {call}" for call in calls)
    assert not (state_dir / "maintenance").exists()
    attempt = json.loads((state_dir / "last-deployment.json").read_text())
    assert attempt["stage"] == "backing_up"
    assert attempt["status"] == "failed"


def test_migration_failure_with_unchanged_schema_restores_previous_images(
    deploy_environment: dict[str, str],
) -> None:
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    deploy_environment["FAKE_MIGRATION_FAIL"] = "1"
    deploy_environment["FAKE_SCHEMA_AFTER"] = "head_previous"
    runtime_env = Path(deploy_environment["LAUNCHPAD_PRODUCTION_RUNTIME_ENV_FILE"])
    runtime_env.write_text(
        "LAUNCHPAD_LAUNCHES_ENABLED=true\nLAUNCHPAD_DEMO_HOME_LATEST_LAUNCH_ENABLED=true\n"
    )
    runtime_env.chmod(0o640)
    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    assert not (state_dir / "maintenance").exists()
    assert json.loads((state_dir / "current-release.json").read_text())["commit"] == "b" * 40
    calls = [
        " ".join(json.loads(line))
        for line in Path(deploy_environment["FAKE_DOCKER_LOG"]).read_text().splitlines()
    ]
    assert any(
        "--env-file" in call and "b" * 40 in call and " up --detach --wait" in call
        for call in calls
    )
    restore_env = state_dir / "releases" / f"{'b' * 40}.env"
    assert "LAUNCHPAD_LAUNCHES_ENABLED=true\n" in restore_env.read_text()
    assert "LAUNCHPAD_DEMO_HOME_LATEST_LAUNCH_ENABLED=true\n" in restore_env.read_text()
    assert any("worker.py --health" in call for call in calls)
    attempt = json.loads((state_dir / "last-deployment.json").read_text())
    assert attempt["stage"] == "rolled_back"


def test_changed_schema_failure_keeps_maintenance_and_never_restores_old_images(
    deploy_environment: dict[str, str],
) -> None:
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    deploy_environment["FAKE_SCHEMA_AFTER"] = "head_unexpected"
    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    assert (state_dir / "maintenance").is_file()
    assert json.loads((state_dir / "current-release.json").read_text())["commit"] == "b" * 40
    calls = [
        " ".join(json.loads(line))
        for line in Path(deploy_environment["FAKE_DOCKER_LOG"]).read_text().splitlines()
    ]
    assert not any(
        "--env-file" in call and "b" * 40 in call and " up --detach --wait" in call
        for call in calls
    )
    attempt = json.loads((state_dir / "last-deployment.json").read_text())
    assert attempt["stage"] == "maintenance_recovery_required"


@pytest.mark.parametrize("failure_env", ["FAKE_WORKER_FAIL", "FAKE_SCHEDULER_FAIL"])
def test_fresh_process_health_failure_is_reported_and_attempts_schema_safe_recovery(
    deploy_environment: dict[str, str],
    failure_env: str,
) -> None:
    deploy_environment[failure_env] = "1"
    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    attempt = json.loads(
        (
            Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"]) / "last-deployment.json"
        ).read_text()
    )
    assert attempt["stage"] in {"rolled_back", "maintenance_recovery_required"}
    calls = [
        " ".join(json.loads(line))
        for line in Path(deploy_environment["FAKE_DOCKER_LOG"]).read_text().splitlines()
    ]
    assert any("worker.py --health" in call for call in calls)
    if failure_env == "FAKE_WORKER_FAIL":
        assert not any("scheduler.py --health" in call for call in calls)
    else:
        assert any("scheduler.py --health" in call for call in calls)


def test_failed_release_readiness_retries_both_origins_then_restores_previous_release(
    deploy_environment: dict[str, str],
) -> None:
    deploy_environment["FAKE_CURL_FAIL"] = "1"
    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    curl_calls = Path(deploy_environment["FAKE_CURL_LOG"]).read_text().splitlines()
    assert len(curl_calls) >= 2
    assert "localhost" in curl_calls[0]
    assert (Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"]) / "maintenance").is_file()
    attempt = json.loads(
        (
            Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"]) / "last-deployment.json"
        ).read_text()
    )
    assert attempt["stage"] == "maintenance_recovery_required"


def test_first_release_failure_leaves_maintenance_without_previous_release(
    deploy_environment: dict[str, str],
) -> None:
    state_dir = Path(deploy_environment["LAUNCHPAD_PRODUCTION_STATE_DIR"])
    (state_dir / "current-release.json").unlink()
    (state_dir / "current-release.env").unlink()
    deploy_environment["FAKE_EMPTY_DATABASE"] = "1"
    deploy_environment["FAKE_CURL_FAIL"] = "1"
    result = run_deploy(deploy_environment)

    assert result.returncode != 0
    assert (state_dir / "maintenance").is_file()
    assert not (state_dir / "current-release.json").exists()
    attempt = json.loads((state_dir / "last-deployment.json").read_text())
    assert attempt["stage"] == "maintenance_recovery_required"
