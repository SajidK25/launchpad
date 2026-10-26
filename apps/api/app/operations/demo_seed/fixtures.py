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


@dataclass(frozen=True, slots=True)
class PublicProductFixture:
    """One launched catalog example with its stable archive-day offset."""

    seed_key: str
    founder_key: str
    name: str
    pitch: str
    description: str
    website_url: str
    topics: tuple[str, ...]
    day_offset: int


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

_PUBLIC_PRODUCTS = (
    ("Brightpath", "A simple map for better team habits", ("Productivity", "Business")),
    ("Morrow", "Turn reading notes into useful ideas", ("Education", "Writing")),
    ("Pebble Plan", "Keep small projects moving", ("Productivity", "Design")),
    ("Signal Grove", "Understand customer feedback faster", ("Analytics", "Business")),
    ("Open Lantern", "A clearer way to share research", ("Research", "Education")),
    ("Tempo Garden", "Make room for focused work", ("Productivity", "Health")),
    ("Copper Kite", "Plan creative work with confidence", ("Design", "Business")),
    ("Common Thread", "Keep community projects connected", ("Community", "Productivity")),
    ("Paper Current", "Write useful updates in less time", ("Writing", "Productivity")),
    ("Northstar Notes", "A lightweight research notebook", ("Research", "Education")),
    ("Good Orchard", "Organize recurring customer work", ("Business", "Analytics")),
    ("Soft Signal", "Find patterns in product conversations", ("Analytics", "Research")),
    ("Blue Heron", "Bring calm to shared calendars", ("Productivity", "Community")),
    ("Mosaic Route", "Coordinate work across small teams", ("Business", "Productivity")),
    ("Lumen Desk", "A gentle home for creative planning", ("Design", "Writing")),
    ("Kindred Map", "Help local groups plan together", ("Community", "Education")),
    ("Clover Index", "Collect and revisit useful references", ("Research", "Productivity")),
    ("Amber Draft", "Make publishing feel more manageable", ("Writing", "Design")),
    ("Tandem Field", "Track experiments with a small team", ("Analytics", "Business")),
    ("Willow Works", "A shared workspace for independent makers", ("Community", "Design")),
)

PUBLIC_PRODUCT_FIXTURES = tuple(
    PublicProductFixture(
        seed_key=f"product-launched-{index:02d}",
        founder_key=f"founder-{index:02d}",
        name=name,
        pitch=pitch,
        description=f"{name} is a fictional Launchpad demo product. {pitch}. "
        "It helps independent teams make steady progress with a focused, approachable workflow.",
        website_url=f"https://{name.lower().replace(' ', '-')}.demo.launchpad.example",
        topics=topics,
        day_offset=(index - 1) % 8,
    )
    for index, (name, pitch, topics) in enumerate(_PUBLIC_PRODUCTS, start=1)
)


def fixture_asset_path(name: str) -> Path:
    """Resolve a checked-in fixture path without exposing arbitrary paths."""

    if name not in {"logo", "screenshot"}:
        raise ValueError("unknown product fixture asset")
    return Path(__file__).with_name("assets") / "products" / f"demo-{name}.png"
