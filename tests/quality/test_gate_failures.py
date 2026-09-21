"""Failure propagation checks for the shared quality gate."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _run(script: str, **environment: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        env=os.environ | environment,
        text=True,
    )


def test_gate_reports_and_propagates_a_controlled_category_failure() -> None:
    result = _run("scripts/quality/run.sh", LAUNCHPAD_QUALITY_ONLY="controlled-failure")

    assert result.returncode != 0
    assert "controlled-failure" in result.stdout + result.stderr


def test_scanner_errors_and_blocking_findings_never_pass() -> None:
    for mode in ("unavailable", "secret", "high"):
        result = _run("scripts/quality/security.sh", LAUNCHPAD_SECURITY_MODE=mode)
        assert result.returncode != 0
        assert mode in result.stdout + result.stderr


def test_lower_severity_scanner_result_remains_visible_without_blocking() -> None:
    result = _run("scripts/quality/security.sh", LAUNCHPAD_SECURITY_MODE="low")

    assert result.returncode == 0
    assert "low-severity" in result.stdout


def test_local_and_ci_share_the_same_quality_orchestrator() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text()
    gate = (ROOT / "scripts/quality/run.sh").read_text()

    assert "sh scripts/quality/run.sh" in workflow
    assert "compose.checks.yaml" in gate


def test_security_scan_uses_the_built_project_image_without_a_running_web_container() -> None:
    scanner = (ROOT / "scripts/quality/security.sh").read_text()

    assert "docker image inspect --format" in scanner
    assert '"${project}-web"' in scanner
    assert "compose images -q web" not in scanner
