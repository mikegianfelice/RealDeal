"""CLI for Real Deal Ontario property scanner."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from typing import Optional

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import typer
from rich.console import Console
from rich.table import Table

from collections import defaultdict

from .config import get_all_cities, get_city_province_map, get_export_min_cashflow_monthly, load_config
from .connectors import RapidAPIRealtorConnector, RapidAPIRedfinConnector
from .filters import filter_listings
from .listing_classification import is_land_from_listing
from .listing_utils import dedupe_listings
from .storage import Storage, export_csv, export_json
from .underwriting import UnderwritingEngine
from .land import LandUnderwritingEngine
from .land.detection import is_land_candidate
from .land.mocks import run_mock_underwriting

app = typer.Typer(
    name="real-deal",
    help="Ontario cash-flow property scanner - find cash-flow deals",
)
console = Console()


def _get_output_dir() -> Path:
    """Default output directory for runs."""
    return Path("output")


def _get_storage() -> Storage:
    """Default storage instance."""
    return Storage(_get_output_dir() / "real_deal.duckdb")


def _run_id() -> str:
    """Generate run ID from timestamp."""
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _filter_cashflow_band(results: list, min_cashflow: float) -> list:
    """Keep deals with base-case monthly cashflow >= min_cashflow (e.g. -500 drawdown)."""
    return [
        r
        for r in results
        if (r.cashflow_monthly if hasattr(r, "cashflow_monthly") else r.get("cashflow_monthly", -1e9))
        >= min_cashflow
    ]


def _sort_results(results: list, sort: str = "safety") -> list:
    """Sort underwriting results by the given key."""
    sort_keys = {
        "safety": lambda r: (-r.margin_of_safety_score, -r.confidence_score, -r.cashflow_monthly),
        "cashflow": lambda r: (-r.cashflow_monthly, -r.confidence_score, -r.margin_of_safety_score),
        "coc": lambda r: (-r.cash_on_cash, -r.cashflow_monthly, -r.confidence_score),
        "dscr": lambda r: (-r.dscr, -r.cashflow_monthly, -r.confidence_score),
        "confidence": lambda r: (-r.confidence_score, -r.margin_of_safety_score, -r.cashflow_monthly),
    }
    key_fn = sort_keys.get(sort.lower(), sort_keys["safety"])
    return sorted(results, key=key_fn)


def _display_report(
    results: list,
    run_id: str,
    limit: int = 20,
    json_path: Optional[Path] = None,
) -> None:
    """Display ranked deals table. Results can be UnderwritingResult or dict (from JSON)."""
    # Normalize to dict format
    rows = []
    for r in results:
        if hasattr(r, "to_dict"):
            rows.append(r.to_dict())
        else:
            rows.append(r)

    if not rows:
        console.print("[yellow]No results to display.[/yellow]")
        return

    table = Table(title=f"Best Deals (Run {run_id})")
    table.add_column("Rank", style="dim")
    table.add_column("Address", style="cyan")
    table.add_column("City", style="dim")
    table.add_column("Price", justify="right")
    table.add_column("CF/mo", justify="right")
    table.add_column("Stress CF", justify="right")
    table.add_column("CoC", justify="right")
    table.add_column("DSCR", justify="right")
    table.add_column("MoS", justify="right")
    table.add_column("Conf", justify="right")
    table.add_column("Pass", justify="center")

    for i, r in enumerate(rows[:limit], 1):
        listing = r.get("listing", {})
        addr = listing.get("address", "")
        addr_display = addr[:30] + "..." if len(addr) > 30 else addr
        passed = "✓" if r.get("passed") else "✗"
        table.add_row(
            str(i),
            addr_display,
            listing.get("city", ""),
            f"${listing.get('price', 0):,.0f}",
            f"${r.get('cashflow_monthly', 0):,.0f}",
            f"${r.get('stress_cashflow_monthly', 0):,.0f}",
            f"{r.get('cash_on_cash', 0):.1%}",
            f"{r.get('dscr', 0):.2f}",
            f"{r.get('margin_of_safety_score', 0):.0f}",
            f"{r.get('confidence_score', 0.5):.2f}",
            passed,
        )

    console.print(table)
    if json_path:
        console.print(f"\n[dim]Full details: {json_path}[/dim]")


@app.command()
def fetch(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Limit number of cities (for testing)"),
    cities_only: Optional[str] = typer.Option(None, "--cities", "-C", help="Comma-separated cities or tier names (e.g. tier_1,tier_2,bruce_county)"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Override connector: realtor, redfin, or both"),
) -> None:
    """Fetch listings from data source and store raw data."""
    cfg = load_config(config_path)
    if isinstance(cities_only, str):
        parts = [c.strip() for c in cities_only.split(",") if c.strip()]
        all_tier_names = set(cfg.get("cities", {}).keys())
        # Check if all parts are tier names
        if all(p in all_tier_names for p in parts):
            cities = get_all_cities(cfg, tiers=tuple(parts))
        elif any(p in all_tier_names for p in parts):
            # Mix of tier names and city names
            tiers = [p for p in parts if p in all_tier_names]
            explicit = [p for p in parts if p not in all_tier_names]
            cities = get_all_cities(cfg, tiers=tuple(tiers)) + explicit
        else:
            cities = parts
        console.print(f"[dim]Using cities: {cities}[/dim]")
    else:
        cities = get_all_cities(cfg)
    if isinstance(limit, int) and limit > 0:
        cities = cities[:limit]
        console.print(f"[dim]Limited to {limit} cities for testing[/dim]")
    ds = cfg.get("data_source", {})
    max_price = float(cfg.get("max_price", 550000))
    min_price = float(cfg.get("min_price", ds.get("min_price", 20000)))
    default_province = cfg.get("province", "ON")

    connector_type = str(source or ds.get("connector", "realtor")).lower()
    delay = float(ds.get("delay_seconds", 2.0))

    # Group cities by province so each province is fetched with the correct filter
    city_prov_map = get_city_province_map(cfg)
    province_groups: dict[str, list[str]] = defaultdict(list)
    for city in cities:
        prov = city_prov_map.get(city, default_province)
        province_groups[prov].append(city)

    all_listings: list = []
    all_errors: list[str] = []

    for province, prov_cities in province_groups.items():
        if connector_type in ("realtor", "both"):
            host = ds.get("rapidapi_host", "realtor-ca-scraper-api.p.rapidapi.com")
            property_type_group_id = str(ds.get("property_type_group_id", "1") or "")
            bounding_box_delta = float(ds.get("bounding_box_delta", 0.15))
            zoom_level = str(ds.get("zoom_level", "10"))
            realtor_conn = RapidAPIRealtorConnector(
                host=host,
                delay_seconds=delay,
                min_price=min_price,
                property_type_group_id=property_type_group_id,
                bounding_box_delta=bounding_box_delta,
                zoom_level=zoom_level,
            )
            console.print(f"[bold]Fetching from Realtor.ca for {len(prov_cities)} cities ({province})...[/bold]")
            result = realtor_conn.fetch(cities=prov_cities, max_price=max_price, province=province)
            all_listings.extend(result.listings)
            all_errors.extend(result.errors)

        if connector_type in ("redfin", "both"):
            if connector_type == "both":
                time.sleep(delay)
            host = ds.get("redfin_host", "redfin-canada.p.rapidapi.com")
            redfin_conn = RapidAPIRedfinConnector(
                host=host,
                delay_seconds=delay,
                min_price=min_price,
            )
            console.print(f"[bold]Fetching from Redfin Canada for {len(prov_cities)} cities ({province})...[/bold]")
            result = redfin_conn.fetch(cities=prov_cities, max_price=max_price, province=province)
            all_listings.extend(result.listings)
            all_errors.extend(result.errors)

    if connector_type == "both":
        before = len(all_listings)
        all_listings = dedupe_listings(all_listings, prefer_source="rapidapi_redfin")
        console.print(
            f"[dim]Combined {len(all_listings)} unique listings "
            f"(deduped from {before} by ID + address)[/dim]"
        )

    result = type("Result", (), {"listings": all_listings, "errors": all_errors})()

    if result.errors:
        for e in result.errors:
            console.print(f"[yellow]Warning: {e}[/yellow]")

    # Apply keyword filter
    kw = cfg.get("keyword_filters", {})
    include = kw.get("include", []) if kw.get("require_include_match", True) else []
    exclude = kw.get("exclude", [])
    filtered = filter_listings(result.listings, include, exclude, max_price, min_price=min_price)

    console.print(
        f"[green]Fetched {len(result.listings)} listings, {len(filtered)} after filters "
        f"(${min_price:,.0f}–${max_price:,.0f})[/green]"
    )

    if filtered:
        storage = _get_storage()
        storage.save_listings(filtered)
        # Save raw payloads for debugging
        raw_dir = _get_output_dir() / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        run_id = _run_id()
        raw_file = raw_dir / f"listings_{run_id}.json"
        import json as _json
        with open(raw_file, "w") as f:
            _json.dump([l.raw_payload for l in filtered], f, indent=2, default=str)
        console.print(f"[dim]Raw payloads saved to {raw_file}[/dim]")
        storage.close()
    else:
        console.print("[yellow]No listings to save. Check RAPIDAPI_KEY in .env and API rate limits.[/yellow]")


@app.command()
def underwrite(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
    sort: str = typer.Option("safety", "--sort", "-S", help="Sort by: safety (margin-of-safety), cashflow, coc (cash-on-cash), dscr"),
) -> None:
    """Underwrite stored listings and save results."""
    cfg = load_config(config_path)
    storage = _get_storage()
    min_price = float(cfg.get("min_price", 0))
    listings = storage.load_listings()
    storage.close()
    before = len(listings)
    listings = [
        l
        for l in listings
        if l.price >= min_price and not is_land_from_listing(l)
    ]
    dropped = before - len(listings)
    if dropped:
        console.print(
            f"[dim]Excluded {dropped} listings (land/lots or price < ${min_price:,.0f})[/dim]"
        )

    if not listings:
        console.print("[yellow]No listings in database. Run 'fetch' first.[/yellow]")
        raise typer.Exit(1)

    engine = UnderwritingEngine(config=cfg)
    results = engine.underwrite_many(listings)

    run_id = _run_id()
    storage = _get_storage()
    storage.save_deals(run_id, results)
    storage.close()

    out_dir = _get_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"deals_{run_id}.csv"
    json_path = out_dir / f"deals_{run_id}.json"

    ranked = _sort_results(results, sort)
    min_cf = get_export_min_cashflow_monthly(cfg)
    exported = _filter_cashflow_band(ranked, min_cf)

    export_csv(exported, csv_path)
    export_json(exported, json_path)

    console.print(f"[green]Underwrote {len(results)} listings. Run ID: {run_id}[/green]")
    console.print(
        f"[dim]Exported {len(exported)} with cashflow >= ${min_cf:,.0f}/mo "
        f"(of {len(ranked)} ranked)[/dim]"
    )
    console.print(f"  CSV:  {csv_path}")
    console.print(f"  JSON: {json_path}")
    return run_id


@app.command()
def report(
    run_id: Optional[str] = typer.Option(None, "--run", "-r", help="Specific run ID (default: latest)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max deals to show"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
    min_cashflow: Optional[float] = typer.Option(
        None,
        "--min-cashflow",
        help="Only show deals with CF/mo >= this (default: export_filters.min_cashflow_monthly)",
    ),
) -> None:
    """Display ranked deals report."""
    cfg = load_config(config_path)
    cf_floor = min_cashflow if min_cashflow is not None else get_export_min_cashflow_monthly(cfg)
    out_dir = _get_output_dir()
    if not run_id:
        # Find latest JSON
        jsons = sorted(out_dir.glob("deals_*.json"), reverse=True)
        if not jsons:
            console.print("[yellow]No report files found. Run 'underwrite' first.[/yellow]")
            raise typer.Exit(1)
        json_path = jsons[0]
        run_id = json_path.stem.replace("deals_", "")
    else:
        json_path = out_dir / f"deals_{run_id}.json"
        if not json_path.exists():
            console.print(f"[red]Report not found: {json_path}[/red]")
            raise typer.Exit(1)

    import json
    with open(json_path) as f:
        data = json.load(f)

    results = data.get("results", [])
    if not results:
        console.print("[yellow]No results in report.[/yellow]")
        return

    filtered = _filter_cashflow_band(results, cf_floor)
    if len(filtered) < len(results):
        console.print(
            f"[dim]Showing {len(filtered)} deals with cashflow >= ${cf_floor:,.0f}/mo "
            f"(of {len(results)} in file)[/dim]\n"
        )
    _display_report(filtered, run_id, limit=limit, json_path=json_path)


@app.command()
def run(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
    cities_only: Optional[str] = typer.Option(None, "--cities", "-C", help="Comma-separated cities or tier names (e.g. tier_1,tier_2,bruce_county)"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Override connector: realtor, redfin, or both"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max deals to show in report"),
    sort: str = typer.Option("safety", "--sort", "-S", help="Sort by: safety, cashflow, coc, dscr"),
) -> None:
    """End-to-end: fetch, underwrite, and report."""
    cfg = load_config(config_path)
    console.print("[bold]Running full pipeline...[/bold]\n")
    fetch(config_path=config_path, cities_only=cities_only, source=source)
    run_id = underwrite(config_path=config_path, sort=sort)
    console.print()
    if run_id:
        import json as _json
        out_dir = _get_output_dir()
        json_path = out_dir / f"deals_{run_id}.json"
        if json_path.exists():
            with open(json_path) as f:
                data = _json.load(f)
            results = data.get("results", [])
            cf_floor = get_export_min_cashflow_monthly(cfg)
            filtered = _filter_cashflow_band(results, cf_floor)
            if len(filtered) < len(results):
                console.print(
                    f"[dim]Showing {len(filtered)} deals with cashflow >= ${cf_floor:,.0f}/mo "
                    f"(of {len(results)} underwritten)[/dim]\n"
                )
            _display_report(filtered, run_id, limit=limit, json_path=json_path)


land_app = typer.Typer(help="Vacant land underwriting commands")
app.add_typer(land_app, name="land")


def _sort_land_results(results: list, sort: str = "score") -> list:
    keys = {
        "score": lambda r: (-r.scores.underwriting_score, -r.scores.buildability_score),
        "roi": lambda r: (-r.financials.estimated_roi, -r.scores.underwriting_score),
        "price": lambda r: (r.listing.price or 0, -r.scores.underwriting_score),
        "acreage": lambda r: (-(r.metrics.acres or 0), -r.scores.underwriting_score),
    }
    key_fn = keys.get(sort.lower(), keys["score"])
    return sorted(results, key=key_fn)


def _risk_indicator(score: float) -> str:
    if score >= 60:
        return "[red]HIGH[/red]"
    if score >= 35:
        return "[yellow]MED[/yellow]"
    return "[green]LOW[/green]"


def _display_land_report(results: list, run_id: str, limit: int = 20) -> None:
    if not results:
        console.print("[yellow]No land results to display.[/yellow]")
        return
    table = Table(title=f"Vacant Land Underwriting (Run {run_id})")
    table.add_column("Rank", style="dim")
    table.add_column("Address", style="cyan", max_width=32)
    table.add_column("City")
    table.add_column("Price", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Build", justify="right")
    table.add_column("ROI%", justify="right")
    table.add_column("Risk", justify="center")
    table.add_column("Rec", justify="center")
    for i, r in enumerate(results[:limit], 1):
        env_risk = r.scores.environmental_risk
        addr = r.listing.address[:30] + "…" if len(r.listing.address) > 30 else r.listing.address
        table.add_row(
            str(i),
            addr,
            r.listing.city,
            f"${r.listing.price:,.0f}" if r.listing.price else "—",
            f"{r.scores.underwriting_score:.0f}",
            f"{r.scores.buildability_score:.0f}",
            f"{r.financials.estimated_roi:.1f}",
            _risk_indicator(env_risk),
            r.recommendation,
        )
    console.print(table)


@land_app.command("underwrite")
def land_underwrite(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
    sort: str = typer.Option("score", "--sort", "-S", help="score, roi, price, acreage"),
) -> None:
    """Underwrite vacant land listings from the database."""
    cfg = load_config(config_path)
    storage = _get_storage()
    all_listings = storage.load_listings()
    storage.close()
    listings = [l for l in all_listings if is_land_candidate(l)]
    if not listings:
        console.print(
            "[yellow]No land listings in database. Run fetch (land is no longer keyword-excluded) "
            "or `land examples` for mocks.[/yellow]"
        )
        raise typer.Exit(1)
    console.print(f"[dim]Underwriting {len(listings)} land listings (of {len(all_listings)} total)[/dim]")
    engine = LandUnderwritingEngine(config=cfg)
    results = engine.underwrite_many(listings)
    ranked = _sort_land_results(results, sort)
    run_id = _run_id()
    storage = _get_storage()
    storage.save_land_deals(run_id, ranked)
    storage.close()
    out_dir = _get_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    import json as _json

    json_path = out_dir / f"land_deals_{run_id}.json"
    with open(json_path, "w") as f:
        _json.dump({"run_id": run_id, "results": [r.to_dict() for r in ranked]}, f, indent=2, default=str)
    console.print(f"[green]Land underwrite complete. Run ID: {run_id}[/green]")
    console.print(f"  JSON: {json_path}")
    report_dir = cfg.get("land_underwriting", {}).get("report_output_dir", "outputs/underwriting")
    console.print(f"  Reports: {report_dir}/")
    _display_land_report(ranked, run_id)


@land_app.command("report")
def land_report(
    run_id: Optional[str] = typer.Option(None, "--run", "-r"),
    limit: int = typer.Option(20, "--limit", "-n"),
    sort: str = typer.Option("score", "--sort", "-S"),
) -> None:
    """Display land underwriting results from the latest JSON export."""
    out_dir = _get_output_dir()
    if run_id:
        json_path = out_dir / f"land_deals_{run_id}.json"
    else:
        jsons = sorted(out_dir.glob("land_deals_*.json"), reverse=True)
        if not jsons:
            console.print("[yellow]No land report found. Run `land underwrite` first.[/yellow]")
            raise typer.Exit(1)
        json_path = jsons[0]
        run_id = json_path.stem.replace("land_deals_", "")
    if not json_path.exists():
        console.print(f"[red]Not found: {json_path}[/red]")
        raise typer.Exit(1)
    import json as _json

    with open(json_path) as f:
        data = _json.load(f)
    console.print(f"[bold]Land deals from {json_path.name}[/bold]\n")
    rows = data.get("results", [])
    if not rows:
        console.print("[yellow]Empty results.[/yellow]")
        return
    table = Table(title=f"Vacant Land (Run {run_id})")
    table.add_column("Address", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("ROI%", justify="right")
    table.add_column("Recommendation")
    for r in rows[:limit]:
        listing = r.get("listing", {})
        table.add_row(
            (listing.get("address") or "")[:35],
            str(r.get("underwriting_score", "")),
            str(r.get("estimated_roi", "")),
            r.get("recommendation", ""),
        )
    console.print(table)


@land_app.command("examples")
def land_examples(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """Run three mocked land underwriting scenarios and write reports."""
    cfg = load_config(config_path)
    console.print("[bold]Running mock land underwriting examples...[/bold]\n")
    results = run_mock_underwriting(cfg)
    ranked = _sort_land_results(results, "score")
    _display_land_report(ranked, "mock-examples", limit=10)
    for r in ranked:
        console.print(f"  [dim]{r.recommendation}[/dim] — {r.listing.address} → {r.report_path}")


if __name__ == "__main__":
    app()
