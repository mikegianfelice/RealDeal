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
        margin_of_safety_base=float(pf.get("margin_of_safety_base", 50)),
        margin_of_safety_stress_positive=float(pf.get("margin_of_safety_stress_positive", 25)),
        margin_of_safety_stress_threshold=float(pf.get("margin_of_safety_stress_threshold", 15)),
        margin_of_safety_coc=float(pf.get("margin_of_safety_coc", 5)),
        margin_of_safety_dscr=float(pf.get("margin_of_safety_dscr", 5)),
    )


def get_rent_estimation_params(config: dict[str, Any]) -> RentEstimationParams:
    """Extract rent estimation params from config (default tier)."""
    re = config.get("rent_estimation", {})
    default = re.get("default", {})
    if isinstance(default, dict):
        base = float(default.get("base", 1200))
        per_bedroom = float(default.get("per_bedroom", 800))
    else:
        base = float(re.get("base", 1200))
        per_bedroom = float(re.get("per_bedroom", 800))
    return RentEstimationParams(
        base=base,
        per_bedroom=per_bedroom,
        min_rent=float(re.get("min_rent", 500)),
        max_rent=float(re.get("max_rent", 15000)),
    )


def _build_city_to_tier(config: dict[str, Any]) -> dict[str, str]:
    """Build city -> tier map from cities config (case-insensitive keys)."""
    city_to_tier: dict[str, str] = {}
    cities_cfg = config.get("cities", {})
    for tier, city_list in cities_cfg.items():
        if isinstance(city_list, list):
            for city in city_list:
                if isinstance(city, str):
                    city_to_tier[city.strip().lower()] = tier
    return city_to_tier


def get_rent_estimation_params_for_city(
    config: dict[str, Any], city: str
) -> RentEstimationParams:
    """Get rent estimation params for a specific city (tiered by city tier)."""
    re = config.get("rent_estimation", {})
    min_rent = float(re.get("min_rent", 500))
    max_rent = float(re.get("max_rent", 15000))

    city_to_tier = _build_city_to_tier(config)
    tier_params = re.get("tiers", {})
    default_params = re.get("default", {})

    city_key = (city or "").strip().lower()
    tier = city_to_tier.get(city_key)
    params = tier_params.get(tier, default_params) if tier else default_params
    if not isinstance(params, dict):
        params = default_params if isinstance(default_params, dict) else {"base": 1200, "per_bedroom": 800}
    base = float(params.get("base", 1200))
    per_bedroom = float(params.get("per_bedroom", 800))

    return RentEstimationParams(
        base=base,
        per_bedroom=per_bedroom,
        min_rent=min_rent,
        max_rent=max_rent,
    )


def get_all_cities(config: dict[str, Any], tiers: tuple[str, ...] | None = None) -> list[str]:
    """Flatten all tier cities into a single list."""
    cities: list[str] = []
    if tiers is not None:
        tier_names = tiers
    else:
        # Dynamically include all tiers defined in config
        tier_names = tuple(config.get("cities", {}).keys())
    for tier in tier_names:
        cities.extend(config.get("cities", {}).get(tier, []))
    return cities


def get_city_province_map(config: dict[str, Any]) -> dict[str, str]:
    """Map city name -> province code based on tier_provinces config.

    Tiers not listed in tier_provinces default to the top-level 'province' value (e.g. ON).
    """
    default_province = config.get("province", "ON")
    tier_provinces = config.get("tier_provinces", {})
    city_to_province: dict[str, str] = {}
    cities_cfg = config.get("cities", {})
    for tier, city_list in cities_cfg.items():
        province = tier_provinces.get(tier, default_province)
        if isinstance(city_list, list):
            for city in city_list:
                if isinstance(city, str):
                    city_to_province[city.strip()] = province
    return city_to_province
