"""Compose declaration checks for preparation-gated consumers."""

from pathlib import Path


def test_check_consumer_waits_for_successful_preparation() -> None:
    """The disposable consumer must not start until preparation exits successfully."""

    compose = Path("compose.checks.yaml").read_text()
    consumer = compose.split("  gated-consumer:\n", 1)[1]
    assert "service_completed_successfully" in consumer
    assert "prepare:" in consumer
