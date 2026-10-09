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
            elif 'FROM product_assets' in joined:
                print(os.getenv('FAKE_REFERENCE_KEYS', ''))
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
            expected_repository = os.environ.get(
                'FAKE_EXPECTED_RESTIC_REPOSITORY', 's3:https://backup.invalid/db-repo'
            )
            if os.environ.get('RESTIC_REPOSITORY') != expected_repository:
                sys.exit(36)
            if os.environ.get('AWS_ACCESS_KEY_ID') != 'dedicated-backup-key':
                sys.exit(31)
            if os.environ.get('AWS_SECRET_ACCESS_KEY') != 'dedicated-backup-secret':
                sys.exit(32)
            if os.environ.get('LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY'):
                sys.exit(33)
            if os.environ.get('RCLONE_CONFIG_BACKUPMEDIA_SECRET_ACCESS_KEY'):
                sys.exit(47)
            if args[0] == 'backup':
                if os.getenv('FAKE_RESTIC_FAIL_BACKUP'):
                    sys.exit(34)
                root = os.environ['FAKE_ARCHIVE_DIR']
                os.makedirs(root, exist_ok=True)
                if 'media' in args:
                    index = 1
                    while os.path.exists(os.path.join(root, f'media.{index}')):
                        index += 1
                    dest = os.path.join(root, f'media.{index}')
                else:
                    dest = root
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

    rclone = bin_dir / "rclone"
    rclone.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import shutil
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            with open(os.environ['FAKE_RCLONE_LOG'], 'a') as log:
                log.write(json.dumps(args) + '\\n')
            if os.environ.get('RCLONE_CONFIG') != '/dev/null':
                sys.exit(40)
            if os.environ.get('RCLONE_CONFIG_BACKUPMEDIA_ACCESS_KEY_ID') != 'readonly-media-key':
                sys.exit(45)
            if os.environ.get('RCLONE_CONFIG_BACKUPMEDIA_SECRET_ACCESS_KEY') != (
                'readonly-media-secret'
            ):
                sys.exit(46)
            if args[0] == 'size':
                root = Path(os.environ['FAKE_MEDIA_SOURCE'])
                files = [path for path in root.rglob('*') if path.is_file()]
                print(json.dumps({'bytes': sum(path.stat().st_size for path in files),
                                  'count': len(files)}))
            elif args[0] == 'copy':
                if os.getenv('FAKE_RCLONE_FAIL_COPY'):
                    sys.exit(41)
                source = Path(os.environ['FAKE_MEDIA_SOURCE'])
                target = Path(args[-1])
                shutil.copytree(source, target, dirs_exist_ok=True)
            elif args[0] == 'check':
                if os.getenv('FAKE_RCLONE_FAIL_CHECK'):
                    sys.exit(42)
                source = Path(os.environ['FAKE_MEDIA_SOURCE'])
                target = Path(args[-2])
                for path in source.rglob('*'):
                    if path.is_file():
                        copied = (target / path.relative_to(source)).read_bytes()
                        if copied != path.read_bytes():
                            sys.exit(43)
            else:
                sys.exit(44)
            """
        )
    )
    rclone.chmod(0o755)

    fake_df = bin_dir / "df"
    fake_df.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "if 'FAKE_DF_FREE_KB' in os.environ:\n"
        " print('Filesystem 1024-blocks Used Available Capacity Mounted on')\n"
        " print('fake 100 0 ' + os.environ['FAKE_DF_FREE_KB'] + ' 0% /fake')\n"
        "else:\n"
        " os.execv('/bin/df', ['/bin/df', *sys.argv[1:]])\n"
    )
    fake_df.chmod(0o755)

    media_source = tmp_path / "media-source"
    media_source.mkdir()
    (media_source / "profile-clean" / ("a" * 32)).mkdir(parents=True)
    (media_source / "profile-clean" / ("a" * 32) / ("b" * 32)).write_bytes(b"profile-image")
    (media_source / "product-clean" / ("c" * 32) / ("d" * 32)).mkdir(parents=True)
    product_object = media_source / "product-clean" / ("c" * 32) / ("d" * 32) / ("e" * 32)
    product_object.write_bytes(b"product-image")

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
            "FAKE_RCLONE_LOG": str(tmp_path / "rclone-args.jsonl"),
            "FAKE_MEDIA_SOURCE": str(media_source),
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


def media_environment(backup_environment: dict[str, str]) -> dict[str, str]:
    backup_environment.update(
        {
            "LAUNCHPAD_BACKUP_MEDIA_REPOSITORY": "s3:https://backup.invalid/media-repo",
            "LAUNCHPAD_BACKUP_MEDIA_BUCKET": "launchpad-production-private",
            "LAUNCHPAD_BACKUP_MEDIA_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
            "LAUNCHPAD_BACKUP_MEDIA_ACCESS_KEY_ID": "readonly-media-key",
            "LAUNCHPAD_BACKUP_MEDIA_SECRET_ACCESS_KEY": "readonly-media-secret",
            "LAUNCHPAD_BACKUP_MEDIA_MAX_BYTES": "1048576",
            "FAKE_EXPECTED_RESTIC_REPOSITORY": "s3:https://backup.invalid/media-repo",
            "FAKE_REFERENCE_KEYS": (
                "profile-clean/"
                + "a" * 32
                + "/"
                + "b" * 32
                + "\nproduct-clean/"
                + "c" * 32
                + "/"
                + "d" * 32
                + "/"
                + "e" * 32
            ),
        }
    )
    return backup_environment


def test_media_snapshot_uses_read_only_configured_bucket_and_preserves_history(
    backup_environment: dict[str, str],
) -> None:
    env = media_environment(backup_environment)
    first = run_backup(env, "media", "weekly")
    assert first.returncode == 0, first.stdout + first.stderr
    assert "objects=2" in first.stdout
    first_snapshot = Path(env["FAKE_ARCHIVE_DIR"]) / "media.1"
    first_object = next(first_snapshot.glob("media.*/objects/profile-clean/*/*"))
    assert first_object.read_bytes() == b"profile-image"
    (Path(env["FAKE_MEDIA_SOURCE"]) / "profile-clean" / ("a" * 32) / ("b" * 32)).unlink()
    env["FAKE_REFERENCE_KEYS"] = "product-clean/" + "c" * 32 + "/" + "d" * 32 + "/" + "e" * 32

    second = run_backup(env, "media", "weekly")
    assert second.returncode == 0, second.stdout + second.stderr
    assert first_object.exists()
    calls = [json.loads(line) for line in Path(env["FAKE_RCLONE_LOG"]).read_text().splitlines()]
    assert all("backupmedia:launchpad-production-private" in call for call in calls)
    assert all("sync" not in call and "--delete" not in call for call in calls)
    assert all("backupmedia:backup-repo" not in " ".join(call) for call in calls)
    restic_calls = Path(env["FAKE_RESTIC_LOG"]).read_text().splitlines()
    assert restic_calls == ["backup", "forget", "backup", "forget"]


@pytest.mark.parametrize(
    ("override", "expected_message"),
    [
        ({"LAUNCHPAD_BACKUP_MEDIA_MAX_BYTES": "1"}, "exceeds the configured byte budget"),
        (
            {"FAKE_DF_FREE_KB": "1024", "LAUNCHPAD_BACKUP_MEDIA_MAX_BYTES": "1048576"},
            "Insufficient free space for bounded media staging",
        ),
        ({"LAUNCHPAD_BACKUP_MIN_FREE_BYTES": "999999999999999"}, "Insufficient free space"),
        ({"FAKE_RCLONE_FAIL_COPY": "1"}, "copy failed"),
        (
            {"FAKE_REFERENCE_KEYS": "profile-clean/" + "f" * 32 + "/" + "1" * 32},
            "referenced production media object is missing",
        ),
    ],
)
def test_media_pre_snapshot_failures_never_create_snapshot_or_prune(
    backup_environment: dict[str, str], override: dict[str, str], expected_message: str
) -> None:
    env = media_environment(backup_environment)
    env.update(override)

    result = run_backup(env, "media", "weekly")

    assert result.returncode != 0
    assert expected_message in result.stderr
    assert not Path(env["FAKE_RESTIC_LOG"]).exists()


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
