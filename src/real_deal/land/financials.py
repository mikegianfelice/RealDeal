"""Land-specific financial modeling."""

from __future__ import annotations

from typing import Any

from ..models import Listing
from .models import LandFinancials, LandMetrics, LandSignals


def _cfg(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("land_underwriting", {})


def estimate_servicing_cost(
    signals: LandSignals,
    metrics: LandMetrics,
    config: dict[str, Any],
) -> float:
    """Estimate utility / servicing capital cost."""
    lc = _cfg(config)
    frontage = metrics.frontage_ft or lc.get("default_frontage_ft", 75)
    rates = lc.get("servicing_cost_per_ft_frontage", {})
    has_muni = "sewer" in signals.utilities_at_lot and "water" in signals.utilities_at_lot
    has_hydro = "hydro" in signals.utilities_at_lot

    if has_muni and has_hydro:
        return float(lc.get("servicing_already_connected", 5000))

    if has_hydro or len(signals.utilities_at_lot) >= 2:
        rate = float(rates.get("partial", 65))
        base = frontage * rate
    elif signals.land_type in ("vacant_residential_lot", "development_land"):
        rate = float(rates.get("full_urban", 120))
        base = frontage * rate
    elif signals.access_type == "seasonal_road" or signals.land_type == "raw_land":
        rate = float(rates.get("remote", 45))
        base = frontage * rate + float(lc.get("road_upgrade_allowance", 35000))
    else:
        rate = float(rates.get("rural", 85))
        base = frontage * rate

    if signals.septic_mentioned or (signals.septic_mentioned is None and "sewer" not in signals.utilities_at_lot):
        base += float(lc.get("septic_allowance", 25000))

    if signals.wetland_risk or signals.conservation_risk:
        base *= float(lc.get("environmental_servicing_multiplier", 1.35))

    return round(base, 0)


def estimate_resale_value(
    listing: Listing,
    metrics: LandMetrics,
    signals: LandSignals,
    config: dict[str, Any],
    city_tier: str = "tier_2",
) -> float:
    """Heuristic finished-lot / land resale value (not full development pro-forma)."""
    lc = _cfg(config)
    acres = metrics.acres or 0.5
    per_acre_table = lc.get("build_ready_value_per_acre", {})
    base_per_acre = float(per_acre_table.get(city_tier, per_acre_table.get("tier_2", 35000)))

    multipliers = lc.get("land_type_value_multipliers", {})
    mult = float(multipliers.get(signals.land_type, multipliers.get("default", 1.0)))

    if signals.wetland_risk or signals.conservation_risk:
        mult *= 0.55
    if signals.legal_road_access is False:
        mult *= 0.45
    if len(signals.utilities_at_lot) >= 3:
        mult *= 1.15
    if signals.severance_hint:
        mult *= 1.08  # upside is uncertain until approval

    # Large parcels: only a portion at build-ready rates; balance at raw land value
    raw_mult = float(lc.get("raw_acreage_value_fraction", 0.35))
    buildable_cap = float(lc.get("buildable_acre_cap", 5))
    if signals.severance_hint and acres > buildable_cap:
        buildable_cap = float(lc.get("severance_buildable_acre_cap", 2))
        raw_mult = min(raw_mult, float(lc.get("severance_unapproved_raw_fraction", 0.18)))
    if acres > buildable_cap and signals.land_type in (
        "farmland",
        "raw_land",
        "severance_opportunity",
    ):
        value = (
            buildable_cap * base_per_acre * mult
            + (acres - buildable_cap) * base_per_acre * raw_mult
        )
    else:
        value = acres * base_per_acre * mult

    if metrics.frontage_ft and metrics.frontage_ft >= 100:
        value *= 1.08

    price = listing.price or 0
    if (
        signals.land_type in ("vacant_residential_lot", "development_land")
        and len(signals.utilities_at_lot) >= 3
    ):
        floor = price * float(lc.get("serviced_lot_resale_multiple", 1.32))
        value = max(value, floor)

    return round(max(value, price * 0.85), 0)


def compute_land_financials(
    listing: Listing,
    metrics: LandMetrics,
    signals: LandSignals,
    config: dict[str, Any],
    city_tier: str = "tier_2",
) -> LandFinancials:
    """All-in basis, ROI, and carrying costs."""
    lc = _cfg(config)
    price = float(listing.price or 0)
    hold_years = float(lc.get("max_hold_years", 3))
    closing_rate = float(lc.get("closing_cost_rate", 0.025))
    closing = price * closing_rate
    legal = float(lc.get("legal_survey_cost", 2500)) + float(lc.get("solicitor_closing", 1500))
    servicing = estimate_servicing_cost(signals, metrics, config)

    tax_rate = float(lc.get("annual_property_tax_rate", 0.011))
    ins_per_acre = float(lc.get("annual_insurance_per_acre", 150))
    acres = metrics.acres or 0.5
    carrying_annual = price * tax_rate + acres * ins_per_acre
    interest_rate = float(lc.get("interest_rate", 0.075))
    carrying_total = carrying_annual * hold_years + price * interest_rate * hold_years * 0.5

    all_in = price + closing + legal + servicing + carrying_total
    resale = estimate_resale_value(listing, metrics, signals, config, city_tier)
    profit = resale - all_in
    roi = (profit / all_in * 100) if all_in > 0 else 0.0
    ann_return: float | None = None
    if all_in > 0 and hold_years > 0:
        try:
            ann_return = ((resale / all_in) ** (1 / hold_years) - 1) * 100
        except (ValueError, ZeroDivisionError):
            ann_return = None

    return LandFinancials(
        purchase_price=price,
        closing_costs=round(closing, 0),
        estimated_servicing_cost=servicing,
        legal_survey=legal,
        carrying_cost_annual=round(carrying_annual, 0),
        estimated_all_in_basis=round(all_in, 0),
        estimated_resale_value=resale,
        estimated_profit=round(profit, 0),
        estimated_roi=round(roi, 1),
        annualized_return=round(ann_return, 1) if ann_return is not None else None,
        hold_years=hold_years,
    )
