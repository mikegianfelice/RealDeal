"""Rent estimation and parsing from listings."""

import re
from typing import Optional

from ..models import Listing, RentEstimationParams


def parse_rent_from_description(description: str) -> Optional[float]:
    """
    Parse explicit rent numbers from listing description.
    Looks for patterns like: $2000/mo, $2000/month, rent $2000, etc.
    Returns the first valid rent found, or None.
    """
    if not description:
        return None

    text = description.lower()
    # Collect all candidate numbers from various patterns
    candidates: list[float] = []

    # Pattern 1: $2000, $2,000, $2000/mo
    for m in re.finditer(r'\$([\d,]+)', text):
        num_str = m.group(1).replace(",", "")
        if num_str:
            candidates.append(float(num_str))

    # Pattern 2: 2000/mo, 2000/month
    for m in re.finditer(r'([\d,]+)\s*(?:/|\s)(?:mo|month)', text):
        num_str = m.group(1).replace(",", "")
        if num_str:
            candidates.append(float(num_str))

    # Pattern 3: rent: 2000, rent $2000
    for m in re.finditer(r'rent(?:s)?(?:\s*(?:of|:|=))?\s*\$?([\d,]+)', text):
        num_str = m.group(1).replace(",", "")
        if num_str:
            candidates.append(float(num_str))

    for rent in candidates:
        if 500 <= rent <= 15000:  # Sanity check
            return rent
    return None


def estimate_rent(listing: Listing, params: RentEstimationParams) -> float:
    """
    Estimate monthly rent for a listing.
    Uses explicit rent from description if found, otherwise: base + per_bedroom * bedrooms.
    """
    parsed = parse_rent_from_description(listing.description)
    if parsed is not None:
        return parsed
    bedrooms = max(1, listing.bedrooms)
    return params.base + params.per_bedroom * bedrooms
