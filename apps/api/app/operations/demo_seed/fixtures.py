"""Stable fictional product examples used by the stakeholder seed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PrivateProductFixture:
    """One private workflow example with fictional copy and local media paths."""

    seed_key: str
    founder_key: str
    name: str
    pitch: str
    description: str
    website_url: str
    topics: tuple[str, ...]
    outcome: str | None
    feedback: str | None = None
    schedule: bool = False
    submit: bool = False


PRIVATE_PRODUCT_FIXTURES = (
    PrivateProductFixture(
        "product-private-draft",
        "founder-01",
        "Draftboard",
        "A calmer project handoff",
        "Draftboard keeps project handoffs organized for small creative teams.",
        "https://draftboard.demo.launchpad.example",
        ("Productivity", "Design"),
        None,
    ),
    PrivateProductFixture(
        "product-private-submitted",
        "founder-02",
        "Fieldnote",
        "Research notes that stay useful",
        "Fieldnote turns interview notes into clear, searchable research summaries.",
        "https://fieldnote.demo.launchpad.example",
        ("Research", "Productivity"),
        None,
        submit=True,
    ),
    PrivateProductFixture(
        "product-private-changes-requested",
        "founder-03",
        "Patchwork",
        "Small fixes, one clear queue",
        "Patchwork helps teams collect and prioritize maintenance work.",
        "https://patchwork.demo.launchpad.example",
        ("Developer tools",),
        "changes_requested",
        "Clarify who benefits most and add one concrete example.",
    ),
    PrivateProductFixture(
        "product-private-rejected",
        "founder-04",
        "Quietframe",
        "A focused space for planning",
        "Quietframe is a fictional planning workspace for independent teams.",
        "https://quietframe.demo.launchpad.example",
        ("Productivity",),
        "rejected",
        "This example needs a clearer original use case before resubmission.",
    ),
    PrivateProductFixture(
        "product-private-approved",
        "founder-05",
        "Cedar Metrics",
        "Simple metrics for makers",
        "Cedar Metrics presents a small set of product signals in one readable view.",
        "https://cedarmetrics.demo.launchpad.example",
        ("Analytics",),
        "approved",
    ),
    PrivateProductFixture(
        "product-private-scheduled",
        "founder-06",
        "Orbit Ledger",
        "A clearer view of recurring work",
        "Orbit Ledger helps small studios track recurring client work and delivery dates.",
        "https://orbitledger.demo.launchpad.example",
        ("Business", "Productivity"),
        "approved",
        schedule=True,
    ),
)


def fixture_asset_path(name: str) -> Path:
    """Resolve a checked-in fixture path without exposing arbitrary paths."""

    if name not in {"logo", "screenshot"}:
        raise ValueError("unknown product fixture asset")
    return Path(__file__).with_name("assets") / "products" / f"demo-{name}.png"
