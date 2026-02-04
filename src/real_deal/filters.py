"""Listing filters for keyword matching and price constraints."""

from __future__ import annotations

from .models import Listing


def filter_listings(
    listings: list[Listing],
    include_keywords: list[str],
    exclude_keywords: list[str],
    max_price: float,
) -> list[Listing]:
    """
    Filter listings by keywords and max price.
    - Must match at least one include keyword (in description or property_type)
    - Must not match any exclude keyword
    - Price must be <= max_price
    """
    result = []
    text_fields = ["description", "property_type", "address"]
    for l in listings:
        if l.price > max_price:
            continue
        combined = " ".join(
            str(getattr(l, f, "")) for f in text_fields
        ).lower()
        if exclude_keywords:
            if any(kw.lower() in combined for kw in exclude_keywords):
                continue
        if include_keywords:
            if not any(kw.lower() in combined for kw in include_keywords):
                continue
        result.append(l)
    return result
