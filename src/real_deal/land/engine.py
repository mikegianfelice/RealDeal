"""Land underwriting engine orchestration."""

from __future__ import annotations

import logging
from typing import Any

from ..config import load_config
from ..models import Listing
from .ai_listing_analysis import analyze_listing, merge_ai_into_signals
from .detection import is_land_candidate, parse_land_metrics
from .financials import compute_land_financials
from .models import LandUnderwritingResult
from .providers import get_gis_provider
from .report import save_land_report
from .scoring import (
    compute_land_scores,
    compute_risk_analysis,
    recommendation_from_score,
)
from .signals import extract_land_signals

logger = logging.getLogger(__name__)


def _city_tier(city: str, config: dict[str, Any]) -> str:
    for tier_name, cities in (config.get("cities") or {}).items():
        if isinstance(cities, list) and city in cities:
            return tier_name
    return "tier_2"


def _next_steps(result: LandUnderwritingResult) -> list[str]:
    steps: list[str] = []
    sig = result.signals
    if sig.legal_road_access is not True:
        steps.append("Confirm legal year-round municipal road access with lawyer.")
    if sig.buyer_to_verify:
        steps.append("Complete buyer due diligence on all seller disclaimers.")
    if sig.wetland_risk or sig.conservation_risk:
        steps.append("Engage conservation authority for wetland/floodplain mapping.")
    if sig.severance_hint:
        steps.append("Pre-consult planning department on severance feasibility.")
    if not sig.utilities_at_lot:
        steps.append("Obtain hydro/water/sewer availability letters from utilities.")
    if result.scores.buildability_score >= 65:
        steps.append("Order draft plan or survey for buildable envelope.")
    if result.recommendation == "PASS":
        steps = ["Archive — does not meet minimum land investment criteria."] + steps[:2]
    return steps[:6]


class LandUnderwritingEngine:
    """Underwrite vacant land listings end-to-end."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_config()
        self.gis = get_gis_provider(self.config)

    def underwrite(
        self,
        listing: Listing,
        *,
        save_report: bool = True,
        report_dir: str | None = None,
    ) -> LandUnderwritingResult | None:
        if not is_land_candidate(listing):
            logger.debug("Skipping non-land listing %s", listing.id)
            return None

        metrics = parse_land_metrics(listing)
        signals = extract_land_signals(listing)
        ai = analyze_listing(listing, self.config, signals)
        signals = merge_ai_into_signals(signals, ai)

        tier = _city_tier(listing.city or "", self.config)
        financials = compute_land_financials(listing, metrics, signals, self.config, tier)
        scores, exits = compute_land_scores(signals, metrics, financials, self.config)
        risks = compute_risk_analysis(signals, financials)
        rec = recommendation_from_score(scores.underwriting_score, signals, self.config)

        red = list(dict.fromkeys(signals.red_flags + ai.risks))
        opps = list(dict.fromkeys(signals.opportunity_flags + ai.opportunities))

        result = LandUnderwritingResult(
            listing_id=listing.id,
            listing=listing,
            metrics=metrics,
            signals=signals,
            financials=financials,
            scores=scores,
            exit_strategies=exits,
            risk_analysis=risks,
            ai_analysis=ai,
            recommendation=rec,
            red_flags=red,
            opportunity_flags=opps,
        )
        result.next_steps = _next_steps(result)

        if save_report:
            rd = report_dir or self.config.get("land_underwriting", {}).get(
                "report_output_dir", "outputs/underwriting"
            )
            save_land_report(result, rd)

        return result

    def underwrite_many(
        self,
        listings: list[Listing],
        **kwargs: Any,
    ) -> list[LandUnderwritingResult]:
        results: list[LandUnderwritingResult] = []
        for listing in listings:
            r = self.underwrite(listing, **kwargs)
            if r is not None:
                results.append(r)
        return results
