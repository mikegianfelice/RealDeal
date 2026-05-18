"""Rule-based land signal extraction from listings."""

from __future__ import annotations

import re

from ..models import Listing
from .detection import classify_land_type
from .models import LandSignals

# Zoning / planning
_ZONING_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\br(?:ural|1|2)\b.*\bzoning\b|\brural\s+residential\b", "rural_residential"),
    (r"(?i)\bresidential\b.*\bzoning\b|\bzoned\s+residential\b", "residential"),
    (r"(?i)\bagricultural\b.*\bzoning\b|\bzoned\s+agricultural\b", "agricultural"),
    (r"(?i)\bcommercial\b.*\bzoning\b", "commercial"),
    (r"(?i)\bhamlet\b|\bvillage\b.*\bzoning\b", "hamlet"),
]

_ACCESS_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\blegal\s+(?:year[- ]round\s+)?road\b|\blegal\s+access\b", "legal_road"),
    (r"(?i)\bprivate\s+road\b|\blane\b", "private_road"),
    (r"(?i)\bseasonal\s+road\b|\bunassumed\s+road\b", "seasonal_road"),
    (r"(?i)\bwater\s+access\b|\bboat\s+access\b", "water_access"),
    (r"(?i)\bno\s+road\s+access\b|\blandlocked\b", "no_legal_access"),
]

_UTILITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("hydro", re.compile(r"(?i)\bhydro\b|\belectric(?:al)?\s+at\s+lot\b|\bpower\s+at\s+lot\b")),
    ("water", re.compile(r"(?i)\bmunicipal\s+water\b|\bwater\s+at\s+lot\b|\bwaterr\b")),
    ("sewer", re.compile(r"(?i)\bmunicipal\s+sewer\b|\bsewer\s+at\s+lot\b|\bsewer\s+available\b|water\s+and\s+sewer\b")),
    ("gas", re.compile(r"(?i)\bnatural\s+gas\b|\bgas\s+at\s+lot\b")),
    ("internet", re.compile(r"(?i)\bfibre|fiber\b|\bhigh[- ]speed\b")),
]

_RISK_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\bwetland\b|\bprovincially\s+significant\b|\bpsw\b", "wetland"),
    (r"(?i)\bflood\s*plain\b|\bfloodplain\b|\bflood\s+zone\b", "floodplain"),
    (r"(?i)\bconservation\b|\bnvca\b|\bsource\s+water\b|\bprotected\b", "conservation"),
    (r"(?i)\benvironmentally\s+protected\b|\bepa\b", "environmental"),
    (r"(?i)\bsteep\s+slope\b|\bescarpment\b|\brock\s+outcrop\b", "topography"),
    (r"(?i)\bnot\s+buildable\b|\bnon[- ]buildable\b|\bunbuildable\b", "not_buildable"),
]

_OPPORTUNITY_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\bseverance\b|\bsubdivid", "severance"),
    (r"(?i)\bdevelopment\s+potential\b|\bfuture\s+development\b", "development"),
    (r"(?i)\bexpanding\b|\bgrowth\b|\burban\s+boundary\b|\bminutes\s+from\b", "growth"),
    (r"(?i)\bhydro\s+at\s+lot\s+line\b|\butilities\s+at\s+lot\b", "utilities_ready"),
    (r"(?i)\bmotivated\s+seller\b|\bquick\s+sale\b|\bestate\s+sale\b", "distress"),
    (r"(?i)\binvestor\s+opportunity\b|\bvalue\b", "value"),
]


def extract_land_signals(listing: Listing) -> LandSignals:
    """Extract structured land signals from listing fields."""
    text = " ".join(
        [
            listing.description or "",
            listing.address or "",
            listing.property_type or "",
        ]
    ).lower()

    land_type = classify_land_type(listing, text)
    zoning_hint: str | None = None
    for pat, label in _ZONING_PATTERNS:
        if re.search(pat, text):
            zoning_hint = label
            break

    access_type: str | None = None
    legal_road: bool | None = None
    seasonal_road = False
    for pat, label in _ACCESS_PATTERNS:
        if re.search(pat, text):
            access_type = label
            if label == "legal_road":
                legal_road = True
            elif label == "seasonal_road":
                seasonal_road = True
                legal_road = False
            elif label == "no_legal_access":
                legal_road = False
            break

    utilities: list[str] = []
    for name, rx in _UTILITY_PATTERNS:
        if rx.search(text):
            utilities.append(name)

    wetland = floodplain = conservation = False
    red_flags: list[str] = []
    for pat, label in _RISK_PATTERNS:
        if re.search(pat, text):
            if label == "wetland":
                wetland = True
                red_flags.append("wetland_or_psw_reference")
            elif label == "floodplain":
                floodplain = True
                red_flags.append("floodplain_reference")
            elif label == "conservation":
                conservation = True
                red_flags.append("conservation_or_protected_area")
            elif label == "not_buildable":
                red_flags.append("explicitly_not_buildable")
            else:
                red_flags.append(label)

    opportunities: list[str] = []
    severance = development = growth = distress = False
    for pat, label in _OPPORTUNITY_PATTERNS:
        if re.search(pat, text):
            opportunities.append(label)
            if label == "severance":
                severance = True
            elif label == "development":
                development = True
            elif label == "growth":
                growth = True
            elif label == "distress":
                distress = True

    buyer_verify = bool(re.search(r"(?i)buyer\s+to\s+verify|due\s+diligence", text))
    if buyer_verify:
        red_flags.append("buyer_to_verify")

    septic: bool | None = None
    if re.search(r"(?i)\bseptic\b", text):
        septic = "municipal" not in text and "sewer" not in text

    topo: str | None = None
    if re.search(r"(?i)\bflat\b|\bcleared\b|\blevel\b", text):
        topo = "level"
    elif re.search(r"(?i)\brolling\b|\bmoderate\s+slope\b", text):
        topo = "rolling"
    elif re.search(r"(?i)\bsteep\b|\brocky\b", text):
        topo = "challenging"

    notes: list[str] = []
    if not listing.description.strip():
        notes.append("empty_description")

    return LandSignals(
        land_type=land_type,
        zoning_hint=zoning_hint,
        access_type=access_type,
        legal_road_access=legal_road,
        utilities_at_lot=utilities,
        wetland_risk=wetland,
        floodplain_risk=floodplain,
        conservation_risk=conservation,
        severance_hint=severance,
        development_hint=development,
        seasonal_road=seasonal_road,
        buyer_to_verify=buyer_verify,
        distress_language=distress,
        growth_proximity_hint=growth,
        septic_mentioned=septic,
        topography_hint=topo,
        red_flags=red_flags,
        opportunity_flags=opportunities,
        notes=notes,
    )
