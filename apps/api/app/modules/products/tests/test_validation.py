"""Product content validation contracts."""

import pytest
from app.modules.products.schemas import ProductContentInput
from app.modules.products.service import ProductValidationError, validate_submission_content
from pydantic import ValidationError


def test_accepts_incomplete_draft_with_omitted_or_blank_optional_fields() -> None:
    content = ProductContentInput(name="   ", pitch=None, description="", website_url=None)

    assert content.name is None
    assert content.pitch is None
    assert content.description is None
    assert content.website_url is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "n" * 81),
        ("pitch", "p" * 161),
        ("pitch", "line one\nline two"),
        ("description", "d" * 5001),
        ("website_url", "https://"),
        ("website_url", "http://example.com"),
        ("website_url", "https://user:secret@example.com"),
    ],
)
def test_rejects_invalid_supplied_content_with_field_error(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as raised:
        ProductContentInput(**{field: value})

    assert raised.value.errors()[0]["loc"] == (field,)


def test_submission_completeness_reports_missing_and_whitespace_fields() -> None:
    content = ProductContentInput(name="A", pitch=" ", description=None, website_url=" ")

    with pytest.raises(ProductValidationError) as raised:
        validate_submission_content(content)

    assert raised.value.fields == ("pitch", "description", "website_url")
