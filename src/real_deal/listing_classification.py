"""Detect vacant land / lots so they are not underwritten as residential."""

from __future__ import annotations

import re
from typing import Any

# Redfin Canada API: type 8 is vacant land/lots in practice (not townhouse).
REDFIN_PROPERTY_TYPE_LAND = frozenset({8, 10})

_LAND_ADDRESS_PATTERN = re.compile(
    r"(?i)(?:"
    r"\bpt\s+(?:fm|farm|lt|lot)\b|"
    r"\bpart\s+fm\b|"
    r"\bpt\s+lt\b|"
    r"\bfarm\s+lot\b|"
    r"\bvacant\s+(?:land|lot)\b|"
    r"\bvacant\b|"
    r"\b\d+(?:\.\d+)?\s*acres?\b|"
    r"\bacres?\b|"
    r"\blot\s+\d+\b|"
    r"\blt\s+\d+\b|"
    r"\bcon(?:cession)?\s+\d+\b|"
    r"\bparcel\b|"
    r"^\s*lt\s+"
    r")",
)

_LAND_TEXT_KEYWORDS = (
    "vacant land",
    "vacant lot",
    "land only",
    "building lot",
    "waterfront lot",
    "empty lot",
    "undeveloped",
    "no structure",
)


def _redfin_property_type_num(raw_payload: dict[str, Any] | None) -> int | None:
    if not raw_payload:
        return None
    hd = raw_payload.get("homeData") or raw_payload
    pt = hd.get("propertyType")
    if pt is None:
        return None
    try:
        return int(pt)
    except (TypeError, ValueError):
        return None


def is_land_listing(
    *,
    address: str = "",
    property_type: str = "",
    description: str = "",
    url: str = "",
    bedrooms: int = 0,
    bathrooms: float = 0,
    raw_payload: dict[str, Any] | None = None,
) -> bool:
    """Return True if listing is vacant land / lot (land underwriting pipeline, not residential)."""
    ptype_num = _redfin_property_type_num(raw_payload)
    if ptype_num is not None and ptype_num in REDFIN_PROPERTY_TYPE_LAND:
        return True

    ptype_lower = (property_type or "").lower()
    if any(
        tok in ptype_lower
        for tok in ("land", "vacant", "lot", "acreage", "farm", "building lot")
    ):
        return True

    combined = f"{address} {description} {url}".lower()
    if any(kw in combined for kw in _LAND_TEXT_KEYWORDS):
        return True

    if _LAND_ADDRESS_PATTERN.search(address or ""):
        return True

    # No beds/baths and lot-style address (Redfin often omits beds on land)
    if (
        (bedrooms or 0) <= 0
        and (bathrooms or 0) <= 0
        and ptype_num == 8
    ):
        return True

    return False


def is_land_from_listing(listing: Any) -> bool:
    """Convenience wrapper for Listing models."""
    return is_land_listing(
        address=getattr(listing, "address", "") or "",
        property_type=getattr(listing, "property_type", "") or "",
        description=getattr(listing, "description", "") or "",
        url=getattr(listing, "url", "") or "",
        bedrooms=int(getattr(listing, "bedrooms", 0) or 0),
        bathrooms=float(getattr(listing, "bathrooms", 0) or 0),
        raw_payload=getattr(listing, "raw_payload", None),
    )
