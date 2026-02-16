"""Data models for listings and underwriting results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Listing:
    """Normalized listing schema (source-agnostic)."""

    id: str
    source: str
    address: str
    city: str
    province: str
    postal_code: str
    price: float
    bedrooms: int
    bathrooms: float
    property_type: str
    description: str
    url: str
    raw_payload: dict[str, Any]
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "address": self.address,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "price": self.price,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "property_type": self.property_type,
            "description": self.description,
            "url": self.url,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass
class UnderwritingAssumptions:
    """Underwriting assumptions (from config or overrides)."""

    vacancy_rate: float
    management_rate: float
    maintenance_rate: float
    capex_rate: float
    insurance_monthly: float
    utilities_monthly: float
    snow_lawn_monthly: float
    closing_cost_rate: float
    down_payment_rate: float
    interest_rate: float
    amort_years: int
    property_tax_rate_annual: float


@dataclass
class StressTestParams:
    """Stress test parameters."""

    rent_haircut: float
    interest_rate_bump: float
    vacancy_bump: float


@dataclass
class PassFailThresholds:
    """Pass/fail thresholds for deals."""

    min_cashflow_monthly: float
    min_dscr: float
    min_cash_on_cash: float
    margin_of_safety_base: float
    margin_of_safety_stress_positive: float
    margin_of_safety_stress_threshold: float
    margin_of_safety_coc: float
    margin_of_safety_dscr: float


@dataclass
class RentEstimationParams:
    """Rent estimation parameters."""

    base: float
    per_bedroom: float
    min_rent: float
    max_rent: float


@dataclass
class UnderwritingResult:
    """Full underwriting result for a listing."""

    listing_id: str
    listing: Listing
    rent_monthly: float
    noi_annual: float
    cashflow_monthly: float
    cap_rate: float
    cash_on_cash: float
    dscr: float
    stress_rent_monthly: float
    stress_cashflow_monthly: float
    margin_of_safety_score: float
    passed: bool
    reason_flags: list[str]
    assumptions: UnderwritingAssumptions
    stress_params: StressTestParams
    thresholds: PassFailThresholds
    # Signals + confidence (additive fields)
    confidence_score: float = 0.5
    signals: dict[str, Any] = field(default_factory=dict)
    confidence_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "listing": self.listing.to_dict(),
            "rent_monthly": self.rent_monthly,
            "noi_annual": self.noi_annual,
            "cashflow_monthly": self.cashflow_monthly,
            "cap_rate": self.cap_rate,
            "cash_on_cash": self.cash_on_cash,
            "dscr": self.dscr,
            "stress_rent_monthly": self.stress_rent_monthly,
            "stress_cashflow_monthly": self.stress_cashflow_monthly,
            "margin_of_safety_score": self.margin_of_safety_score,
            "passed": self.passed,
            "reason_flags": self.reason_flags,
            "assumptions": {
                "vacancy_rate": self.assumptions.vacancy_rate,
                "management_rate": self.assumptions.management_rate,
                "maintenance_rate": self.assumptions.maintenance_rate,
                "capex_rate": self.assumptions.capex_rate,
                "insurance_monthly": self.assumptions.insurance_monthly,
                "utilities_monthly": self.assumptions.utilities_monthly,
                "snow_lawn_monthly": self.assumptions.snow_lawn_monthly,
                "closing_cost_rate": self.assumptions.closing_cost_rate,
                "down_payment_rate": self.assumptions.down_payment_rate,
                "interest_rate": self.assumptions.interest_rate,
                "amort_years": self.assumptions.amort_years,
                "property_tax_rate_annual": self.assumptions.property_tax_rate_annual,
            },
            "stress_params": {
                "rent_haircut": self.stress_params.rent_haircut,
                "interest_rate_bump": self.stress_params.interest_rate_bump,
                "vacancy_bump": self.stress_params.vacancy_bump,
            },
            "thresholds": {
                "min_cashflow_monthly": self.thresholds.min_cashflow_monthly,
                "min_dscr": self.thresholds.min_dscr,
                "min_cash_on_cash": self.thresholds.min_cash_on_cash,
            },
            "confidence_score": self.confidence_score,
            "signals": self.signals,
            "confidence_notes": self.confidence_notes,
        }
