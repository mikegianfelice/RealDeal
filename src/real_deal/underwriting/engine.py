"""Underwriting engine for cash-flow analysis."""

from __future__ import annotations

import math
from typing import List

from ..models import (
    Listing,
    PassFailThresholds,
    RentEstimationParams,
    StressTestParams,
    UnderwritingAssumptions,
    UnderwritingResult,
)
from .rent import estimate_rent
from ..config import (
    get_pass_fail_thresholds,
    get_rent_estimation_params_for_city,
    get_stress_params,
    get_underwriting_assumptions,
    load_config,
)


class UnderwritingEngine:
    """
    Conservative cash-flow underwriting engine.
    Supports base case + stress test, margin-of-safety score, pass/fail thresholds.
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
        self.assumptions = assumptions or get_underwriting_assumptions(cfg)
        self.stress_params = stress_params or get_stress_params(cfg)
        self.thresholds = thresholds or get_pass_fail_thresholds(cfg)
        self._rent_params_override = rent_params

    def underwrite(self, listing: Listing) -> UnderwritingResult:
        """Run full underwriting on a listing."""
        rent_p = get_rent_estimation_params_for_city(self._config, listing.city)
        if self._rent_params_override:
            rent_p = RentEstimationParams(
                base=self._rent_params_override.get("base", rent_p.base),
                per_bedroom=self._rent_params_override.get("per_bedroom", rent_p.per_bedroom),
                min_rent=self._rent_params_override.get("min_rent", rent_p.min_rent),
                max_rent=self._rent_params_override.get("max_rent", rent_p.max_rent),
            )
        rent_monthly = estimate_rent(listing, rent_p)

        # Base case
        noi = self._noi(rent_monthly, listing.price)
        piti = self._piti(listing.price)
        cashflow = (noi / 12) - piti
        cap_rate = noi / listing.price if listing.price > 0 else 0
        coc = self._cash_on_cash(noi, piti, listing.price)
        dscr = self._dscr(noi, listing.price)

        # Stress case
        stress_rent = rent_monthly * (1 - self.stress_params.rent_haircut)
        stress_vacancy = self.assumptions.vacancy_rate + self.stress_params.vacancy_bump
        stress_noi = self._noi(stress_rent, listing.price, vacancy_override=stress_vacancy)
        stress_interest = self.assumptions.interest_rate + self.stress_params.interest_rate_bump
        stress_piti = self._piti(listing.price, interest_override=stress_interest)
        stress_cashflow = (stress_noi / 12) - stress_piti

        # Margin of safety (0-100): based on how much cushion vs stress
        mos = self._margin_of_safety(cashflow, stress_cashflow, coc, dscr)

        # Pass/fail + reason flags
        passed, flags = self._evaluate(listing, cashflow, stress_cashflow, coc, dscr)

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
            assumptions=self.assumptions,
            stress_params=self.stress_params,
            thresholds=self.thresholds,
        )

    def underwrite_many(self, listings: List[Listing]) -> List[UnderwritingResult]:
        """Underwrite multiple listings."""
        return [self.underwrite(l) for l in listings]

    def _noi(
        self,
        rent_monthly: float,
        price: float,
        vacancy_override: float | None = None,
    ) -> float:
        """Net Operating Income (annual)."""
        vacancy = vacancy_override or self.assumptions.vacancy_rate
        gpi = rent_monthly * 12 * (1 - vacancy)
        mgmt = gpi * self.assumptions.management_rate
        maint = gpi * self.assumptions.maintenance_rate
        capex = gpi * self.assumptions.capex_rate
        prop_tax = price * self.assumptions.property_tax_rate_annual
        insurance = self.assumptions.insurance_monthly * 12
        utils = self.assumptions.utilities_monthly * 12
        snow_lawn = self.assumptions.snow_lawn_monthly * 12
        return gpi - mgmt - maint - capex - prop_tax - insurance - utils - snow_lawn

    def _piti(
        self,
        price: float,
        interest_override: float | None = None,
    ) -> float:
        """Principal + Interest + Taxes + Insurance (monthly)."""
        rate = interest_override or self.assumptions.interest_rate
        down = price * self.assumptions.down_payment_rate
        principal = price - down
        n = self.assumptions.amort_years * 12
        r = rate / 12
        if r == 0:
            pi = principal / n
        else:
            pi = principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
        tax = (price * self.assumptions.property_tax_rate_annual) / 12
        ins = self.assumptions.insurance_monthly
        return pi + tax + ins

    def _cash_on_cash(self, noi: float, piti_monthly: float, price: float) -> float:
        """Annual cash-on-cash return."""
        closing = price * self.assumptions.closing_cost_rate
        down = price * self.assumptions.down_payment_rate
        total_in = down + closing
        annual_cf = (noi / 12 - piti_monthly) * 12
        return annual_cf / total_in if total_in > 0 else 0

    def _dscr(self, noi: float, price: float) -> float:
        """Debt Service Coverage Ratio."""
        down = price * self.assumptions.down_payment_rate
        principal = price - down
        n = self.assumptions.amort_years * 12
        r = self.assumptions.interest_rate / 12
        if r == 0:
            dsc = principal / n
        else:
            dsc = principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
        annual_dsc = dsc * 12
        return noi / annual_dsc if annual_dsc > 0 else 0

    def _margin_of_safety(
        self,
        cashflow: float,
        stress_cashflow: float,
        coc: float,
        dscr: float,
    ) -> float:
        """
        Margin of safety score 0-100.
        Higher = more cushion. Based on:
        - Stress cashflow still positive
        - CoC and DSCR above thresholds
        """
        score = self.thresholds.margin_of_safety_base
        if stress_cashflow > 0:
            score += self.thresholds.margin_of_safety_stress_positive
        if stress_cashflow >= self.thresholds.min_cashflow_monthly:
            score += self.thresholds.margin_of_safety_stress_threshold
        if coc >= self.thresholds.min_cash_on_cash:
            score += self.thresholds.margin_of_safety_coc
        if dscr >= self.thresholds.min_dscr:
            score += self.thresholds.margin_of_safety_dscr
        return min(100, max(0, score))

    def _evaluate(
        self,
        listing: Listing,
        cashflow: float,
        stress_cashflow: float,
        coc: float,
        dscr: float,
    ) -> tuple[bool, list[str]]:
        """Evaluate pass/fail and build reason flags."""
        flags: list[str] = []
        if cashflow >= self.thresholds.min_cashflow_monthly:
            flags.append("PASS: cashflow")
        else:
            flags.append(f"FAIL: cashflow ${cashflow:.0f} < ${self.thresholds.min_cashflow_monthly:.0f}")

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

        passed = (
            cashflow >= self.thresholds.min_cashflow_monthly
            and stress_cashflow >= 0
            and coc >= self.thresholds.min_cash_on_cash
            and dscr >= self.thresholds.min_dscr
        )
        return passed, flags
