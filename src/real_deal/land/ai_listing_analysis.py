"""AI-assisted listing analysis with rule-based fallback."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from ..models import Listing
from .models import AIListingAnalysis, LandSignals
from .signals import extract_land_signals

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an Ontario vacant land acquisition analyst.
Extract structured signals from the listing. Respond ONLY with valid JSON:
{
  "summary": "2-3 sentence analyst summary",
  "confidence_score": 0.0-1.0,
  "zoning_clues": [],
  "severance_hints": [],
  "development_hints": [],
  "utility_mentions": [],
  "environmental_warnings": [],
  "road_access_clues": [],
  "seller_distress_signals": [],
  "opportunities": [],
  "risks": []
}
"""


def _rule_based_analysis(listing: Listing, signals: LandSignals | None = None) -> AIListingAnalysis:
    """Fallback when OpenAI is unavailable."""
    signals = signals or extract_land_signals(listing)
    desc = (listing.description or "")[:500]
    risks = list(signals.red_flags)
    opps = list(signals.opportunity_flags)

    parts = [f"Land type: {signals.land_type}."]
    if signals.zoning_hint:
        parts.append(f"Zoning hint: {signals.zoning_hint}.")
    if signals.access_type:
        parts.append(f"Access: {signals.access_type}.")
    if signals.utilities_at_lot:
        parts.append(f"Utilities mentioned: {', '.join(signals.utilities_at_lot)}.")

    confidence = 0.55
    if len(desc) > 100:
        confidence += 0.15
    if signals.zoning_hint or signals.access_type:
        confidence += 0.1

    return AIListingAnalysis(
        summary=" ".join(parts) or "Limited listing text; rely on municipal due diligence.",
        confidence_score=min(confidence, 0.85),
        extracted_signals={
            "land_type": signals.land_type,
            "zoning_hint": signals.zoning_hint,
            "access_type": signals.access_type,
            "utilities": signals.utilities_at_lot,
            "wetland_risk": signals.wetland_risk,
            "severance_hint": signals.severance_hint,
        },
        risks=risks,
        opportunities=opps,
        used_ai=False,
    )


def _call_openai(listing: Listing, config: dict[str, Any]) -> AIListingAnalysis | None:
    api_key = os.environ.get("OPENAI_API_KEY") or config.get("openai_api_key")
    if not api_key:
        return None

    lc = config.get("land_underwriting", {}).get("openai", {})
    if lc.get("enabled") is False:
        return None

    model = lc.get("model", "gpt-4o-mini")
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        user_content = json.dumps(
            {
                "address": listing.address,
                "city": listing.city,
                "price": listing.price,
                "property_type": listing.property_type,
                "description": listing.description,
            },
            ensure_ascii=False,
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        return AIListingAnalysis(
            summary=str(data.get("summary", "")),
            confidence_score=float(data.get("confidence_score", 0.7)),
            extracted_signals={
                "zoning_clues": data.get("zoning_clues", []),
                "severance_hints": data.get("severance_hints", []),
                "development_hints": data.get("development_hints", []),
                "utility_mentions": data.get("utility_mentions", []),
                "environmental_warnings": data.get("environmental_warnings", []),
                "road_access_clues": data.get("road_access_clues", []),
                "seller_distress_signals": data.get("seller_distress_signals", []),
            },
            risks=[str(r) for r in data.get("risks", [])],
            opportunities=[str(o) for o in data.get("opportunities", [])],
            used_ai=True,
        )
    except ImportError:
        logger.debug("openai package not installed; using rule-based analysis")
        return None
    except Exception as e:
        logger.warning("OpenAI land analysis failed: %s", e)
        return None


def merge_ai_into_signals(signals: LandSignals, ai: AIListingAnalysis) -> LandSignals:
    """Enrich rule signals with AI extractions."""
    ext = ai.extracted_signals
    for risk in ai.risks:
        if risk not in signals.red_flags:
            signals.red_flags.append(risk)
    for opp in ai.opportunities:
        if opp not in signals.opportunity_flags:
            signals.opportunity_flags.append(opp)

    env = ext.get("environmental_warnings") or []
    if env and not signals.wetland_risk:
        text = " ".join(str(x) for x in env).lower()
        if re.search(r"wetland|flood|conservation", text):
            signals.wetland_risk = "wetland" in text
            signals.conservation_risk = "conservation" in text
    return signals


def analyze_listing(
    listing: Listing,
    config: dict[str, Any],
    signals: LandSignals | None = None,
) -> AIListingAnalysis:
    """Run AI analysis with fallback."""
    signals = signals or extract_land_signals(listing)
    ai = _call_openai(listing, config)
    if ai is None:
        return _rule_based_analysis(listing, signals)
    return ai
