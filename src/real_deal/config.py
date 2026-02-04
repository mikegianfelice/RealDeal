"""Configuration loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import (
    PassFailThresholds,
    RentEstimationParams,
    StressTestParams,
    UnderwritingAssumptions,
)


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load config from YAML file."""
    path = Path(config_path) if config_path else Path(__file__).parent.parent.parent / "config.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def get_underwriting_assumptions(config: dict[str, Any]) -> UnderwritingAssumptions:
    """Extract underwriting assumptions from config."""
    uw = config.get("underwriting", {})
    return UnderwritingAssumptions(
        vacancy_rate=float(uw.get("vacancy_rate", 0.06)),
        management_rate=float(uw.get("management_rate", 0.08)),
        maintenance_rate=float(uw.get("maintenance_rate", 0.05)),
        capex_rate=float(uw.get("capex_rate", 0.05)),
        insurance_monthly=float(uw.get("insurance_monthly", 150)),
        utilities_monthly=float(uw.get("utilities_monthly", 250)),
        snow_lawn_monthly=float(uw.get("snow_lawn_monthly", 75)),
        closing_cost_rate=float(uw.get("closing_cost_rate", 0.02)),
        down_payment_rate=float(uw.get("down_payment_rate", 0.20)),
        interest_rate=float(uw.get("interest_rate", 0.055)),
        amort_years=int(uw.get("amort_years", 30)),
        property_tax_rate_annual=float(uw.get("property_tax_rate_annual", 0.011)),
    )


def get_stress_params(config: dict[str, Any]) -> StressTestParams:
    """Extract stress test params from config."""
    st = config.get("stress_test", {})
    return StressTestParams(
        rent_haircut=float(st.get("rent_haircut", 0.07)),
        interest_rate_bump=float(st.get("interest_rate_bump", 0.01)),
        vacancy_bump=float(st.get("vacancy_bump", 0.02)),
    )


def get_pass_fail_thresholds(config: dict[str, Any]) -> PassFailThresholds:
    """Extract pass/fail thresholds from config."""
    pf = config.get("pass_fail", {})
    return PassFailThresholds(
        min_cashflow_monthly=float(pf.get("min_cashflow_monthly", 150)),
        min_dscr=float(pf.get("min_dscr", 1.15)),
        min_cash_on_cash=float(pf.get("min_cash_on_cash", 0.08)),
    )


def get_rent_estimation_params(config: dict[str, Any]) -> RentEstimationParams:
    """Extract rent estimation params from config."""
    re = config.get("rent_estimation", {})
    return RentEstimationParams(
        base=float(re.get("base", 1200)),
        per_bedroom=float(re.get("per_bedroom", 850)),
    )


def get_all_cities(config: dict[str, Any], tiers: tuple[str, ...] | None = None) -> list[str]:
    """Flatten all tier cities into a single list."""
    cities: list[str] = []
    tier_names = tiers or ("tier_1", "tier_2", "tier_3", "bruce_county")
    for tier in tier_names:
        cities.extend(config.get("cities", {}).get(tier, []))
    return cities
