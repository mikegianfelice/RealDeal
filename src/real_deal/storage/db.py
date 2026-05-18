"""DuckDB storage for listings_raw and deals_underwritten."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from ..models import Listing, UnderwritingResult

try:
    from ..land.models import LandUnderwritingResult
except ImportError:
    LandUnderwritingResult = None  # type: ignore[misc, assignment]


def _serialize_datetime(obj: Any) -> Any:
    """JSON serializer for datetime objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class Storage:
    """
    DuckDB storage for listings_raw and deals_underwritten.
    """

    def __init__(self, db_path: Path | str = "real_deal.duckdb") -> None:
        self.db_path = Path(db_path)
        self._conn: duckdb.DuckDBPyConnection | None = None

    def _connect(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(self.db_path))
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        conn = self._conn
        conn.execute("""
            CREATE TABLE IF NOT EXISTS listings_raw (
                id TEXT PRIMARY KEY,
                source TEXT,
                address TEXT,
                city TEXT,
                province TEXT,
                postal_code TEXT,
                price REAL,
                bedrooms INTEGER,
                bathrooms REAL,
                property_type TEXT,
                description TEXT,
                url TEXT,
                raw_payload JSON,
                fetched_at TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deals_underwritten (
                run_id TEXT,
                listing_id TEXT,
                rent_monthly REAL,
                noi_annual REAL,
                cashflow_monthly REAL,
                cap_rate REAL,
                cash_on_cash REAL,
                dscr REAL,
                stress_cashflow_monthly REAL,
                margin_of_safety_score REAL,
                passed INTEGER,
                reason_flags JSON,
                full_result JSON,
                created_at TIMESTAMP,
                PRIMARY KEY (run_id, listing_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS land_underwritten (
                run_id TEXT,
                listing_id TEXT,
                underwriting_score REAL,
                buildability_score REAL,
                servicing_score REAL,
                environmental_risk REAL,
                estimated_servicing_cost REAL,
                estimated_all_in_basis REAL,
                estimated_roi REAL,
                land_type TEXT,
                exit_strategy_score REAL,
                ai_summary TEXT,
                recommendation TEXT,
                full_result JSON,
                created_at TIMESTAMP,
                PRIMARY KEY (run_id, listing_id)
            )
        """)

    def save_listings(self, listings: list[Listing]) -> None:
        """Upsert listings into listings_raw."""
        if not listings:
            return
        conn = self._connect()
        rows = [
            [
                l.id,
                l.source,
                l.address,
                l.city,
                l.province,
                l.postal_code,
                l.price,
                l.bedrooms,
                l.bathrooms,
                l.property_type,
                l.description,
                l.url,
                json.dumps(l.raw_payload, default=str),
                l.fetched_at,
            ]
            for l in listings
        ]
        conn.executemany(
            """
            INSERT OR REPLACE INTO listings_raw
            (id, source, address, city, province, postal_code, price, bedrooms,
             bathrooms, property_type, description, url, raw_payload, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def save_deals(self, run_id: str, results: list[UnderwritingResult]) -> None:
        """Save underwriting results to deals_underwritten."""
        if not results:
            return
        conn = self._connect()
        now = datetime.utcnow()
        rows = [
            [
                run_id,
                r.listing_id,
                r.rent_monthly,
                r.noi_annual,
                r.cashflow_monthly,
                r.cap_rate,
                r.cash_on_cash,
                r.dscr,
                r.stress_cashflow_monthly,
                r.margin_of_safety_score,
                1 if r.passed else 0,
                json.dumps(r.reason_flags),
                json.dumps(r.to_dict(), default=_serialize_datetime),
                now,
            ]
            for r in results
        ]
        conn.executemany(
            """
            INSERT OR REPLACE INTO deals_underwritten
            (run_id, listing_id, rent_monthly, noi_annual, cashflow_monthly,
             cap_rate, cash_on_cash, dscr, stress_cashflow_monthly,
             margin_of_safety_score, passed, reason_flags, full_result, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def load_listings(self) -> list[Listing]:
        """Load all listings from listings_raw."""
        conn = self._connect()
        rel = conn.execute("SELECT * FROM listings_raw")
        rows = rel.fetchall()
        cols = ["id", "source", "address", "city", "province", "postal_code", "price",
                "bedrooms", "bathrooms", "property_type", "description", "url",
                "raw_payload", "fetched_at"]
        listings = []
        for row in rows:
            d = dict(zip(cols, row))
            raw = d.get("raw_payload")
            if isinstance(raw, str):
                raw = json.loads(raw)
            listings.append(
                Listing(
                    id=d["id"],
                    source=d["source"],
                    address=d["address"],
                    city=d["city"],
                    province=d["province"],
                    postal_code=d["postal_code"],
                    price=d["price"],
                    bedrooms=d["bedrooms"],
                    bathrooms=d["bathrooms"],
                    property_type=d["property_type"],
                    description=d["description"],
                    url=d["url"],
                    raw_payload=raw or {},
                    fetched_at=d.get("fetched_at") or datetime.utcnow(),
                )
            )
        return listings

    def save_land_deals(self, run_id: str, results: list[Any]) -> None:
        """Save land underwriting results to land_underwritten."""
        if not results:
            return
        conn = self._connect()
        now = datetime.utcnow()
        rows = []
        for r in results:
            d = r.to_dict() if hasattr(r, "to_dict") else r
            scores = d.get("underwriting_score")
            if hasattr(r, "scores"):
                s = r.scores
                f = r.financials
                sig = r.signals
                rows.append(
                    [
                        run_id,
                        d.get("listing_id", r.listing_id),
                        s.underwriting_score,
                        s.buildability_score,
                        s.servicing_score,
                        s.environmental_risk,
                        f.estimated_servicing_cost,
                        f.estimated_all_in_basis,
                        f.estimated_roi,
                        sig.land_type,
                        s.exit_strategy_score,
                        d.get("ai_summary", ""),
                        d.get("recommendation", ""),
                        json.dumps(d, default=_serialize_datetime),
                        now,
                    ]
                )
            else:
                rows.append(
                    [
                        run_id,
                        d.get("listing_id"),
                        scores,
                        d.get("buildability_score"),
                        d.get("servicing_score"),
                        d.get("environmental_risk"),
                        d.get("estimated_servicing_cost"),
                        d.get("estimated_all_in_basis"),
                        d.get("estimated_roi"),
                        d.get("land_type"),
                        d.get("exit_strategy_score"),
                        d.get("ai_summary"),
                        d.get("recommendation"),
                        json.dumps(d, default=_serialize_datetime),
                        now,
                    ]
                )
        conn.executemany(
            """
            INSERT OR REPLACE INTO land_underwritten
            (run_id, listing_id, underwriting_score, buildability_score, servicing_score,
             environmental_risk, estimated_servicing_cost, estimated_all_in_basis,
             estimated_roi, land_type, exit_strategy_score, ai_summary, recommendation,
             full_result, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
