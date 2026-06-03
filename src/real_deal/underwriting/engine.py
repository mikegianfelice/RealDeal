"""Underwriting engine for cash-flow analysis."""

from __future__ import annotations

from typing import List

from ..models import (
    Listing,
    PassFailThresholds,
    RentEstimationParams,
    StressTestParams,
    UnderwritingAssumptions,
    UnderwritingResult,
)
from .rent import estimate_rent_with_details
from .signals import extract_signals, compute_confidence_score, signals_to_dict
from ..config import (
    _build_city_to_tier,
    get_pass_fail_thresholds,
    get_rent_estimation_params_for_city,
    get_stress_params,
    get_underwriting_assumptions,
    get_underwriting_assumptions_for_city,
    load_config,
)


class UnderwritingEngine:
    """
    Conservative cash-flow underwriting engine.
    Supports base case + stress test, margin-of-safety score, pass/fail thresholds.

    Cash flow uses NOI (incl. property tax & insurance) minus principal+interest only,
    so tax/insurance are not double-counted against PITI.
    """

    def __init__(
        self,
        assumptions: UnderwritingAssumptions | None = None,
        stress_params: StressTestParams | None = None,
        thresholds: PassFailThresholds | None = None,
        rent_params: dict | None = None,
        config: dict | None = None,
    ) -> None:
        cfg = config or load_config()
        self._config = cfg
        self._city_to_tier = _build_city_to_tier(cfg)
        self.assumptions = assumptions or get_underwriting_assumptions(cfg)
        self.stress_params = stress_params or get_stress_params(cfg)
        self.thresholds = thresholds or get_pass_fail_thresholds(cfg)
        self._rent_params_override = rent_params

    def underwrite(self, listing: Listing) -> UnderwritingResult:
        """Run full underwriting on a listing."""
        assumptions = get_underwriting_assumptions_for_city(
            self._config, listing.city, self._city_to_tier
        )
        rent_p = get_rent_estimation_params_for_city(
            self._config, listing.city, self._city_to_tier
        )
        if self._rent_params_override:
            o = self._rent_params_override
            rent_p = RentEstimationParams(
                base=o.get("base", rent_p.base),
                per_bedroom=o.get("per_bedroom", rent_p.per_bedroom),
                min_rent=o.get("min_rent", rent_p.min_rent),
                max_rent=o.get("max_rent", rent_p.max_rent),
                max_bedrooms_single_unit=o.get(
                    "max_bedrooms_single_unit", rent_p.max_bedrooms_single_unit
                ),
                max_bedrooms_per_unit=o.get("max_bedrooms_per_unit", rent_p.max_bedrooms_per_unit),
                sfh_base=o.get("sfh_base", rent_p.sfh_base),
                sfh_per_bedroom=o.get("sfh_per_bedroom", rent_p.sfh_per_bedroom),
                sfh_max_rent=o.get("sfh_max_rent", rent_p.sfh_max_rent),
                sfh_max_bedrooms=o.get("sfh_max_bedrooms", rent_p.sfh_max_bedrooms),
                sfh_price_tiers=o.get("sfh_price_tiers", rent_p.sfh_price_tiers),
                sfh_quality_min_price=o.get("sfh_quality_min_price", rent_p.sfh_quality_min_price),
                sfh_quality_bonus_per_hit=o.get(
                    "sfh_quality_bonus_per_hit", rent_p.sfh_quality_bonus_per_hit
                ),
                sfh_quality_bonus_max=o.get("sfh_quality_bonus_max", rent_p.sfh_quality_bonus_max),
            )

        signals = extract_signals(listing.description, listing.raw_payload)
        rent_monthly, rent_meta = estimate_rent_with_details(
            listing,
            rent_p,
            unit_count_hint=signals.unit_count_hint,
            multi_unit_signal=signals.multi_unit_signal,
        )
        rent_was_explicit = rent_meta.get("rent_was_explicit", False)
        condo_fee = signals.condo_fee_monthly or 0.0
        utilities_monthly = self._utilities_monthly(signals, assumptions)

        # Base case
        noi = self._noi(
            rent_monthly,
            listing.price,
            assumptions=assumptions,
            condo_fee_monthly=condo_fee,
            utilities_monthly=utilities_monthly,
        )
        monthly_pi = self._monthly_pi(listing.price, assumptions=assumptions)
        cashflow = (noi / 12) - monthly_pi
        cap_rate = noi / listing.price if listing.price > 0 else 0
        coc = self._cash_on_cash(noi, monthly_pi, listing.price, assumptions=assumptions)
        dscr = self._dscr(noi, listing.price, assumptions=assumptions)

        # Stress case
        stress_rent = rent_monthly * (1 - self.stress_params.rent_haircut)
        stress_vacancy = assumptions.vacancy_rate + self.stress_params.vacancy_bump
        stress_maint = assumptions.maintenance_rate + self.stress_params.maintenance_bump
        stress_capex = assumptions.capex_rate + self.stress_params.capex_bump
        stress_noi = self._noi(
            stress_rent,
            listing.price,
            assumptions=assumptions,
            vacancy_override=stress_vacancy,
            maintenance_rate_override=stress_maint,
            capex_rate_override=stress_capex,
            condo_fee_monthly=condo_fee,
            utilities_monthly=utilities_monthly,
        )
        stress_interest = assumptions.interest_rate + self.stress_params.interest_rate_bump
        stress_monthly_pi = self._monthly_pi(
            listing.price,
            assumptions=assumptions,
            interest_override=stress_interest,
        )
        stress_cashflow = (stress_noi / 12) - stress_monthly_pi
        stress_dscr = self._dscr(
            stress_noi,
            listing.price,
            assumptions=assumptions,
            interest_override=stress_interest,
        )

        mos = self._margin_of_safety(cashflow, stress_cashflow, coc, dscr, stress_dscr)
        passed, flags = self._evaluate(
            listing, cashflow, stress_cashflow, coc, dscr, stress_dscr
        )

        confidence_score, confidence_notes = compute_confidence_score(
            listing, signals, rent_was_explicit
        )
        signals_dict = signals_to_dict(signals)
        signals_dict["explicit_rent_found"] = rent_was_explicit
        signals_dict.update(
            {k: v for k, v in rent_meta.items() if k != "rent_was_explicit"}
        )
        if utilities_monthly == 0 and signals.tenant_pays_utilities:
            signals_dict["utilities_assumption"] = "tenant_pays"

        return UnderwritingResult(
            listing_id=listing.id,
            listing=listing,
            rent_monthly=rent_monthly,
            noi_annual=noi,
            cashflow_monthly=cashflow,
            cap_rate=cap_rate,
            cash_on_cash=coc,
            dscr=dscr,
            stress_rent_monthly=stress_rent,
            stress_cashflow_monthly=stress_cashflow,
            margin_of_safety_score=mos,
            passed=passed,
            reason_flags=flags,
            assumptions=assumptions,
            stress_params=self.stress_params,
            thresholds=self.thresholds,
            confidence_score=confidence_score,
            signals=signals_dict,
            confidence_notes=confidence_notes,
        )

    def underwrite_many(self, listings: List[Listing]) -> List[UnderwritingResult]:
        """Underwrite multiple listings."""
        return [self.underwrite(l) for l in listings]

    @staticmethod
    def _utilities_monthly(signals, assumptions: UnderwritingAssumptions) -> float:
        """Landlord-paid utilities; zero when tenant pays."""
        if signals.tenant_pays_utilities:
            return 0.0
        return assumptions.utilities_monthly

    def _noi(
        self,
        rent_monthly: float,
        price: float,
        assumptions: UnderwritingAssumptions | None = None,
        vacancy_override: float | None = None,
        maintenance_rate_override: float | None = None,
        capex_rate_override: float | None = None,
        condo_fee_monthly: float = 0.0,
        utilities_monthly: float | None = None,
    ) -> float:
        """Net Operating Income (annual). Includes property tax and insurance."""
        uw = assumptions or self.assumptions
        vacancy = uw.vacancy_rate if vacancy_override is None else vacancy_override
        maint_rate = (
            uw.maintenance_rate
            if maintenance_rate_override is None
            else maintenance_rate_override
        )
        capex_rate = uw.capex_rate if capex_rate_override is None else capex_rate_override
        utils = uw.utilities_monthly if utilities_monthly is None else utilities_monthly

        egi = rent_monthly * 12 * (1 - vacancy)
        mgmt = egi * uw.management_rate
        maint = egi * maint_rate
        capex = egi * capex_rate
        prop_tax = price * uw.property_tax_rate_annual
        insurance = uw.insurance_monthly * 12
        utils_annual = utils * 12
        snow_lawn = uw.snow_lawn_monthly * 12
        condo_annual = condo_fee_monthly * 12
        return egi - mgmt - maint - capex - prop_tax - insurance - utils_annual - snow_lawn - condo_annual

    @staticmethod
    def _cmhc_premium_rate(down_payment_rate: float) -> float:
        """Return approximate CMHC mortgage insurance premium rate."""
        if down_payment_rate >= 0.20:
            return 0.0
        if down_payment_rate >= 0.15:
            return 0.028
        if down_payment_rate >= 0.10:
            return 0.031
        return 0.04

    def _apply_cmhc(self, principal: float, assumptions: UnderwritingAssumptions) -> float:
        """Add CMHC insurance premium to *principal* when applicable."""
        premium = self._cmhc_premium_rate(assumptions.down_payment_rate)
        return principal * (1 + premium)

    def _monthly_pi(
        self,
        price: float,
        assumptions: UnderwritingAssumptions | None = None,
        interest_override: float | None = None,
    ) -> float:
        """Monthly principal + interest (CMHC-adjusted principal when applicable)."""
        uw = assumptions or self.assumptions
        rate = uw.interest_rate if interest_override is None else interest_override
        down = price * uw.down_payment_rate
        principal = self._apply_cmhc(price - down, uw)
        n = uw.amort_years * 12
        r = rate / 12
        if r == 0:
            return principal / n
        return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)

    def _cash_on_cash(
        self,
        noi: float,
        monthly_pi: float,
        price: float,
        assumptions: UnderwritingAssumptions | None = None,
    ) -> float:
        """Annual cash-on-cash return."""
        uw = assumptions or self.assumptions
        closing = price * uw.closing_cost_rate
        down = price * uw.down_payment_rate
        total_in = down + closing
        annual_cf = (noi / 12 - monthly_pi) * 12
        return annual_cf / total_in if total_in > 0 else 0

    def _dscr(
        self,
        noi: float,
        price: float,
        assumptions: UnderwritingAssumptions | None = None,
        interest_override: float | None = None,
    ) -> float:
        """Debt Service Coverage Ratio (NOI / annual P&I)."""
        uw = assumptions or self.assumptions
        monthly_pi = self._monthly_pi(price, assumptions=uw, interest_override=interest_override)
        annual_dsc = monthly_pi * 12
        return noi / annual_dsc if annual_dsc > 0 else 0

    def _margin_of_safety(
        self,
        cashflow: float,
        stress_cashflow: float,
        coc: float,
        dscr: float,
        stress_dscr: float = 0.0,
    ) -> float:
        """Margin of safety score 0-100."""
        score = self.thresholds.margin_of_safety_base
        if stress_cashflow > 0:
            score += self.thresholds.margin_of_safety_stress_positive
        if stress_cashflow >= self.thresholds.min_cashflow_monthly:
            score += self.thresholds.margin_of_safety_stress_threshold
        if coc >= self.thresholds.min_cash_on_cash:
            score += self.thresholds.margin_of_safety_coc
        conservative_dscr = min(dscr, stress_dscr) if stress_dscr else dscr
        if conservative_dscr >= self.thresholds.min_dscr:
            score += self.thresholds.margin_of_safety_dscr
        return min(100, max(0, score))

    def _evaluate(
        self,
        listing: Listing,
        cashflow: float,
        stress_cashflow: float,
        coc: float,
        dscr: float,
        stress_dscr: float = 0.0,
    ) -> tuple[bool, list[str]]:
        """Evaluate pass/fail and build reason flags."""
        flags: list[str] = []
        if cashflow >= self.thresholds.min_cashflow_monthly:
            flags.append("PASS: cashflow")
        else:
            flags.append(
                f"FAIL: cashflow ${cashflow:.0f} < ${self.thresholds.min_cashflow_monthly:.0f}"
            )

        if stress_cashflow >= 0:
            flags.append("PASS: stress_cashflow positive")
        else:
            flags.append(f"FAIL: stress_cashflow ${stress_cashflow:.0f}")

        if coc >= self.thresholds.min_cash_on_cash:
            flags.append(f"PASS: CoC {coc:.2%}")
        else:
            flags.append(f"FAIL: CoC {coc:.2%} < {self.thresholds.min_cash_on_cash:.2%}")

        if dscr >= self.thresholds.min_dscr:
            flags.append(f"PASS: DSCR {dscr:.2f}")
        else:
            flags.append(f"FAIL: DSCR {dscr:.2f} < {self.thresholds.min_dscr:.2f}")

        if stress_dscr:
            if stress_dscr >= self.thresholds.min_dscr:
                flags.append(f"PASS: stress_DSCR {stress_dscr:.2f}")
            else:
                flags.append(
                    f"FAIL: stress_DSCR {stress_dscr:.2f} < {self.thresholds.min_dscr:.2f}"
                )

        passed = (
            cashflow >= self.thresholds.min_cashflow_monthly
            and stress_cashflow >= 0
            and coc >= self.thresholds.min_cash_on_cash
            and dscr >= self.thresholds.min_dscr
        )
        if self.thresholds.require_stress_dscr and stress_dscr:
            passed = passed and stress_dscr >= self.thresholds.min_dscr

        return passed, flags
