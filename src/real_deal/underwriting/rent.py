"""Rent estimation and parsing from listings."""

import re
from typing import Optional

from ..models import Listing, RentEstimationParams


def parse_rent_from_description(
    description: str,
    min_rent: float = 500,
    max_rent: float = 15000,
) -> Optional[float]:
    """
    Parse explicit rent numbers from listing description.
    Looks for patterns like: $2000/mo, $2000/month, rent $2000, etc.
    Returns the first valid rent found (within min_rent..max_rent), or None.
    """
    if not description:
        return None

    text = description.lower()
    candidates: list[float] = []

    for m in re.finditer(r'\$([\d,]+)', text):
        num_str = m.group(1).replace(",", "")
        if num_str:
            candidates.append(float(num_str))

    for m in re.finditer(r'([\d,]+)\s*(?:/|\s)(?:mo|month)', text):
        num_str = m.group(1).replace(",", "")
        if num_str:
            candidates.append(float(num_str))

    for m in re.finditer(r'rent(?:s)?(?:\s*(?:of|:|=))?\s*\$?([\d,]+)', text):
        num_str = m.group(1).replace(",", "")
        if num_str:
            candidates.append(float(num_str))

    for rent in candidates:
        if min_rent <= rent <= max_rent:
            return rent
    return None


def estimate_rent(listing: Listing, params: RentEstimationParams) -> float:
    """
    Estimate monthly rent for a listing.
    Uses explicit rent from description if found, otherwise: base + per_bedroom * bedrooms.
    """
    parsed = parse_rent_from_description(
        listing.description,
        min_rent=params.min_rent,
        max_rent=params.max_rent,
    )
    if parsed is not None:
        return parsed
    bedrooms = max(1, listing.bedrooms)
    return params.base + params.per_bedroom * bedrooms
