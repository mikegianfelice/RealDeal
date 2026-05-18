"""Rent estimation and parsing from listings."""

from __future__ import annotations

import re
from typing import Optional

from ..models import Listing, RentEstimationParams

# Context keywords that suggest a dollar amount is rent-related.
_RENT_KEYWORDS: set[str] = {
    "rent", "tenant", "lease", "/mo", "month", "monthly",
    "upstairs", "basement", "unit", "suite", "income",
    "upper", "lower", "main", "floor",
}

# Context keywords that suggest a dollar amount is NOT rent.
_IGNORE_KEYWORDS: set[str] = {
    "deposit", "damage", "security", "down", "closing",
    "tax", "taxes", "hoa", "condo fee", "fees",
    "sqft", "square", "year", "annual", "/yr",
    "assessment", "renovation", "reno",
}

# Multi-unit signal phrases (any substring match triggers sum logic).
_MULTI_UNIT_SIGNALS: set[str] = {
    "upstairs", "basement", "unit", "suite",
    "duplex", "triplex", "separate entrance",
    "2 units", "two units", "3 units", "three units",
    "upper", "lower", "main floor",
}

_CONTEXT_WINDOW = 40  # chars before + after a match to scan for keywords


def _extract_candidates(text: str) -> list[tuple[float, int]]:
    """Extract (amount, position) pairs from *lowercased* text.

    Three pattern families are tried (in order):
    1. ``$1,234`` style
    2. ``1234 /mo`` or ``1234 month`` style
    3. ``rent: 1234`` / ``rents of 1234`` style

    Overlapping matches for the same dollar amount within a small window
    are collapsed so ``$1800/mo`` doesn't produce two entries.
    """
    # Track by the start position of the *captured digits* (group 1)
    # so overlapping patterns for the same number are collapsed.
    seen: dict[int, float] = {}  # digit_position -> amount

    for m in re.finditer(r"\$([\d,]+)", text):
        num = m.group(1).replace(",", "")
        if num:
            seen.setdefault(m.start(1), float(num))

    for m in re.finditer(r"([\d,]+)\s*(?:/|\s)(?:mo|month)", text):
        num = m.group(1).replace(",", "")
        if num:
            seen.setdefault(m.start(1), float(num))

    for m in re.finditer(r"rent(?:s)?(?:\s*(?:of|:|=|at))?\s*\$?([\d,]+)", text):
        num = m.group(1).replace(",", "")
        if num:
            seen.setdefault(m.start(1), float(num))

    return [(amt, pos) for pos, amt in sorted(seen.items())]


def _context_around(text: str, pos: int, window: int = _CONTEXT_WINDOW) -> str:
    """Return a substring of *text* centred on *pos*."""
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    return text[start:end]


def _is_rent_ish(context: str) -> bool:
    """Return True if *context* contains at least one rent keyword."""
    return any(kw in context for kw in _RENT_KEYWORDS)


def _is_ignorable(context: str, amount_index: int | None = None) -> bool:
    """Return True if an ignore keyword appears before the amount in *context*."""
    if amount_index is None:
        return any(kw in context for kw in _IGNORE_KEYWORDS)
    left = context[:amount_index]
    return any(kw in left for kw in _IGNORE_KEYWORDS)


def _has_multi_unit_signal(text: str) -> bool:
    """Return True if the full description signals a multi-unit property."""
    return any(sig in text for sig in _MULTI_UNIT_SIGNALS)


