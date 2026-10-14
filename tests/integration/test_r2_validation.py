from __future__ import annotations

import os

import pytest

from scripts.validate_r2 import validate

pytestmark = pytest.mark.skipif(
    os.environ.get("LAUNCHPAD_R2_VALIDATION_ENABLED") != "1",
    reason="R2 checks run only from the protected validation workflow",
)


def test_private_r2_signed_staging_promotion_read_delete_and_health_probe() -> None:
    validate()
