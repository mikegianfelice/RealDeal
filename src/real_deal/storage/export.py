"""Export underwriting results to CSV and JSON."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import UnderwritingResult


def _serialize(obj: Any) -> Any:
    """JSON serializer for datetime and other objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def export_csv(results: list[UnderwritingResult], path: Path | str) -> None:
    """Export ranked deals to CSV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "rank",
        "listing_id",
        "address",
        "city",
        "price",
        "bedrooms",
        "rent_monthly",
        "cashflow_monthly",
        "stress_cashflow_monthly",
        "cap_rate",
        "cash_on_cash",
        "dscr",
        "margin_of_safety_score",
        "passed",
        "reason_flags",
        "url",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, r in enumerate(results, 1):
            writer.writerow({
                "rank": i,
                "listing_id": r.listing_id,
                "address": r.listing.address,
                "city": r.listing.city,
                "price": r.listing.price,
                "bedrooms": r.listing.bedrooms,
                "rent_monthly": r.rent_monthly,
                "cashflow_monthly": r.cashflow_monthly,
                "stress_cashflow_monthly": r.stress_cashflow_monthly,
                "cap_rate": r.cap_rate,
                "cash_on_cash": r.cash_on_cash,
                "dscr": r.dscr,
                "margin_of_safety_score": r.margin_of_safety_score,
                "passed": r.passed,
                "reason_flags": " | ".join(r.reason_flags),
                "url": r.listing.url,
            })


def export_json(results: list[UnderwritingResult], path: Path | str) -> None:
    """Export full underwriting details to JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "run_at": datetime.utcnow().isoformat(),
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=_serialize)
