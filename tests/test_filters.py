"""Tests for listing filters."""

import pytest

from real_deal.models import Listing
from real_deal.filters import filter_listings


@pytest.fixture
def sample_listings() -> list[Listing]:
    return [
        Listing(
            id="1",
            source="test",
            address="123 Main",
            city="Windsor",
            province="ON",
            postal_code="",
            price=400000,
            bedrooms=3,
            bathrooms=2,
            property_type="Duplex",
            description="Legal duplex with separate entrance",
            url="",
            raw_payload={},
        ),
        Listing(
            id="2",
            source="test",
            address="456 Oak",
            city="London",
            province="ON",
            postal_code="",
            price=600000,
            bedrooms=4,
            bathrooms=2,
            property_type="Single Family",
            description="Nice house",
            url="",
            raw_payload={},
        ),
        Listing(
            id="3",
            source="test",
            address="789 Pine",
            city="Hamilton",
            province="ON",
            postal_code="",
            price=450000,
            bedrooms=2,
            bathrooms=1,
            property_type="Land",
            description="Vacant lot for sale",
            url="",
            raw_payload={},
        ),
    ]


def test_filter_by_price(sample_listings: list[Listing]) -> None:
    result = filter_listings(sample_listings, [], [], max_price=500000)
    assert len(result) == 2
    assert all(l.price <= 500000 for l in result)


def test_filter_by_include_keyword(sample_listings: list[Listing]) -> None:
    result = filter_listings(
        sample_listings,
        include_keywords=["duplex"],
        exclude_keywords=[],
        max_price=600000,
    )
    assert len(result) == 1
    assert result[0].id == "1"


def test_filter_by_exclude_keyword(sample_listings: list[Listing]) -> None:
    result = filter_listings(
        sample_listings,
        include_keywords=[],
        exclude_keywords=["land", "vacant lot"],
        max_price=600000,
    )
    assert len(result) == 2
    assert not any("land" in l.property_type.lower() for l in result)


def test_filter_combined(sample_listings: list[Listing]) -> None:
    result = filter_listings(
        sample_listings,
        include_keywords=["duplex", "basement"],
        exclude_keywords=["land"],
        max_price=550000,
    )
    assert len(result) == 1
    assert result[0].id == "1"
