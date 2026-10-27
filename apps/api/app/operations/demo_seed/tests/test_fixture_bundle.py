"""The checked-in stakeholder demo image bundle is complete and production-safe."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.operations.demo_seed.cli import load_fixture_media
from app.operations.demo_seed.fixtures import fixture_asset_path
from app.shared.storage.objects import _validate_and_reencode


def test_fixture_bundle_is_complete_distinct_and_accepted_by_storage_validator() -> None:
    profile_media, product_media = load_fixture_media()

    assert len(profile_media) == 20
    assert len(product_media) == 52
    bodies = [*profile_media.values(), *product_media.values()]
    assert len({hashlib.sha256(body).digest() for body in bodies}) == 72

    for body in bodies:
        content_type, cleaned = _validate_and_reencode(body, 5 * 1024 * 1024)
        assert content_type == "image/png"
        assert 0 < len(cleaned) <= 5 * 1024 * 1024


def test_fixture_manifest_covers_exactly_the_checked_in_images() -> None:
    manifest_path = Path(__file__).parents[1] / "assets" / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest["assets"]
    assert manifest["version"] == 1
    assert "user-authorized" in manifest["generator"]
    assert len(entries) == 72

    listed = [entry["file"] for entry in entries]
    assert len(set(listed)) == 72
    assert all(isinstance(entry["prompt"], str) and entry["prompt"] for entry in entries)
    expected_keys = [
        *(f"avatar-{index:02d}" for index in range(1, 21)),
        *(
            f"launched-{index:02d}-{kind}"
            for index in range(1, 21)
            for kind in ("logo", "screenshot")
        ),
        *(
            f"private-{state}-{kind}"
            for state in (
                "draft",
                "submitted",
                "changes-requested",
                "rejected",
                "approved",
                "scheduled",
            )
            for kind in ("logo", "screenshot")
        ),
    ]
    expected = {
        str(fixture_asset_path(key).relative_to(Path(__file__).parents[1] / "assets"))
        for key in expected_keys
    }
    assert set(listed) == expected
