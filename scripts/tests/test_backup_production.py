from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/backup_production.sh"
COMMIT = "a" * 40


@pytest.fixture
def backup_environment(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    config_dir = tmp_path / "runtime-config"
    config_dir.mkdir()
    for name in (
        "postgres.env",
        "redis.env",
        "api.env",
        "worker.env",
        "scheduler.env",
        "migrate.env",
    ):
        config_file = config_dir / name
        config_file.write_text(f"{name}=protected-config-sentinel\n")
        config_file.chmod(0o600)
    (config_dir / "api.env").write_text("LAUNCHPAD_OUTBOX_KEY=outbox-recovery-key\n")
    (config_dir / "api.env").chmod(0o600)

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "current-release.json").write_text(
        json.dumps({"commit": COMMIT, "schema_revision": "head_20261009"})
    )
    password_file = tmp_path / "restic-password"
    password_file.write_text("test-only-restic-secret\n")
    password_file.chmod(0o600)
    (tmp_path / "compose.production.yaml").write_text("services: {}\n")
    (tmp_path / "release.env").write_text(
        "LAUNCHPAD_API_DIGEST=sha256:" + "a" * 64 + "\n"
        "LAUNCHPAD_WEB_DIGEST=sha256:" + "b" * 64 + "\n"
    )

    compose = bin_dir / "docker"
    compose.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys

            args = sys.argv[1:]
            with open(os.environ['FAKE_COMPOSE_LOG'], 'a') as log:
                log.write(' '.join(args) + '\\n')
            joined = ' '.join(args)
            if 'pg_dump --version' in joined:
                print('pg_dump (PostgreSQL) 17.4')
            elif 'SHOW server_version' in joined:
                print('17.11')
            elif 'FROM alembic_version' in joined:
                print(os.getenv('FAKE_SCHEMA_REVISION', 'head_20261009'))
            elif 'pg_dump ' in joined:
                if os.getenv('FAKE_PG_DUMP_FAIL'):
                    sys.exit(19)
                sys.stdout.buffer.write(b'PGDMP\\x01valid-test-dump')
            elif 'pg_restore --list' in joined:
                data = sys.stdin.buffer.read()
                if not data.startswith(b'PGDMP'):
                    sys.exit(20)
                print('Archive created at 2026-10-09')
            else:
                sys.exit(21)
            """
        )
    )
    compose.chmod(0o755)

    restic = bin_dir / "restic"
    restic.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import shutil
            import sys

            args = sys.argv[1:]
            with open(os.environ['FAKE_RESTIC_LOG'], 'a') as log:
                log.write(args[0] + '\\n')
            with open(os.environ['FAKE_RESTIC_ARGS_LOG'], 'a') as log:
                log.write(json.dumps(args) + '\\n')
            if not os.path.isfile(os.environ['RESTIC_PASSWORD_FILE']):
                sys.exit(30)
            if os.environ.get('RESTIC_REPOSITORY') != 's3:https://backup.invalid/db-repo':
                sys.exit(36)
            if os.environ.get('AWS_ACCESS_KEY_ID') != 'dedicated-backup-key':
                sys.exit(31)
            if os.environ.get('AWS_SECRET_ACCESS_KEY') != 'dedicated-backup-secret':
                sys.exit(32)
            if os.environ.get('LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY'):
                sys.exit(33)
            if args[0] == 'backup':
                if os.getenv('FAKE_RESTIC_FAIL_BACKUP'):
                    sys.exit(34)
                dest = os.environ['FAKE_ARCHIVE_DIR']
                os.makedirs(dest, exist_ok=True)
                for source in args:
                    if os.path.isfile(source):
                        shutil.copy2(source, os.path.join(dest, os.path.basename(source)))
                    elif os.path.isdir(source):
                        shutil.copytree(
                            source,
                            os.path.join(dest, os.path.basename(source)),
                            dirs_exist_ok=True,
                        )
                print(json.dumps({'message_type': 'summary', 'snapshot_id': 'deadbeef01234567'}))
            elif args[0] == 'forget':
                print('retention complete')
            else:
                sys.exit(35)
            """
        )
    )
    restic.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "LAUNCHPAD_BACKUP_DATABASE_REPOSITORY": "s3:https://backup.invalid/db-repo",
            "LAUNCHPAD_BACKUP_PASSWORD_FILE": str(tmp_path / "restic-password"),
            "LAUNCHPAD_BACKUP_ACCESS_KEY_ID": "dedicated-backup-key",
            "LAUNCHPAD_BACKUP_SECRET_ACCESS_KEY": "dedicated-backup-secret",
            "LAUNCHPAD_BACKUP_CONFIG_DIR": str(config_dir),
            "LAUNCHPAD_BACKUP_WORK_DIR": str(work_dir),
            "LAUNCHPAD_PRODUCTION_ROOT": str(tmp_path),
            "LAUNCHPAD_PRODUCTION_STATE_DIR": str(state_dir),
            "LAUNCHPAD_PRODUCTION_COMPOSE_FILE": str(tmp_path / "compose.production.yaml"),
            "LAUNCHPAD_PRODUCTION_RELEASE_ENV": str(tmp_path / "release.env"),
            "LAUNCHPAD_BACKUP_MIN_FREE_BYTES": "1",
            "FAKE_COMPOSE_LOG": str(tmp_path / "compose.log"),
            "FAKE_RESTIC_LOG": str(tmp_path / "restic.log"),
            "FAKE_RESTIC_ARGS_LOG": str(tmp_path / "restic-args.jsonl"),
            "FAKE_ARCHIVE_DIR": str(tmp_path / "restored-snapshot"),
            "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY": "runtime-storage-sentinel",
        }
    )
    return env


