"""Worker/scheduler process health contracts."""

import sys
from pathlib import Path
from time import monotonic

sys.path.insert(0, "apps/worker")

from health import ProgressHealth, progress_is_fresh, record_progress


def test_progress_health_requires_recent_loop_progress() -> None:
    dependency_available = True
    health = ProgressHealth(
        freshness_seconds=1,
        connections=(lambda: dependency_available,),
    )
    assert health.healthy() is False
    health.tick()
    assert health.healthy() is True

    health.last_progress = monotonic() - 2
    assert health.healthy() is False

    health.tick()
    dependency_available = False
    assert health.healthy() is False


def test_progress_file_recovers_when_the_loop_resumes(tmp_path: Path) -> None:
    progress_path = tmp_path / "worker.progress"
    assert progress_is_fresh(progress_path, freshness_seconds=1) is False

    record_progress(progress_path)
    assert progress_is_fresh(progress_path, freshness_seconds=1) is True

    progress_path.write_text("0")
    assert progress_is_fresh(progress_path, freshness_seconds=1) is False


def test_compose_gates_background_processes_on_preparation() -> None:
    for compose_file in ("compose.yaml", "compose.checks.yaml"):
        compose = Path(compose_file).read_text()
        assert "  worker:" in compose
        assert "  scheduler:" in compose
        assert compose.count("service_completed_successfully") >= 3
        assert compose.count('"--health"') >= 2
        api_definition = compose.split("  api:\n", maxsplit=1)[1].split("\n  worker:", maxsplit=1)[
            0
        ]
        assert "    depends_on:\n      prepare:" in api_definition
        assert "worker" not in api_definition
        assert "scheduler" not in api_definition


def test_background_entry_points_do_not_register_product_work() -> None:
    for entry_point in (Path("apps/worker/worker.py"), Path("apps/worker/scheduler.py")):
        assert "@dramatiq.actor" not in entry_point.read_text()
