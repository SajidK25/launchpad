from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_deployment_controller_uses_one_scoped_compose_project_and_no_global_cleanup() -> None:
    script = (ROOT / "scripts/deploy_production.sh").read_text()

    assert 'readonly project_name="launchpad-production"' in script
    assert 'docker compose --project-name "$project_name" --file "$compose_file"' in script
    assert " docker system prune" not in script
    assert "docker restart" not in script
    assert "down --volumes" not in script


def test_maintenance_marker_leaves_readiness_available_and_marks_503_responses() -> None:
    config = (ROOT / "infra/docker/web.production.conf").read_text()

    ready = config.split("location = /api/v1/health/ready", maxsplit=1)[1].split(
        "location ^~ /api/", maxsplit=1
    )[0]
    assert "proxy_pass $api_upstream" in ready
    assert "maintenance" not in ready
    assert "error_page 418 = @launchpad_maintenance" in config
    assert 'add_header Retry-After "60" always' in config
    assert 'add_header Cache-Control "no-store" always' in config
    assert config.count("return 418;") == 2


def test_rollout_has_backup_gate_fresh_health_checks_and_schema_guarded_recovery() -> None:
    script = (ROOT / "scripts/deploy_production.sh").read_text()

    assert '"$backup_script" database pre-migration || fail' in script
    assert '"${compose[@]}" stop api worker scheduler' in script
    assert '"${compose[@]}" run --rm --no-deps migrate' in script
    assert "apps/worker/worker.py --health" in script
    assert "apps/worker/scheduler.py --health" in script
    assert '[[ "$actual" == "$database_schema" ]]' in script
    assert 'rm -f -- "$state_dir/maintenance"' in script
    assert "pg_restore" not in script
