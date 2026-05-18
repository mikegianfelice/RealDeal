"""Markdown underwriting report generation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .models import LandUnderwritingResult


def _risk_badge(level: float) -> str:
    if level >= 60:
        return "🔴 High"
    if level >= 35:
        return "🟡 Medium"
    return "🟢 Low"


def generate_land_report(result: LandUnderwritingResult) -> str:
    """Build markdown report body."""
    L = result.listing
    m = result.metrics
    s = result.scores
    f = result.financials
    sig = result.signals
    ai = result.ai_analysis

    lines = [
        f"# Land Underwriting Report",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Recommendation:** `{result.recommendation}`",
        f"**Investment Score:** {s.underwriting_score}/100",
        "",
        "## Property Overview",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Address | {L.address} |",
        f"| Municipality | {L.city} |",
        f"| List Price | ${L.price:,.0f} |" if L.price else "| List Price | — |",
        f"| Land Type | {sig.land_type} |",
        f"| Acres | {m.acres or '—'} |",
        f"| Frontage | {f'{m.frontage_ft:.0f} ft' if m.frontage_ft else '—'} |",
        f"| Price/Acre | ${m.price_per_acre:,.0f} |" if m.price_per_acre else "| Price/Acre | — |",
        f"| Source | [{L.source}]({L.url}) |" if L.url else f"| Source | {L.source} |",
        "",
        "## Listing Summary",
        "",
        (L.description[:2000] + "…") if L.description and len(L.description) > 2000 else (L.description or "_No description provided._"),
        "",
        "## Underwriting Score",
        "",
        f"| Component | Score |",
        f"|-----------|-------|",
        f"| **Overall** | **{s.underwriting_score}** |",
        f"| Buildability | {s.buildability_score} |",
        f"| Servicing | {s.servicing_score} |",
        f"| Environmental (safety) | {s.environmental_score} |",
        f"| Exit Strategy (avg) | {s.exit_strategy_score} |",
        f"| Financial | {s.financial_score} |",
        f"| Liquidity | {s.liquidity_score} |",
        "",
        "## Financial Metrics",
        "",
        f"| Metric | Estimate |",
        f"|--------|----------|",
        f"| All-in Basis | ${f.estimated_all_in_basis:,.0f} |",
        f"| Servicing Cost | ${f.estimated_servicing_cost:,.0f} |",
        f"| Carrying (annual) | ${f.carrying_cost_annual:,.0f} |",
        f"| Est. Resale | ${f.estimated_resale_value:,.0f} |",
        f"| Est. Profit | ${f.estimated_profit:,.0f} |",
        f"| ROI ({f.hold_years:.0f}yr hold) | {f.estimated_roi:.1f}% |",
    ]
    if f.annualized_return is not None:
        lines.append(f"| Annualized Return | {f.annualized_return:.1f}% |")

    lines.extend(
        [
            "",
            "## Risk Analysis",
            "",
        ]
    )
    for name, level in sorted(result.risk_analysis.items(), key=lambda x: -x[1]):
        lines.append(f"- **{name.replace('_', ' ').title()}:** {_risk_badge(level)} ({level:.0f}/100)")

    lines.extend(["", "## Exit Strategy Fit", ""])
    for name, val in sorted(result.exit_strategies.items(), key=lambda x: -x[1]):
        lines.append(f"- {name.replace('_', ' ').title()}: {val:.0f}/100")

    lines.extend(
        [
            "",
            "## AI Insights",
            "",
            f"_{'OpenAI' if ai.used_ai else 'Rule-based'} analysis (confidence {ai.confidence_score:.0%})_",
            "",
            ai.summary or "_No summary._",
            "",
        ]
    )
    if ai.risks:
        lines.extend(["### AI-Detected Risks", ""] + [f"- {r}" for r in ai.risks] + [""])
    if ai.opportunities:
        lines.extend(["### AI-Detected Opportunities", ""] + [f"- {o}" for o in ai.opportunities] + [""])

    lines.extend(["## Red Flags", ""])
    if result.red_flags:
        lines.extend([f"- {r}" for r in result.red_flags])
    else:
        lines.append("_None flagged._")

    lines.extend(["", "## Opportunity Flags", ""])
    if result.opportunity_flags:
        lines.extend([f"- {o}" for o in result.opportunity_flags])
    else:
        lines.append("_None flagged._")

    lines.extend(["", "## Recommended Next Steps", ""])
    if result.next_steps:
        lines.extend([f"1. {step}" for i, step in enumerate(result.next_steps, 1)])
    else:
        lines.append("1. Order title search and confirm legal road access.")
        lines.append("2. Request zoning confirmation from municipality.")
        lines.append("3. Retain surveyor for frontage, wetland, and septic feasibility.")

    lines.extend(
        [
            "",
            "## Final Recommendation",
            "",
            f"**{result.recommendation}** — Composite score {s.underwriting_score}/100.",
            "",
        ]
    )
    return "\n".join(lines)


def save_land_report(
    result: LandUnderwritingResult,
    output_dir: str | Path = "outputs/underwriting",
) -> Path:
    """Write markdown report to disk."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe_id = result.listing_id.replace("/", "_")[:80]
    path = out / f"land_{safe_id}.md"
    path.write_text(generate_land_report(result), encoding="utf-8")
    result.report_path = str(path)
    return path
