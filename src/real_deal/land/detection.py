"""Land listing detection and classification."""

from __future__ import annotations

import re
from typing import Any

from ..listing_classification import is_land_listing
from ..models import Listing
from .models import LandMetrics, LandSignals

_ACRE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:acres?|ac\.?)\b|"
    r"\b(\d+(?:\.\d+)?)\s*ha\b",
    re.IGNORECASE,
)
_FRONTAGE_RE = re.compile(
    r"(?:frontage|front)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(?:ft|feet|')|"
    r"(\d+(?:\.\d+)?)\s*(?:ft|feet|')\s*(?:of\s*)?frontage",
    re.IGNORECASE,
)
_LOT_DIM_RE = re.compile(
    r"(?i)(\d+(?:\.\d+)?)\s*(?:ft|feet|')\s*x\s*(\d+(?:\.\d+)?)\s*(?:ft|feet|')"
)

_LAND_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\bfarm(?:land)?\b|\bagricultural\b", "farmland"),
    (r"(?i)\brecreational\b|\bcottage\s+lot\b", "recreational"),
    (r"(?i)\bseverance\b|\bsubdivid", "severance_opportunity"),
    (r"(?i)\bdevelopment\s+land\b|\bbuild(?:ing)?\s+lot\b", "development_land"),
    (r"(?i)\braw\s+land\b|\bundeveloped\b", "raw_land"),
    (r"(?i)\bresidential\s+lot\b|\bvacant\s+lot\b", "vacant_residential_lot"),
    (r"(?i)\bwaterfront\s+lot\b", "waterfront_lot"),
]


def is_land_candidate(listing: Listing) -> bool:
    """True if listing should use the land underwriting pipeline."""
    return is_land_listing(
        address=listing.address,
        property_type=listing.property_type,
        description=listing.description,
        url=listing.url,
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        raw_payload=listing.raw_payload,
    )


def parse_land_metrics(
    listing: Listing,
    default_acres_if_unknown: float = 0.5,
) -> LandMetrics:
    """Extract acreage and frontage from description, address, and raw payload."""
    text = " ".join(
        [
            listing.description or "",
            listing.address or "",
            str(listing.raw_payload or ""),
        ]
    )
    acres: float | None = None
    for m in _ACRE_RE.finditer(text):
        val = m.group(1) or m.group(2)
        if val:
            a = float(val)
            if "ha" in m.group(0).lower():
                a *= 2.471
            acres = a
            break

    frontage: float | None = None
    depth: float | None = None
    fm = _FRONTAGE_RE.search(text)
    if fm:
        frontage = float(fm.group(1) or fm.group(2))
    dm = _LOT_DIM_RE.search(text)
    if dm:
        frontage = frontage or float(dm.group(1))
        depth = float(dm.group(2))

    # Redfin lot size in sqft in raw payload
    if acres is None and listing.raw_payload:
        hd = listing.raw_payload.get("homeData") or listing.raw_payload
        lot = hd.get("lotSize") or {}
        amt = lot.get("amount")
        if amt is not None:
            try:
                sqft = float(str(amt).replace(",", ""))
                if sqft > 100:
                    acres = sqft / 43560.0
            except ValueError:
                pass

    if acres is None or acres <= 0:
        acres = default_acres_if_unknown

    price = listing.price or 0
    ppa = price / acres if acres and acres > 0 else None
    ppf = price / frontage if frontage and frontage > 0 else None

    return LandMetrics(
        acres=round(acres, 3),
        frontage_ft=round(frontage, 1) if frontage else None,
        depth_ft=round(depth, 1) if depth else None,
        price_per_acre=round(ppa, 0) if ppa else None,
        price_per_frontage_ft=round(ppf, 0) if ppf else None,
    )


def classify_land_type(listing: Listing, text: str | None = None) -> str:
    """Classify land subtype from combined text."""
    combined = text or f"{listing.description} {listing.property_type} {listing.address}"
    for pattern, land_type in _LAND_TYPE_PATTERNS:
        if re.search(pattern, combined):
            return land_type
    if is_land_listing(property_type=listing.property_type, address=listing.address):
        return "vacant_land"
    return "unknown"


def initial_land_signals(listing: Listing) -> LandSignals:
    """Rule-based signal extraction (extended in signals.py)."""
    from .signals import extract_land_signals

    return extract_land_signals(listing)
