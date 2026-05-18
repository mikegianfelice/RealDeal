"""Weighted land investment scoring (0–100)."""

from __future__ import annotations

from typing import Any

from .models import LandFinancials, LandMetrics, LandScores, LandSignals


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def score_buildability(signals: LandSignals, metrics: LandMetrics, config: dict[str, Any]) -> float:
    """Buildability 0–100; cheap acreage without access scores low."""
    lc = config.get("land_underwriting", {})
    min_front = float(lc.get("min_frontage_ft", 50))
    ideal_front = float(lc.get("ideal_frontage_ft", 100))
    score = 55.0

    if signals.legal_road_access is True:
        score += 18
    elif signals.legal_road_access is False or signals.access_type == "no_legal_access":
        score -= 35
    elif signals.seasonal_road:
        score -= 15

    if signals.zoning_hint in ("residential", "rural_residential", "hamlet"):
        score += 12
    elif signals.zoning_hint == "agricultural":
        score -= 5

    front = metrics.frontage_ft
    if front is not None:
        if front < min_front:
            score -= 25
        elif front >= ideal_front:
            score += 10
        else:
            score += 5 * (front - min_front) / max(ideal_front - min_front, 1)

    util_count = len(signals.utilities_at_lot)
    score += min(util_count * 5, 15)

    if signals.topography_hint == "level":
        score += 8
    elif signals.topography_hint == "challenging":
        score -= 12

    if signals.wetland_risk:
        score -= 30
    if signals.floodplain_risk:
        score -= 25
    if signals.conservation_risk:
        score -= 28
    if "explicitly_not_buildable" in signals.red_flags:
        score -= 40

    return _clamp(score)


def score_servicing(signals: LandSignals, financials: LandFinancials, config: dict[str, Any]) -> float:
    """Higher = easier / cheaper to service."""
    price = financials.purchase_price or 1
    ratio = financials.estimated_servicing_cost / price
    score = 70.0
    if ratio > 0.5:
        score -= 35
    elif ratio > 0.35:
        score -= 20
    elif ratio > 0.2:
        score -= 10
    elif ratio < 0.08:
        score += 10

    if len(signals.utilities_at_lot) >= 3:
        score += 15
    if signals.septic_mentioned and "sewer" not in signals.utilities_at_lot:
        score -= 8
    return _clamp(score)


def score_environmental(signals: LandSignals) -> tuple[float, float]:
    """Returns (safety_score 0–100, risk_score 0–100 higher=worse)."""
    risk = 0.0
    if signals.wetland_risk:
        risk += 35
    if signals.floodplain_risk:
        risk += 30
    if signals.conservation_risk:
        risk += 32
    if "environmental" in " ".join(signals.red_flags):
        risk += 15
    risk = _clamp(risk, 0, 100)
    return _clamp(100 - risk), risk


def score_exit_strategies(signals: LandSignals, buildability: float) -> dict[str, float]:
    """Viability per exit path."""
    b = buildability / 100.0
    strategies = {
        "single_family_build": _clamp(85 * b + (10 if signals.zoning_hint == "residential" else 0)),
        "buy_and_hold": _clamp(50 + (15 if signals.distress_language else 0) - (20 if signals.wetland_risk else 0)),
        "severance": _clamp(40 + (35 if signals.severance_hint else 0) + 10 * b),
        "subdivision": _clamp(30 + (25 if signals.severance_hint or signals.development_hint else 0) + 15 * b),
        "recreational_resale": _clamp(60 if signals.land_type == "recreational" else 35),
        "builder_flip": _clamp(70 * b + (12 if len(signals.utilities_at_lot) >= 2 else 0)),
    }
    if signals.land_type == "farmland":
        strategies["single_family_build"] *= 0.6
        strategies["severance"] += 15
    return {k: round(v, 1) for k, v in strategies.items()}


def score_financial(financials: LandFinancials, metrics: LandMetrics, config: dict[str, Any]) -> float:
    """ROI and margin — penalize negative ROI heavily."""
    lc = config.get("land_underwriting", {})
    target_roi = float(lc.get("target_roi_pct", 15))
    score = 50.0
    roi = financials.estimated_roi
    if roi >= target_roi + 10:
        score += 25
    elif roi >= target_roi:
        score += 15
    elif roi >= 5:
        score += 5
    elif roi < 0:
        score -= 30
    else:
        score -= 10

    # Cheap $/acre alone should not inflate score
    if metrics.price_per_acre and metrics.price_per_acre < 3000:
        score -= 8  # often unusable cheap acreage

    margin = financials.estimated_profit / max(financials.estimated_all_in_basis, 1)
    if margin > 0.2:
        score += 10
    elif margin < 0:
        score -= 15

    return _clamp(score)


