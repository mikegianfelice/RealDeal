"""Listing filters for keyword matching and price constraints."""

from __future__ import annotations

from .listing_classification import is_land_from_listing
from .models import Listing

# Fields commonly present in API payloads (search without full JSON serialize)
_PAYLOAD_TEXT_KEYS = frozenset({
    "description", "publicremarks", "publicremarksen", "remarks",
    "propertytype", "propertytypename", "address", "unparsedaddress",
    "title", "headline", "summary", "features", "amenities",
})


def _payload_search_text(payload: dict, max_depth: int = 4) -> str:
    """Collect searchable text from a raw API payload (no json.dumps)."""
    parts: list[str] = []

    def walk(obj: object, depth: int) -> None:
        if depth > max_depth:
            return
        if isinstance(obj, str):
            if obj.strip():
                parts.append(obj)
        elif isinstance(obj, dict):
            for key, val in obj.items():
                key_lower = str(key).lower()
                if isinstance(val, str) and (
                    key_lower in _PAYLOAD_TEXT_KEYS or len(val) < 500
                ):
                    parts.append(val)
                else:
                    walk(val, depth + 1)
        elif isinstance(obj, list):
            for item in obj[:40]:
                walk(item, depth + 1)

    walk(payload, 0)
    return " ".join(parts).lower()


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
    include_lower = [kw.lower() for kw in include_keywords] if include_keywords else []
    exclude_lower = [kw.lower() for kw in exclude_keywords] if exclude_keywords else []
    text_fields = ("description", "property_type", "address")
    result: list[Listing] = []

    for listing in listings:
        if listing.price > max_price:
            continue
        combined = " ".join(str(getattr(listing, f, "")) for f in text_fields).lower()
        if listing.raw_payload:
            combined = f"{combined} {_payload_search_text(listing.raw_payload)}"
        if exclude_lower and any(kw in combined for kw in exclude_lower):
            continue
        if include_lower and not any(kw in combined for kw in include_lower):
            continue
        if is_land_from_listing(listing):
            continue
        result.append(listing)
    return result
