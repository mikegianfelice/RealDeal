# Real Deal – Cash-Flow Property Scanner

A simple tool for investors to find cash-flowing properties in Canada. Scans target cities, underwrites with a conservative cash-flow model, and ranks deals by margin of safety.

## Features

- **Data sources**: Realtor.ca (RapidAPI) or Redfin Canada (RapidAPI) – switch via `config.yaml` or `--source`; use `both` to merge and dedupe
- **Property types**: Duplex, triplex, multi-unit, single-family with secondary suites (house-hack plays)
- **Underwriting**: Base case + stress test, margin-of-safety score, pass/fail thresholds
- **Outputs**: CSV, JSON, DuckDB (`listings_raw`, `deals_underwritten`)

## Quick Start

```bash
# Install
pip install -e .

# Set RAPIDAPI_KEY in .env (or export RAPIDAPI_KEY)

# Run full pipeline (fetch from API → underwrite → report)
real-deal run

# Or step by step
real-deal fetch
real-deal underwrite
real-deal report
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `fetch` | Fetch listings from API and store raw data |
| `fetch --source redfin` | Use Redfin Canada instead of Realtor.ca |
| `fetch --source both` | Fetch from both APIs, merge and dedupe by ID |
| `underwrite` | Underwrite stored listings and save results |
| `report` | Display ranked deals table |
| `run` | End-to-end: fetch → underwrite → report |

## Configuration

Edit `config.yaml`:

- **data_source.connector**: `realtor`, `redfin`, or `both` (default) – which API(s) to use (both merges and dedupes by listing ID)
- **max_price**: 550000
- **cities**: Tier 1–3 Ontario cities
- **keyword_filters**: include/exclude for duplex, triplex, secondary suite, etc.
- **underwriting**: vacancy, management, maintenance, capex, insurance, utilities, closing costs, down payment, interest rate, amortization, property tax
- **stress_test**: rent haircut, interest rate bump, vacancy bump
- **pass_fail**: min cashflow, min DSCR, min cash-on-cash
- **rent_estimation**: base + per_bedroom formula; overridden by explicit rent in listing description

## Underwriting Method & Cash Flow Prediction

The engine uses a **conservative income-property model**: base-case cash flow plus a **stress test**, then ranks deals by a **margin-of-safety** score and applies **pass/fail** thresholds.

### Rent estimation

- **Explicit rent**: If the listing description contains a rent amount (e.g. `$2000/mo`, `Rent: $2400`), that value is used.
- **Fallback**: Otherwise rent is estimated as **base + (per_bedroom × bedrooms)** from `config.yaml` (e.g. $1,200 + $850 per bedroom). This is intentionally conservative for single-family; multi-unit listings often have rent in the description.

### Base-case cash flow

1. **NOI (Net Operating Income, annual)**  
   - **Gross potential income** = monthly rent × 12, then reduced by **vacancy** (configurable, e.g. 6%).  
   - **Operating expenses** (all annual): management %, maintenance %, capex reserve %, **property tax** (price × rate), **insurance**, **utilities**, **snow/lawn**.  
   - **NOI = GPI − vacancy − all op ex**.

2. **PITI (monthly)**  
   - **Principal + interest** from a standard amortization (down payment %, interest rate, amortization years).  
   - Plus **monthly property tax** and **monthly insurance**.

3. **Monthly cash flow**  
   - **Cash flow = (NOI ÷ 12) − PITI**.

4. **Metrics**  
   - **Cap rate** = NOI ÷ purchase price.  
   - **Cash-on-cash** = annual cash flow ÷ (down payment + closing costs).  
   - **DSCR** = NOI ÷ annual debt service (lender-style coverage ratio).

### Stress test

A worse-case scenario is run with:

- **Rent haircut** (e.g. 7% lower rent)  
- **Higher vacancy** (e.g. +2%)  
- **Higher interest rate** (e.g. +1%)

Stress **NOI** and **PITI** are recomputed with these inputs; **stress cash flow** = (stress NOI ÷ 12) − stress PITI. A deal is expected to remain viable (or at least not deeply negative) under this scenario.

### Margin of safety (0–100)

The score starts at 50 and adds points for:

- Stress cash flow > 0 (+25)  
- Stress cash flow ≥ min threshold (+15)  
- Cash-on-cash ≥ threshold (+5)  
- DSCR ≥ threshold (+5)

Higher score = more cushion against rent, vacancy, or rate shocks.

### Pass/fail

A listing **passes** only if all of the following hold (thresholds in `config.yaml`):

- Base **monthly cash flow** ≥ min (e.g. $150)  
- **Stress cash flow** ≥ 0  
- **Cash-on-cash** ≥ min (e.g. 8%)  
- **DSCR** ≥ min (e.g. 1.15)

The report shows **reason_flags** for each metric (PASS/FAIL and value).

## Data Source Setup

All listing data comes from the API. No mock or hardcoded data.

1. Sign up at [RapidAPI](https://rapidapi.com)
2. Subscribe to either:
   - **Realtor.ca Scraper API** (baqo271) – residential listings by bounding box
   - **Redfin Canada API** (Apidojo) – more listings per city, search by region
3. Add your API key to `.env`:
   ```
   RAPIDAPI_KEY=your_key_here
   ```
4. Choose connector in `config.yaml`: `data_source.connector: "realtor"` or `"redfin"`
5. Run:
   ```bash
   real-deal run
   ```
   Or step by step: `fetch` → `underwrite` → `report`

The connector is designed so you can add an Apify HouseSigma actor or another source by implementing the `ListingConnector` interface.

## Project Structure

```
RealDeal/
├── config.yaml           # Config (cities, underwriting, thresholds)
├── pyproject.toml
├── src/real_deal/
│   ├── cli.py            # Typer CLI
│   ├── config.py         # Config loader
│   ├── models.py         # Listing, UnderwritingResult, etc.
│   ├── filters.py        # Keyword + price filters
│   ├── connectors/
│   │   ├── base.py       # ListingConnector interface
│   │   ├── rapidapi_realtor.py
│   │   └── rapidapi_redfin.py
│   ├── underwriting/
│   │   ├── engine.py     # UnderwritingEngine
│   │   └── rent.py       # Rent estimation + parse from description
│   └── storage/
│       ├── db.py         # DuckDB (listings_raw, deals_underwritten)
│       └── export.py     # CSV, JSON export
├── tests/
└── output/               # CSV, JSON, DuckDB, raw payloads
```

## Output Metrics

- **cashflow_monthly**: Base-case monthly cash flow
- **stress_cashflow_monthly**: Stress-case (rent haircut, higher vacancy, higher rate)
- **cap_rate**: NOI / purchase price
- **cash_on_cash**: Annual cash flow / total cash in (down + closing)
- **DSCR**: Debt service coverage ratio
- **margin_of_safety_score**: 0–100 (higher = more cushion)
- **reason_flags**: Pass/fail reasons for each threshold

## Tests

```bash
pytest tests/ -v -p no:anchorpy
```

## Example Output

All data comes from the API. Example report from `real-deal run`:

```
                        Best Deals (Run YYYYMMDD_HHMMSS)
┏━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━┳━━━━━┳━━━━━━┓
┃ Rank ┃ Address┃ City   ┃  Price ┃ CF/mo ┃ Stress ┃   CoC ┃ DSCR ┃ MoS ┃ Pass ┃
┡━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━╇━━━━━╇━━━━━━┩
│ 1    │ ...    │ Windsor│ $399,000│  $xxx │   $xxx │  x.x% │ x.xx │ xx  │  ✓   │
│ 2    │ ...    │ London │ $475,000│  $xxx │   $xxx │  x.x% │ x.xx │ xx  │  ✗   │
└──────┴────────┴────────┴────────┴───────┴────────┴───────┴──────┴─────┴──────┘
```

Output files:

- `output/deals_<run_id>.csv` – Ranked deals
- `output/deals_<run_id>.json` – Full underwriting details
- `output/real_deal.duckdb` – DuckDB database
- `output/raw/listings_<run_id>.json` – Raw API payloads (for debugging)

## License

MIT
