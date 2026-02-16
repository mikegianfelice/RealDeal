"""Extract structured signals from listing descriptions for underwriting confidence."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Listing
from dataclasses import dataclass, field


@dataclass
class ListingSignals:
    """Structured signals extracted from a listing description."""

    explicit_rent_found: bool
    multi_unit_signal: bool
    unit_count_hint: int | None
    condo_signal: bool
    condo_fee_monthly: float | None
    utilities_included: bool | None
    tenant_pays_utilities: bool | None
    legal_suite_signal: bool | None
    notes: list[str] = field(default_factory=list)


# Multi-unit keywords (substring match in normalized text)
_MULTI_UNIT_KEYWORDS: set[str] = {
    "duplex",
    "triplex",
    "fourplex",
    "4plex",
    "2 units",
    "two units",
    "3 units",
    "three units",
    "separate suite",
    "secondary suite",
    "in-law suite",
    "basement apartment",
    "separate entrance",
    "unit a",
    "unit b",
    "upper unit",
    "lower unit",
    "upstairs",
    "basement",
}

# Unit count mapping (keyword -> count)
_UNIT_COUNT_MAP: dict[str, int] = {
    "duplex": 2,
    "triplex": 3,
    "fourplex": 4,
    "4plex": 4,
    "2 units": 2,
    "two units": 2,
    "3 units": 3,
    "three units": 3,
}

# Condo keywords
_CONDO_KEYWORDS: set[str] = {
    "condo",
    "condominium",
    "strata",
    "maintenance fee",
    "condo fee",
    "hoa",
}

# Utilities included keywords
_UTILITIES_INCLUDED_KEYWORDS: set[str] = {
    "utilities included",
    "all inclusive",
    "incl utilities",
    "includes hydro",
    "includes heat",
}

# Tenant pays utilities keywords
_TENANT_PAYS_UTILITIES_KEYWORDS: set[str] = {
    "tenant pays",
    "tenant to pay",
    "hydro extra",
    "utilities extra",
    "plus utilities",
    "+ utilities",
    "tenant responsible for utilities",
    "tenant pays hydro",
}

# Legal suite positive keywords (must be near suite keywords)
_LEGAL_POSITIVE_KEYWORDS: set[str] = {
    "legal",
    "registered",
    "licensed",
    "permitted",
    "code compliant",
}

# Legal suite negative keywords
_LEGAL_NEGATIVE_KEYWORDS: set[str] = {
    "non-conforming",
    "not legal",
    "unpermitted",
    "illegal",
}

# Suite keywords (for legal signal context)
_SUITE_KEYWORDS: set[str] = {
    "suite",
    "apartment",
    "unit",
    "basement",
    "in-law",
    "secondary",
}

# Condo fee sane range (CAD)
_CONDO_FEE_MIN = 50
_CONDO_FEE_MAX = 2000


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    if not text:
        return ""
    return " ".join(text.lower().split())


def _parse_condo_fee(text: str) -> float | None:
    """Parse condo/maintenance fee from text. Returns None if not found or out of range."""
    # Patterns: "condo fee $425", "maintenance fee: $510/mo", "hoa $300/month"
    patterns = [
        r"(?:condo|maintenance)\s+fee[s]?\s*[:\s]*\$?\s*([\d,]+)\s*(?:/mo|/month|/mo\.|monthly)?",
        r"hoa\s+\$?\s*([\d,]+)\s*(?:/mo|/month|/mo\.|monthly)?",
        r"\$?\s*([\d,]+)\s*(?:/mo|/month)\s*(?:condo|maintenance)\s+fee",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                if _CONDO_FEE_MIN <= val <= _CONDO_FEE_MAX:
                    return val
            except (ValueError, IndexError):
                pass
    return None


def _has_suite_context(text: str) -> bool:
    """Return True if text contains suite-related keywords."""
    return any(kw in text for kw in _SUITE_KEYWORDS)


def _extract_hoa_from_payload(raw_payload: dict | None) -> float | None:
    """Extract hoaDues from Redfin raw_payload if present and sane.

    Redfin stores HOA/condo fees at ``homeData.hoaDues.amount`` (string).
    Returns the monthly amount if within the sane range, else None.
    """
    if not raw_payload or not isinstance(raw_payload, dict):
        return None
    hd = raw_payload.get("homeData") or raw_payload
    hoa = hd.get("hoaDues") or {}
    amt_str = hoa.get("amount")
    if not amt_str:
        return None
    try:
        val = float(str(amt_str).replace(",", ""))
        if _CONDO_FEE_MIN <= val <= _CONDO_FEE_MAX:
            return val
    except (ValueError, TypeError):
        pass
    return None


def extract_signals(
    description: str | None,
    raw_payload: dict | None = None,
) -> ListingSignals:
    """Extract structured signals from a listing description and raw API payload.

    Uses conservative keyword matching on the description text.
    Also checks ``raw_payload`` for structured data (e.g. Redfin ``hoaDues``).
    """
    notes: list[str] = []
    text = _normalize(description or "")

    # explicit_rent_found: determined by rent parser, not signals; set False here
    # (caller will set based on parse_rent_from_description result)
    explicit_rent_found = False

    # Multi-unit signal
    multi_unit_signal = any(kw in text for kw in _MULTI_UNIT_KEYWORDS)

    # Unit count hint
    unit_count_hint: int | None = None
    for kw, count in _UNIT_COUNT_MAP.items():
        if kw in text:
            unit_count_hint = count
            break

    # Condo signal
    condo_signal = any(kw in text for kw in _CONDO_KEYWORDS)

    # Condo fee: prefer structured API data, fall back to description parsing
    condo_fee_monthly: float | None = None
    hoa_from_api = _extract_hoa_from_payload(raw_payload)
    if hoa_from_api is not None:
        condo_fee_monthly = hoa_from_api
        condo_signal = True
        notes.append(f"condo_fee_from_api={hoa_from_api}")
    elif condo_signal:
        condo_fee_monthly = _parse_condo_fee(text)
        if condo_fee_monthly is not None:
            notes.append(f"condo_fee_parsed={condo_fee_monthly}")

    # Utilities
    has_included = any(kw in text for kw in _UTILITIES_INCLUDED_KEYWORDS)
    has_tenant_pays = any(kw in text for kw in _TENANT_PAYS_UTILITIES_KEYWORDS)
    if has_included and has_tenant_pays:
        utilities_included = None
        tenant_pays_utilities = None
        notes.append("utilities_ambiguous")
    else:
        utilities_included = has_included if has_included else None
        tenant_pays_utilities = has_tenant_pays if has_tenant_pays else None

    # Legal suite signal
    legal_suite_signal: bool | None = None
    if _has_suite_context(text):
        has_legal_pos = any(kw in text for kw in _LEGAL_POSITIVE_KEYWORDS)
        has_legal_neg = any(kw in text for kw in _LEGAL_NEGATIVE_KEYWORDS)
        if has_legal_pos and not has_legal_neg:
            legal_suite_signal = True
            notes.append("legal_suite_positive")
        elif has_legal_neg:
            legal_suite_signal = False
            notes.append("legal_suite_negative")

    return ListingSignals(
        explicit_rent_found=explicit_rent_found,
        multi_unit_signal=multi_unit_signal,
        unit_count_hint=unit_count_hint,
        condo_signal=condo_signal,
        condo_fee_monthly=condo_fee_monthly,
        utilities_included=utilities_included,
        tenant_pays_utilities=tenant_pays_utilities,
        legal_suite_signal=legal_suite_signal,
        notes=notes,
    )


def signals_to_dict(signals: ListingSignals) -> dict:
    """Convert ListingSignals to a JSON-serializable dict."""
    return {
        "explicit_rent_found": signals.explicit_rent_found,
        "multi_unit_signal": signals.multi_unit_signal,
        "unit_count_hint": signals.unit_count_hint,
        "condo_signal": signals.condo_signal,
        "condo_fee_monthly": signals.condo_fee_monthly,
        "utilities_included": signals.utilities_included,
        "tenant_pays_utilities": signals.tenant_pays_utilities,
        "legal_suite_signal": signals.legal_suite_signal,
        "notes": signals.notes,
    }


def compute_confidence_score(
    listing: Listing,
    signals: ListingSignals,
    rent_was_explicit: bool,
) -> tuple[float, list[str]]:
    """Compute confidence score (0.0–1.0) and explanatory notes.

    Rules:
    - Start at 0.50 baseline.
    - Add: explicit rent (+0.20), multi-unit + unit count (+0.10), condo fee parsed (+0.10),
      utilities known (+0.05), legal suite True (+0.05).
    - Subtract: legal suite False (-0.10), condo signal but no fee (-0.20),
      bedrooms 0/missing (-0.10), empty description (-0.10).
    """
    score = 0.50
    notes: list[str] = ["baseline 0.50"]

    # Add points
    if rent_was_explicit:
        score += 0.20
        notes.append("+0.20 explicit_rent")
    if signals.multi_unit_signal and signals.unit_count_hint is not None:
        score += 0.10
        notes.append("+0.10 multi_unit_with_count")
    if signals.condo_signal and signals.condo_fee_monthly is not None:
        score += 0.10
        notes.append("+0.10 condo_fee_parsed")
    if signals.utilities_included is not None or signals.tenant_pays_utilities is not None:
        score += 0.05
        notes.append("+0.05 utilities_known")
    if signals.legal_suite_signal is True:
        score += 0.05
        notes.append("+0.05 legal_suite_true")
    elif signals.legal_suite_signal is False:
        score -= 0.10
        notes.append("-0.10 legal_suite_false")

    # Subtract points
    if signals.condo_signal and signals.condo_fee_monthly is None:
        score -= 0.20
        notes.append("-0.20 condo_signal_no_fee")
    if listing.bedrooms == 0:
        score -= 0.10
        notes.append("-0.10 bedrooms_defaulted")
    desc = listing.description or ""
    if not desc.strip():
        score -= 0.10
        notes.append("-0.10 empty_description")

    score = max(0.0, min(1.0, score))
    return score, notes