def score_liquidity(listing_price: float, acres: float | None, config: dict[str, Any]) -> float:
    lc = config.get("land_underwriting", {})
    sweet_min = float(lc.get("liquidity_price_min", 25000))
    sweet_max = float(lc.get("liquidity_price_max", 350000))
    if sweet_min <= listing_price <= sweet_max:
        base = 70
    elif listing_price > sweet_max:
        base = 45
    else:
        base = 55
    if acres and acres > 25:
        base -= 15
    return _clamp(base)


def compute_risk_analysis(signals: LandSignals, financials: LandFinancials) -> dict[str, float]:
    """Risk severity 0–100 per category."""
    servicing_ratio = financials.estimated_servicing_cost / max(financials.purchase_price, 1)
    return {
        "environmental_risk": 80.0 if signals.wetland_risk and signals.conservation_risk else (
            65 if signals.wetland_risk or signals.floodplain_risk else (
                45 if signals.conservation_risk else 15
            )
        ),
        "zoning_risk": 55 if signals.zoning_hint == "agricultural" else (
            40 if not signals.zoning_hint else 20
        ),
        "servicing_risk": _clamp(servicing_ratio * 120, 0, 95),
        "liquidity_risk": 60 if financials.purchase_price > 500000 else 30,
        "approval_risk": 70 if signals.severance_hint and not signals.development_hint else 35,
        "conservation_authority_risk": 75 if signals.conservation_risk else 10,
        "access_risk": 85 if signals.legal_road_access is False else (45 if signals.seasonal_road else 15),
    }


def compute_land_scores(
    signals: LandSignals,
    metrics: LandMetrics,
    financials: LandFinancials,
    config: dict[str, Any],
) -> tuple[LandScores, dict[str, float]]:
    lc = config.get("land_underwriting", {})
    weights = lc.get("score_weights", {})

    build = score_buildability(signals, metrics, config)
    serv = score_servicing(signals, financials, config)
    env_safe, env_risk = score_environmental(signals)
    exits = score_exit_strategies(signals, build)
    exit_avg = sum(exits.values()) / len(exits) if exits else 50.0
    fin = score_financial(financials, metrics, config)
    liq = score_liquidity(financials.purchase_price, metrics.acres, config)

    w_build = float(weights.get("buildability", 0.35))
    w_fin = float(weights.get("financial", 0.25))
    w_exit = float(weights.get("exit_strategy", 0.15))
    w_risk = float(weights.get("risk_inverse", 0.25))

    # Risk inverse uses environmental safety + access
    access_penalty = 0 if signals.legal_road_access is not False else 40
    risk_inverse = _clamp((env_safe + (100 - access_penalty)) / 2)

    composite = (
        build * w_build
        + fin * w_fin
        + exit_avg * w_exit
        + risk_inverse * w_risk
    )

    # Hard penalties
    if signals.legal_road_access is False:
        composite -= 25
    if signals.wetland_risk and signals.floodplain_risk:
        composite -= 20
    if "explicitly_not_buildable" in signals.red_flags:
        composite -= 30
    if financials.estimated_servicing_cost > financials.purchase_price * 0.6:
        composite -= 15

    composite = _clamp(composite)

    scores = LandScores(
        buildability_score=round(build, 1),
        servicing_score=round(serv, 1),
        environmental_score=round(env_safe, 1),
        exit_strategy_score=round(exit_avg, 1),
        financial_score=round(fin, 1),
        liquidity_score=round(liq, 1),
        underwriting_score=round(composite, 1),
        environmental_risk=round(env_risk, 1),
    )
    return scores, exits


def recommendation_from_score(
    score: float,
    signals: LandSignals,
    config: dict[str, Any],
) -> str:
    lc = config.get("land_underwriting", {})
    th = lc.get("thresholds", {})
    strong = float(th.get("strong_candidate", 72))
    investigate = float(th.get("investigate", 48))

    if signals.legal_road_access is False or "explicitly_not_buildable" in signals.red_flags:
        return "PASS"
    if score >= strong:
        return "STRONG_CANDIDATE"
    if score >= investigate:
        return "INVESTIGATE"
    return "PASS"
