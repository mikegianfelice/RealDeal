"""Configuration loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import (
    PassFailThresholds,
    RentEstimationParams,
    SfhPriceTier,
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
        maintenance_bump=float(st.get("maintenance_bump", 0.0)),
        capex_bump=float(st.get("capex_bump", 0.0)),
    )


def get_export_min_cashflow_monthly(config: dict[str, Any]) -> float:
    """Minimum base-case monthly cash flow for CSV/JSON export and report display."""
    ef = config.get("export_filters", {})
    if "min_cashflow_monthly" in ef:
        return float(ef["min_cashflow_monthly"])
    return float(config.get("pass_fail", {}).get("min_cashflow_monthly", 150))


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
        require_stress_dscr=bool(pf.get("require_stress_dscr", False)),
    )


def _rent_global_bounds(config: dict[str, Any]) -> dict[str, float | int]:
    """Shared rent_estimation bounds and bedroom caps from config."""
    re = config.get("rent_estimation", {})
    return {
        "min_rent": float(re.get("min_rent", 500)),
        "max_rent": float(re.get("max_rent", 15000)),
        "max_bedrooms_single_unit": int(re.get("max_bedrooms_single_unit", 4)),
        "max_bedrooms_per_unit": int(re.get("max_bedrooms_per_unit", 3)),
    }


def _parse_sfh_price_tiers(tier_sfh: dict[str, Any]) -> tuple[SfhPriceTier, ...]:
    """Parse descending price-tier overrides for SFH rent formula."""
    raw = tier_sfh.get("price_tiers", [])
    tiers: list[SfhPriceTier] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict) or "min_price" not in item:
                continue
            tiers.append(
                SfhPriceTier(
                    min_price=float(item["min_price"]),
                    base=float(item["base"]) if "base" in item else None,
                    per_bedroom=float(item["per_bedroom"]) if "per_bedroom" in item else None,
                    max_rent=float(item["max_rent"]) if "max_rent" in item else None,
                )
            )
    return tuple(sorted(tiers, key=lambda t: t.min_price, reverse=True))


def _sfh_rent_params(rent_cfg: dict[str, Any], tier: str | None) -> dict[str, Any]:
    """Single-family rent formula params for a city tier."""
    sfh_cfg = rent_cfg.get("single_family", {})
    default = sfh_cfg.get("default", {}) if isinstance(sfh_cfg.get("default"), dict) else {}
    tier_sfh = sfh_cfg.get("tiers", {}).get(tier, {}) if tier else {}
    merged = {**default, **tier_sfh} if isinstance(tier_sfh, dict) else default
    quality = merged.get("quality_bonus", {})
    if not isinstance(quality, dict):
        quality = {}
    return {
        "sfh_base": float(merged.get("base", 1200)),
        "sfh_per_bedroom": float(merged.get("per_bedroom", 350)),
        "sfh_max_rent": float(merged.get("max_rent", 2500)),
        "sfh_max_bedrooms": int(merged.get("max_bedrooms", 4)),
        "sfh_price_tiers": _parse_sfh_price_tiers(merged),
        "sfh_quality_min_price": float(quality.get("min_price", merged.get("quality_min_price", 0))),
        "sfh_quality_bonus_per_hit": float(quality.get("per_keyword", 150)),
        "sfh_quality_bonus_max": float(quality.get("max_bonus", 0)),
    }


def _rent_params_from_parts(
    bounds: dict[str, float | int],
    base: float,
    per_bedroom: float,
    sfh: dict[str, Any],
) -> RentEstimationParams:
    return RentEstimationParams(
        base=base,
        per_bedroom=per_bedroom,
        min_rent=float(bounds["min_rent"]),
        max_rent=float(bounds["max_rent"]),
        max_bedrooms_single_unit=int(bounds["max_bedrooms_single_unit"]),
        max_bedrooms_per_unit=int(bounds["max_bedrooms_per_unit"]),
        sfh_base=float(sfh["sfh_base"]),
        sfh_per_bedroom=float(sfh["sfh_per_bedroom"]),
        sfh_max_rent=float(sfh["sfh_max_rent"]),
        sfh_max_bedrooms=int(sfh["sfh_max_bedrooms"]),
        sfh_price_tiers=sfh["sfh_price_tiers"],
        sfh_quality_min_price=float(sfh["sfh_quality_min_price"]),
        sfh_quality_bonus_per_hit=float(sfh["sfh_quality_bonus_per_hit"]),
        sfh_quality_bonus_max=float(sfh["sfh_quality_bonus_max"]),
    )


def get_rent_estimation_params(config: dict[str, Any]) -> RentEstimationParams:
    """Extract rent estimation params from config (default tier)."""
    rent_cfg = config.get("rent_estimation", {})
    bounds = _rent_global_bounds(config)
    default = rent_cfg.get("default", {})
    if isinstance(default, dict):
        base = float(default.get("base", 1200))
        per_bedroom = float(default.get("per_bedroom", 800))
    else:
        base = float(rent_cfg.get("base", 1200))
        per_bedroom = float(rent_cfg.get("per_bedroom", 800))
    sfh = _sfh_rent_params(rent_cfg, None)
    return _rent_params_from_parts(bounds, base, per_bedroom, sfh)


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


def get_city_tier(config: dict[str, Any], city: str, city_to_tier: dict[str, str] | None = None) -> str | None:
    """Return tier name for a city, or None if unknown."""
    mapping = city_to_tier if city_to_tier is not None else _build_city_to_tier(config)
    return mapping.get((city or "").strip().lower())


def get_rent_estimation_params_for_city(
    config: dict[str, Any],
    city: str,
    city_to_tier: dict[str, str] | None = None,
) -> RentEstimationParams:
    """Get rent estimation params for a specific city (tiered by city tier)."""
    bounds = _rent_global_bounds(config)
    rent_cfg = config.get("rent_estimation", {})

    tier = get_city_tier(config, city, city_to_tier)
    tier_params = rent_cfg.get("tiers", {})
    default_params = rent_cfg.get("default", {})

    params = tier_params.get(tier, default_params) if tier else default_params
    if not isinstance(params, dict):
        params = default_params if isinstance(default_params, dict) else {"base": 1200, "per_bedroom": 800}
    base = float(params.get("base", 1200))
    per_bedroom = float(params.get("per_bedroom", 800))
    sfh = _sfh_rent_params(rent_cfg, tier)

    return _rent_params_from_parts(bounds, base, per_bedroom, sfh)


def get_underwriting_assumptions_for_city(
    config: dict[str, Any],
    city: str,
    city_to_tier: dict[str, str] | None = None,
) -> UnderwritingAssumptions:
    """Underwriting assumptions with tier overrides for tax and insurance."""
    base = get_underwriting_assumptions(config)
    tier = get_city_tier(config, city, city_to_tier)
    tier_overrides = config.get("assumption_tiers", {})
    overrides = tier_overrides.get(tier, {}) if tier else {}
    if not isinstance(overrides, dict):
        overrides = {}
    return UnderwritingAssumptions(
        vacancy_rate=base.vacancy_rate,
        management_rate=base.management_rate,
        maintenance_rate=base.maintenance_rate,
        capex_rate=base.capex_rate,
        insurance_monthly=float(overrides.get("insurance_monthly", base.insurance_monthly)),
        utilities_monthly=base.utilities_monthly,
        snow_lawn_monthly=base.snow_lawn_monthly,
        closing_cost_rate=base.closing_cost_rate,
        down_payment_rate=base.down_payment_rate,
        interest_rate=base.interest_rate,
        amort_years=base.amort_years,
        property_tax_rate_annual=float(
            overrides.get("property_tax_rate_annual", base.property_tax_rate_annual)
        ),
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
