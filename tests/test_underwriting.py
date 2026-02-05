"""Tests for underwriting engine."""

import pytest

from real_deal.models import Listing, UnderwritingAssumptions, PassFailThresholds, StressTestParams
from real_deal.underwriting import UnderwritingEngine, estimate_rent, parse_rent_from_description
from real_deal.underwriting.rent import RentEstimationParams


class TestRentEstimation:
    """Tests for rent estimation."""

    def test_parse_rent_from_description_dollar_mo(self) -> None:
        assert parse_rent_from_description("Rent: $2000/mo") == 2000
        assert parse_rent_from_description("$2,500/month") == 2500

    def test_parse_rent_from_description_rent_keyword(self) -> None:
        assert parse_rent_from_description("Currently renting at $1800") == 1800
        assert parse_rent_from_description("Rent of $2200") == 2200

    def test_parse_rent_from_description_no_match(self) -> None:
        assert parse_rent_from_description("Nice house with 4 bedrooms") is None
        assert parse_rent_from_description("") is None

    def test_parse_rent_sanity_check(self) -> None:
        # Too low
        assert parse_rent_from_description("$100/mo") is None
        # Too high
        assert parse_rent_from_description("$20000/mo") is None

    def test_estimate_rent_from_description(self) -> None:
        listing = Listing(
            id="1",
            source="test",
            address="123 St",
            city="Windsor",
            province="ON",
            postal_code="",
            price=400000,
            bedrooms=3,
            bathrooms=2,
            property_type="Duplex",
            description="Rent: $2500 total",
            url="",
            raw_payload={},
        )
        params = RentEstimationParams(base=1200, per_bedroom=850, min_rent=500, max_rent=15000)
        assert estimate_rent(listing, params) == 2500

    def test_estimate_rent_fallback(self) -> None:
        listing = Listing(
            id="1",
            source="test",
            address="123 St",
            city="Windsor",
            province="ON",
            postal_code="",
            price=400000,
            bedrooms=3,
            bathrooms=2,
            property_type="Duplex",
            description="Nice duplex",
            url="",
            raw_payload={},
        )
        params = RentEstimationParams(base=1200, per_bedroom=850, min_rent=500, max_rent=15000)
        # base + 3 * per_bedroom = 1200 + 2550 = 3750
        assert estimate_rent(listing, params) == 3750


class TestUnderwritingEngine:
    """Tests for underwriting engine."""

    def test_underwrite_produces_result(self, mock_listing: Listing) -> None:
        engine = UnderwritingEngine()
        result = engine.underwrite(mock_listing)
        assert result.listing_id == mock_listing.id
        assert result.rent_monthly > 0
        assert result.noi_annual != 0
        assert 0 <= result.margin_of_safety_score <= 100
        assert isinstance(result.reason_flags, list)
        assert len(result.reason_flags) >= 4

    def test_underwrite_many(self, mock_listings: list[Listing]) -> None:
        engine = UnderwritingEngine()
        results = engine.underwrite_many(mock_listings)
        assert len(results) == len(mock_listings)
        for r in results:
            assert r.listing_id in [l.id for l in mock_listings]

    def test_stress_case_lower_than_base(self, mock_listing: Listing) -> None:
        engine = UnderwritingEngine()
        result = engine.underwrite(mock_listing)
        # Stress rent should be lower (7% haircut)
        assert result.stress_rent_monthly <= result.rent_monthly
        # Stress cashflow should typically be lower or equal
        assert result.stress_cashflow_monthly <= result.cashflow_monthly + 50  # small tolerance

    def test_cap_rate_positive_for_positive_noi(self, mock_listing: Listing) -> None:
        engine = UnderwritingEngine()
        result = engine.underwrite(mock_listing)
        if result.noi_annual > 0:
            assert result.cap_rate > 0
