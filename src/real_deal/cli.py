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

from .config import get_all_cities, get_city_province_map, load_config
from .connectors import RapidAPIRealtorConnector, RapidAPIRedfinConnector
from .filters import filter_listings
from .storage import Storage, export_csv, export_json
from .underwriting import UnderwritingEngine

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
    cities_only: Optional[str] = typer.Option(None, "--cities", "-C", help="Comma-separated cities, or tier name (e.g. bruce_county)"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Override connector: realtor, redfin, or both"),
) -> None:
    """Fetch listings from data source and store raw data."""
    cfg = load_config(config_path)
    if isinstance(cities_only, str):
        if "," in cities_only:
            cities = [c.strip() for c in cities_only.split(",") if c.strip()]
        else:
            cities = get_all_cities(cfg, tiers=(cities_only,))
        console.print(f"[dim]Using cities: {cities}[/dim]")
    else:
        cities = get_all_cities(cfg)
    if isinstance(limit, int) and limit > 0:
        cities = cities[:limit]
        console.print(f"[dim]Limited to {limit} cities for testing[/dim]")
    max_price = float(cfg.get("max_price", 550000))
    default_province = cfg.get("province", "ON")

    ds = cfg.get("data_source", {})
    connector_type = str(source or ds.get("connector", "realtor")).lower()
    delay = float(ds.get("delay_seconds", 2.0))
    min_price = float(ds.get("min_price", 20000))

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
        # both: dedupe by listing id (prefer Redfin for same id - richer data)
        by_id: dict = {}
        for lst in all_listings:
            lid = lst.id
            if lid not in by_id or lst.source == "rapidapi_redfin":
                by_id[lid] = lst
        all_listings = list(by_id.values())
        console.print(f"[dim]Combined {len(all_listings)} unique listings (deduped by ID)[/dim]")

    result = type("Result", (), {"listings": all_listings, "errors": all_errors})()

    if result.errors:
        for e in result.errors:
            console.print(f"[yellow]Warning: {e}[/yellow]")

    # Apply keyword filter
    kw = cfg.get("keyword_filters", {})
    include = kw.get("include", []) if kw.get("require_include_match", True) else []
    exclude = kw.get("exclude", [])
    filtered = filter_listings(result.listings, include, exclude, max_price)

    console.print(f"[green]Fetched {len(result.listings)} listings, {len(filtered)} after keyword filter[/green]")

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
) -> None:
    """Underwrite stored listings and save results."""
    cfg = load_config(config_path)
    storage = _get_storage()
    listings = storage.load_listings()
    storage.close()

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

    # Rank by margin_of_safety_score desc, then cashflow_monthly desc
    ranked = sorted(
        results,
        key=lambda r: (-r.margin_of_safety_score, -r.cashflow_monthly),
    )

    export_csv(ranked, csv_path)
    export_json(ranked, json_path)

    console.print(f"[green]Underwrote {len(results)} listings. Run ID: {run_id}[/green]")
    console.print(f"  CSV:  {csv_path}")
    console.print(f"  JSON: {json_path}")
    return run_id


@app.command()
def report(
    run_id: Optional[str] = typer.Option(None, "--run", "-r", help="Specific run ID (default: latest)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max deals to show"),
) -> None:
    """Display ranked deals report."""
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

    _display_report(results, run_id, limit=limit, json_path=json_path)


@app.command()
def run(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """End-to-end: fetch, underwrite, and report."""
    console.print("[bold]Running full pipeline...[/bold]\n")
    fetch(config_path=config_path)
    run_id = underwrite(config_path=config_path)
    console.print()
    if run_id:
        import json as _json
        out_dir = _get_output_dir()
        json_path = out_dir / f"deals_{run_id}.json"
        if json_path.exists():
            with open(json_path) as f:
                data = _json.load(f)
            results = data.get("results", [])
            _display_report(results, run_id, limit=15, json_path=json_path)


if __name__ == "__main__":
    app()
