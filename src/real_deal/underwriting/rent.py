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


def _is_ignorable(context: str) -> bool:
    """Return True if *context* contains an ignore keyword."""
    return any(kw in context for kw in _IGNORE_KEYWORDS)


def _has_multi_unit_signal(text: str) -> bool:
    """Return True if the full description signals a multi-unit property."""
    return any(sig in text for sig in _MULTI_UNIT_SIGNALS)


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
    if not description:
        return None

    text = description.lower()
    raw_candidates = _extract_candidates(text)

    # Validate candidates ------------------------------------------------
    validated: list[float] = []
    for amt, pos in raw_candidates:
        if not (min_rent <= amt <= max_rent):
            continue
        ctx = _context_around(text, pos)
        if _is_ignorable(ctx):
            continue
        if _is_rent_ish(ctx):
            validated.append(amt)

    if not validated:
        return None

    # Multi-unit sum rule ------------------------------------------------
    if _has_multi_unit_signal(text) and len(validated) >= 2:
        # Separate candidates whose context contains "total" – these are
        # already the combined rent and must not be summed again.
        totals: list[float] = []
        per_unit: list[float] = []
        for amt, pos in raw_candidates:
            if amt not in validated:
                continue
            ctx = _context_around(text, pos)
            if "total" in ctx:
                totals.append(amt)
            elif 800 <= amt <= 8000:
                per_unit.append(amt)

        if totals:
            return max(totals)
        if len(per_unit) >= 2:
            return sum(per_unit[:3])

    # Single / ambiguous: return max validated candidate ------------------
    return max(validated)


def estimate_rent(listing: Listing, params: RentEstimationParams) -> float:
    """Estimate monthly rent for a listing.

    Uses explicit rent parsed from the description when available;
    otherwise falls back to the tiered formula:
    ``base + per_bedroom * bedrooms``.
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