def run_backup(env: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("reason", ["weekly", "pre-migration"])
def test_database_snapshot_captures_encrypted_config_and_release_metadata(
    backup_environment: dict[str, str], reason: str
) -> None:
    result = run_backup(backup_environment, "database", reason)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "deadbeef01234567" in result.stdout
    assert "test-only-restic-secret" not in result.stdout + result.stderr
    assert "runtime-storage-sentinel" not in result.stdout + result.stderr
    archive = next(Path(backup_environment["FAKE_ARCHIVE_DIR"]).glob("database.*"))
    assert (archive / "database.dump").read_bytes().startswith(b"PGDMP")
    assert (archive / "configuration/api.env").read_text() == (
        "LAUNCHPAD_OUTBOX_KEY=outbox-recovery-key\n"
    )
    assert (archive / "configuration/compose.production.yaml").is_file()
    assert (archive / "configuration/release.env").is_file()
    metadata = json.loads((archive / "metadata.json").read_text())
    assert metadata["kind"] == "database"
    assert metadata["reason"] == reason
    assert metadata["database_version"] == "17.11"
    assert metadata["pg_dump_version"] == "17.4"
    assert metadata["schema_revision"] == "head_20261009"
    assert metadata["release_commit"] == COMMIT
    assert metadata["created_at"].endswith("+00:00")
    log_path = Path(backup_environment["FAKE_RESTIC_LOG"])
    commands = log_path.read_text().splitlines() if log_path.exists() else []
    assert commands == ["backup", "forget"]
    compose_calls = Path(backup_environment["FAKE_COMPOSE_LOG"]).read_text().splitlines()
    assert all("--project-name launchpad-production" in call for call in compose_calls)
    assert any("pg_restore --list" in call for call in compose_calls)
    restic_args = [
        json.loads(line)
        for line in Path(backup_environment["FAKE_RESTIC_ARGS_LOG"]).read_text().splitlines()
    ]
    assert restic_args[0][0] == "backup"
    assert "--tag" in restic_args[0] and reason in restic_args[0]
    assert restic_args[1] == [
        "forget",
        "--group-by",
        "host",
        "--tag",
        "database",
        "--keep-within",
        "30d",
        "--keep-last",
        "1",
        "--prune",
    ]


@pytest.mark.parametrize("failure_variable", ["FAKE_PG_DUMP_FAIL", "FAKE_RESTIC_FAIL_BACKUP"])
def test_failed_or_incomplete_database_backup_never_runs_retention(
    backup_environment: dict[str, str], failure_variable: str
) -> None:
    backup_environment[failure_variable] = "1"

    result = run_backup(backup_environment, "database", "weekly")

    assert result.returncode != 0
    assert "dedicated-backup-secret" not in result.stdout + result.stderr
    log_path = Path(backup_environment["FAKE_RESTIC_LOG"])
    commands = log_path.read_text().splitlines() if log_path.exists() else []
    assert "forget" not in commands


def test_database_backup_rejects_unsupported_reason_before_external_commands(
    backup_environment: dict[str, str],
) -> None:
    result = run_backup(backup_environment, "database", "manual")

    assert result.returncode != 0
    assert not Path(backup_environment["FAKE_COMPOSE_LOG"]).exists()
    assert not Path(backup_environment["FAKE_RESTIC_LOG"]).exists()


def test_database_backup_rejects_insufficient_disk_before_database_or_restic_access(
    backup_environment: dict[str, str],
) -> None:
    backup_environment["LAUNCHPAD_BACKUP_MIN_FREE_BYTES"] = "999999999999999"

    result = run_backup(backup_environment, "database", "weekly")

    assert result.returncode != 0
    assert "Insufficient free space" in result.stderr
    assert not Path(backup_environment["FAKE_COMPOSE_LOG"]).exists()
    assert not Path(backup_environment["FAKE_RESTIC_LOG"]).exists()


def test_database_backup_rejects_schema_mismatch_before_snapshot(
    backup_environment: dict[str, str],
) -> None:
    backup_environment["FAKE_SCHEMA_REVISION"] = "unrecognized_revision"

    result = run_backup(backup_environment, "database", "pre-migration")

    assert result.returncode != 0
    assert "does not match" in result.stderr
    assert not Path(backup_environment["FAKE_RESTIC_LOG"]).exists()


def test_database_backup_rejects_runtime_config_with_broad_permissions(
    backup_environment: dict[str, str],
) -> None:
    api_config = Path(backup_environment["LAUNCHPAD_BACKUP_CONFIG_DIR"]) / "api.env"
    api_config.chmod(0o644)

    result = run_backup(backup_environment, "database", "weekly")

    assert result.returncode != 0
    assert "accessible by group or others" in result.stderr
    assert not Path(backup_environment["FAKE_COMPOSE_LOG"]).exists()
    assert not Path(backup_environment["FAKE_RESTIC_LOG"]).exists()
