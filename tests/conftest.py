"""Pytest fixtures."""

from datetime import datetime

import pytest

from real_deal.models import Listing


@pytest.fixture
def mock_listing() -> Listing:
    """Single mock listing for underwriting tests."""
    return Listing(
        id="test-1",
        source="mock",
        address="123 Main St",
        city="Windsor",
        province="ON",
        postal_code="N9A 1A1",
        price=399000,
        bedrooms=4,
        bathrooms=2,
        property_type="Duplex",
        description="Legal duplex with separate entrance. Upper rents for $1800, lower for $1600.",
        url="https://example.com/1",
        raw_payload={},
    )


@pytest.fixture
def mock_listings() -> list[Listing]:
    """Multiple mock listings for batch underwriting tests."""
    return [
        Listing(
            id="mock-1",
            source="mock",
            address="123 Main St",
            city="Windsor",
            province="ON",
            postal_code="N9A 1A1",
            price=399000,
            bedrooms=4,
            bathrooms=2,
            property_type="Duplex",
            description="Legal duplex. Rent: $3400 total.",
            url="https://example.com/1",
            raw_payload={},
        ),
        Listing(
            id="mock-2",
            source="mock",
            address="456 Oak Ave",
            city="London",
            province="ON",
            postal_code="N6A 2B2",
            price=475000,
            bedrooms=3,
            bathrooms=2,
            property_type="Single Family",
            description="Basement apartment with separate entrance.",
            url="https://example.com/2",
            raw_payload={},
        ),
    ]
