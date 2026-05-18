"""Mock land listings for demonstration and regression testing."""

from __future__ import annotations

from datetime import datetime

from ..models import Listing
from .engine import LandUnderwritingEngine
from .models import LandUnderwritingResult


def _listing(
    lid: str,
    address: str,
    city: str,
    price: float,
    ptype: str,
    description: str,
) -> Listing:
    return Listing(
        id=lid,
        source="mock",
        address=address,
        city=city,
        province="ON",
        postal_code="N0H 2T0",
        price=price,
        bedrooms=0,
        bathrooms=0.0,
        property_type=ptype,
        description=description,
        url=f"https://example.com/land/{lid}",
        raw_payload={"homeData": {"propertyType": 8}},
        fetched_at=datetime.utcnow(),
    )


MOCK_EXCELLENT_BUILDABLE = _listing(
    "mock-excellent-lot",
    "123 County Rd 12, Rural Residential",
    "Kincardine",
    89500.0,
    "Vacant Land",
    (
        "0.71 acre residential building lot on legal year-round municipal road. "
        "Zoned rural residential. 110 ft frontage x 280 ft depth. Level cleared lot. "
        "Hydro at lot line, municipal water and sewer available. Ideal for single family build."
    ),
)

MOCK_HIGH_RISK_CONSERVATION = _listing(
    "mock-wetland-risk",
    "Pt Lt 4 Con 8, Wetland Adjacent",
    "South Bruce",
    42000.0,
    "Vacant Land",
    (
        "2.4 acres raw land. Seasonal road. Buyer to verify. "
        "Property near provincially significant wetland and conservation area. "
        "Environmentally protected portions. Floodplain mapping required. Not buildable as-is."
    ),
)

MOCK_SEVERANCE_SPECULATIVE = _listing(
    "mock-severance-growth",
    "45 Acres Hwy 21, Farm Lot",
    "Walkerton",
    185000.0,
    "Farm / Land",
    (
        "45 acre agricultural parcel with severance potential. Minutes from expanding town "
        "and urban boundary. Hydro on property. Rolling topography. "
        "Future development potential subject to municipal approval. Motivated seller."
    ),
)

MOCK_LISTINGS: list[Listing] = [
    MOCK_EXCELLENT_BUILDABLE,
    MOCK_HIGH_RISK_CONSERVATION,
    MOCK_SEVERANCE_SPECULATIVE,
]


def run_mock_underwriting(config: dict | None = None) -> list[LandUnderwritingResult]:
    """Underwrite all mock scenarios and write reports."""
    engine = LandUnderwritingEngine(config=config)
    return engine.underwrite_many(MOCK_LISTINGS, save_report=True)
