"""Submission completeness rules independent of database transports."""

import pytest
from app.modules.products.schemas import ProductContentInput
from app.modules.products.service import ProductValidationError, validate_submission_content


@pytest.mark.parametrize(
    ("values", "missing"),
    [
        ({}, {"name", "pitch", "description", "website_url"}),
        ({"name": "Name"}, {"pitch", "description", "website_url"}),
        (
            {"name": "Name", "pitch": "Pitch", "description": "Description"},
            {"website_url"},
        ),
    ],
)
def test_submission_content_reports_every_missing_required_field(
    values: dict[str, str], missing: set[str]
) -> None:
    with pytest.raises(ProductValidationError) as raised:
        validate_submission_content(ProductContentInput(**values))

    assert set(raised.value.fields) == missing


def test_submission_content_accepts_complete_https_product() -> None:
    content = ProductContentInput(
        name="Name",
        pitch="Pitch",
        description="Description",
        website_url="https://example.test",
    )

    assert validate_submission_content(content) is content
