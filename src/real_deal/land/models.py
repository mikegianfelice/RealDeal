"""Data models for vacant land underwriting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import Listing


@dataclass
class LandMetrics:
    """Physical / economic attributes parsed from listing."""

    acres: float | None = None
    frontage_ft: float | None = None
    depth_ft: float | None = None
    price_per_acre: float | None = None
    price_per_frontage_ft: float | None = None


@dataclass
class LandSignals:
    """Rule-based signals from listing text and metadata."""

    land_type: str = "unknown"
    zoning_hint: str | None = None
    access_type: str | None = None
    legal_road_access: bool | None = None
    utilities_at_lot: list[str] = field(default_factory=list)
    wetland_risk: bool = False
    floodplain_risk: bool = False
    conservation_risk: bool = False
    severance_hint: bool = False
    development_hint: bool = False
    seasonal_road: bool = False
    buyer_to_verify: bool = False
    distress_language: bool = False
    growth_proximity_hint: bool = False
    septic_mentioned: bool | None = None
    topography_hint: str | None = None
    red_flags: list[str] = field(default_factory=list)
    opportunity_flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class LandFinancials:
    """Land-specific financial estimates."""

    purchase_price: float
    closing_costs: float
    estimated_servicing_cost: float
    legal_survey: float
    carrying_cost_annual: float
    estimated_all_in_basis: float
    estimated_resale_value: float
    estimated_profit: float
    estimated_roi: float
    annualized_return: float | None = None
    hold_years: float = 3.0


@dataclass
class LandScores:
    """Component scores 0–100."""

    buildability_score: float = 0.0
    servicing_score: float = 0.0
    environmental_score: float = 0.0  # higher = safer
    exit_strategy_score: float = 0.0
    financial_score: float = 0.0
    liquidity_score: float = 50.0
    underwriting_score: float = 0.0
    environmental_risk: float = 0.0  # 0–100, higher = riskier


@dataclass
class AIListingAnalysis:
    """Structured output from AI or rule-based fallback."""

    summary: str = ""
    confidence_score: float = 0.0
    extracted_signals: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    used_ai: bool = False


@dataclass
class LandUnderwritingResult:
    """Complete land underwriting output."""

    listing_id: str
    listing: Listing
    metrics: LandMetrics
    signals: LandSignals
    financials: LandFinancials
    scores: LandScores
    exit_strategies: dict[str, float]  # strategy name -> viability 0–100
    risk_analysis: dict[str, float]  # risk category -> 0–100 severity
    ai_analysis: AIListingAnalysis
    recommendation: str  # PASS | INVESTIGATE | STRONG_CANDIDATE
    red_flags: list[str] = field(default_factory=list)
    opportunity_flags: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "listing": self.listing.to_dict(),
            "land_type": self.signals.land_type,
            "metrics": {
                "acres": self.metrics.acres,
                "frontage_ft": self.metrics.frontage_ft,
                "depth_ft": self.metrics.depth_ft,
                "price_per_acre": self.metrics.price_per_acre,
                "price_per_frontage_ft": self.metrics.price_per_frontage_ft,
            },
            "underwriting_score": self.scores.underwriting_score,
            "buildability_score": self.scores.buildability_score,
            "servicing_score": self.scores.servicing_score,
            "environmental_risk": self.scores.environmental_risk,
            "exit_strategy_score": self.scores.exit_strategy_score,
            "estimated_servicing_cost": self.financials.estimated_servicing_cost,
            "estimated_all_in_basis": self.financials.estimated_all_in_basis,
            "estimated_roi": self.financials.estimated_roi,
            "annualized_return": self.financials.annualized_return,
            "recommendation": self.recommendation,
            "ai_summary": self.ai_analysis.summary,
            "ai_confidence": self.ai_analysis.confidence_score,
            "red_flags": self.red_flags,
            "opportunity_flags": self.opportunity_flags,
            "exit_strategies": self.exit_strategies,
            "risk_analysis": self.risk_analysis,
            "report_path": self.report_path,
        }
