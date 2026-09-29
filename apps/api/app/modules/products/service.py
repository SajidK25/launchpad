"""Product content rules that are independent of transport and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

from app.modules.products.schemas import ProductContentInput
from pydantic import ValidationError


class ProductValidationError(ValueError):
    """A product field or set of fields is invalid for the requested operation."""

    def __init__(self, message: str, *, fields: tuple[str, ...]) -> None:
        super().__init__(message)
        self.fields = fields


@dataclass(frozen=True, slots=True)
class TopicLabel:
    """A founder's own spelling paired with its private canonical topic key."""

    display_name: str
    name_key: str


def validate_submission_content(content: ProductContentInput) -> ProductContentInput:
    """Require all text and website fields before a draft can be submitted."""

    missing = tuple(
        field
        for field in ("name", "pitch", "description", "website_url")
        if getattr(content, field) is None
    )
    if missing:
        raise ProductValidationError("submission content is incomplete", fields=missing)
    return content


def validate_topic_names(names: list[str]) -> list[TopicLabel]:
    """Trim, bound, and de-duplicate founder topic choices without leaking canonical casing."""

    if not 1 <= len(names) <= 3:
        raise ProductValidationError("choose between one and three topics", fields=("topics",))
    labels: list[TopicLabel] = []
    seen: set[str] = set()
    for name in names:
        display_name = name.strip()
        name_key = display_name.casefold()
        if not display_name or len(display_name) > 40:
            raise ProductValidationError(
                "topic must contain 1 to 40 characters", fields=("topics",)
            )
        if name_key in seen:
            raise ProductValidationError("topic choices must be unique", fields=("topics",))
        seen.add(name_key)
        labels.append(TopicLabel(display_name=display_name, name_key=name_key))
    return labels


def canonical_website_key(value: str) -> str:
    """Normalize only URL components that do not identify a different website link."""

    try:
        content = ProductContentInput(website_url=value)
    except ValidationError as exc:
        raise ProductValidationError(
            "website_url must be a valid HTTPS URL", fields=("website_url",)
        ) from exc
    if content.website_url is None:
        raise ProductValidationError(
            "website_url must be a valid HTTPS URL", fields=("website_url",)
        )
    try:
        parsed = urlsplit(content.website_url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ProductValidationError(
            "website_url must be a valid HTTPS URL", fields=("website_url",)
        ) from exc
    if (
        parsed.scheme.casefold() != "https"
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in value)
    ):
        raise ProductValidationError(
            "website_url must be a valid HTTPS URL", fields=("website_url",)
        )
    normalized_port = f":{port}" if port is not None and port != 443 else ""
    normalized_host = f"[{host.casefold()}]" if ":" in host else host.casefold()
    netloc = normalized_host + normalized_port
    path = "" if parsed.path in ("", "/") else parsed.path
    return _replace_url(parsed, netloc=netloc, path=path, query=parsed.query, fragment="").geturl()


def canonical_topic_key(value: str) -> str:
    """Return the trimmed, case-folded key used for equivalent topic names."""

    return value.strip().casefold()


def _replace_url(
    parsed: SplitResult, *, netloc: str, path: str, query: str, fragment: str
) -> SplitResult:
    return parsed._replace(netloc=netloc, path=path, query=query, fragment=fragment)