def parse_rent_details(
    description: str,
    min_rent: float = 500,
    max_rent: float = 15000,
) -> tuple[Optional[float], dict]:
    """Parse explicit rent from a listing description with metadata.

    Returns (rent, metadata) where metadata includes:
    - rent_candidates_count: number of validated rent candidates
    - multi_unit_sum_applied: True if multi-unit sum was used
    - explicit_rent_found: True if rent was parsed (not None)
    """
    metadata: dict = {
        "rent_candidates_count": 0,
        "multi_unit_sum_applied": False,
        "explicit_rent_found": False,
    }
    if not description:
        return None, metadata

    text = description.lower()
    raw_candidates = _extract_candidates(text)

    # Validate candidates ------------------------------------------------
    validated: list[float] = []
    for amt, pos in raw_candidates:
        if not (min_rent <= amt <= max_rent):
            continue
        start = max(0, pos - _CONTEXT_WINDOW)
        ctx = _context_around(text, pos)
        amount_index = pos - start
        if _is_ignorable(ctx, amount_index):
            continue
        if _is_rent_ish(ctx):
            validated.append(amt)

    metadata["rent_candidates_count"] = len(validated)
    if not validated:
        return None, metadata

    # Multi-unit sum rule ------------------------------------------------
    if _has_multi_unit_signal(text) and len(validated) >= 2:
        totals: list[float] = []
        per_unit: list[float] = []
        for amt, pos in raw_candidates:
            if amt not in validated:
                continue
            start = max(0, pos - _CONTEXT_WINDOW)
            ctx = _context_around(text, pos)
            if "total" in ctx:
                totals.append(amt)
            elif 800 <= amt <= 8000:
                per_unit.append(amt)

        if totals:
            metadata["explicit_rent_found"] = True
            return max(totals), metadata
        if len(per_unit) >= 2:
            metadata["multi_unit_sum_applied"] = True
            metadata["explicit_rent_found"] = True
            return sum(per_unit[:3]), metadata

    # Single / ambiguous: return max validated candidate ------------------
    metadata["explicit_rent_found"] = True
    return max(validated), metadata


def parse_rent_from_description(
    description: str,
    min_rent: float = 500,
    max_rent: float = 15000,
) -> Optional[float]:
    """Parse explicit rent from a listing description.

    Strategy:
    1. Extract all dollar-amount candidates with a context window.
    2. Validate each: must be in ``[min_rent, max_rent]``, context must
       contain a rent-ish keyword and no ignore keywords.
    3. If the description contains multi-unit signals and there are 2+
       validated per-unit candidates (800..8000), sum them (up to 3).
    4. Otherwise return the **maximum** validated candidate (conservative:
       avoids grabbing a smaller, unrelated amount).
    5. If no validated candidates, return ``None`` so the caller falls
       back to the tiered formula.
    """
    rent, _ = parse_rent_details(description, min_rent, max_rent)
    return rent


def estimate_rent(listing: Listing, params: RentEstimationParams) -> float:
    """Estimate monthly rent for a listing.

    Uses explicit rent parsed from the description when available;
    otherwise falls back to the tiered formula:
    ``base + per_bedroom * bedrooms``.
    """
    rent, _ = estimate_rent_with_details(listing, params)
    return rent


def _capped_bedrooms(raw: int, cap: int) -> tuple[int, bool]:
    """Return (effective_bedrooms, was_capped) for formula rent; minimum 1."""
    effective = max(1, min(raw, cap))
    return effective, effective < raw


def estimate_rent_with_details(
    listing: Listing,
    params: RentEstimationParams,
    unit_count_hint: int | None = None,
) -> tuple[float, dict]:
    """Estimate monthly rent with metadata (rent_was_explicit, etc.)."""
    parsed, meta = parse_rent_details(
        listing.description,
        min_rent=params.min_rent,
        max_rent=params.max_rent,
    )
    if parsed is not None:
        meta["rent_was_explicit"] = True
        return parsed, meta

    meta["rent_was_explicit"] = False
    bedrooms = max(1, listing.bedrooms)
    if unit_count_hint and unit_count_hint >= 2:
        beds_per_unit_raw = max(1, bedrooms // unit_count_hint)
        beds_per_unit, capped = _capped_bedrooms(
            beds_per_unit_raw, params.max_bedrooms_per_unit
        )
        per_unit = params.base + params.per_bedroom * beds_per_unit
        meta["multi_unit_formula"] = True
        meta["unit_count"] = unit_count_hint
        meta["beds_per_unit"] = beds_per_unit
        meta["beds_per_unit_listed"] = beds_per_unit_raw
        if capped:
            meta["bedrooms_capped"] = True
        return unit_count_hint * per_unit, meta

    effective_beds, capped = _capped_bedrooms(
        bedrooms, params.max_bedrooms_single_unit
    )
    meta["effective_bedrooms"] = effective_beds
    meta["bedrooms_listed"] = bedrooms
    if capped:
        meta["bedrooms_capped"] = True
    return params.base + params.per_bedroom * effective_beds, meta
