# StockRadar

Two things, done well:

1. **Real-time market visualization** — See how entire markets move at a glance. Bubble charts for S&P 500, HS300, and HSTECH, sized by market cap, positioned by daily change, colored by sector.
2. **KOL intelligence** — Track what top Twitter investors are actually saying. Auto-fetch their tweets, extract per-stock opinions with LLM, and see consensus/divergence across voices.

---

## Feature 1: Market Visualization

Live bubble charts across three markets, auto-refreshing every 30 seconds during trading hours.

| Market | Index | Constituents | Data Source |
|---|---|---|---|
| US | S&P 500 | ~500 | Alpaca |
| China A-shares | HS300 | 300 | AkShare (Sina) |
| Hong Kong | HSTECH | 30 | yfinance |

**How to read it:** X-axis groups by sector, Y-axis is daily % change (clamped at ±6%), bubble size = market cap. Force simulation packs bubbles tightly so you see sector-level momentum instantly — e.g. all of semis red while banks are green.

Routes: `/market` · `/market/cn` · `/market/hk`

## Feature 2: KOL Tracking & Analysis

Tracks a curated list of high-signal Twitter accounts, then answers: *what are they watching, and what do they think about it?*

**Pipeline:**
```
Tweets fetched hourly (twscrape)
    ↓
LLM extracts per-tweet stock opinions  →  stock_opinion table
    (ticker, direction, reasoning, catalyst)      (tweet-level granularity)
    ↓
Aggregated into 30-day rolling views   →  kol_stock_view table
    (overall stance, mention counts, evolution)   (KOL × ticker granularity)
```

**Two lenses on the same data:**
- **Stock-centric** (`/stocks`, `/stock/<ticker>`) — For a given ticker: who's talking about it, bullish or bearish, is there consensus or disagreement, how has sentiment evolved?
- **KOL-centric** (`/kol/<handle>`) — For a given voice: what are all the tickers they cover, and their current stance on each?
- **Raw feed** (`/tweets`) — Unfiltered tweet stream with KOL/keyword filters.

The LLM handles ticker recognition across languages (Chinese company names → US tickers) and distinguishes *"I'm bullish on X"* from *"X's earnings imply something about Y"* — so a mention of Google's capex guidance gets attributed to semiconductor names, not tagged as a Google buy signal.

---

## Architecture

```
stockradar/
├── src/                  # Core library (imported, never run directly)
│   ├── db.py             # SQLite schema — 10 tables, market data fully separated per region
│   ├── scraper.py        # twscrape tweet fetching, incremental via cursor
│   ├── analyzer.py       # LLM batch analysis, prompts loaded from prompts/
│   ├── tickers.py        # $TICKER regex extraction
│   └── web/              # FastAPI + Jinja2 + D3.js
├── cron/                 # Unattended scheduled jobs
│   ├── fetch_market.py   # Market snapshots — decides trading hours itself (UTC-based)
│   ├── fetch_tweets.py   # Tweet fetching
│   ├── analyze.py        # LLM analysis of unprocessed tweets
│   └── sync_stocks.py    # Daily: index constituents + market caps
├── tools/                # Human-triggered
│   ├── manage_kol.py     # Add/remove tracked accounts
│   └── refresh_cookie.py # Re-auth X session via browser
├── prompts/              # LLM prompts as plain text — edit without touching code
└── data/                 # SQLite + index JSONs (gitignored)
```

**Design choices worth noting:**

- **Frontend never calls external APIs.** Cron writes snapshots to SQLite; the web layer only reads. Page loads are instant and don't depend on Alpaca/AkShare being up.
- **Trading hours live in code, not cron.** `fetch_market.py` checks UTC against each market's hours and skips if closed. One crontab works identically on a Beijing laptop and a UTC VPS.
- **Markets are separate tables.** `stock_us`/`snapshot_us`, `stock_cn`/`snapshot_cn`, `stock_hk`/`snapshot_hk`. No `WHERE market=` scattered through queries.
- **Raw data is kept greedily.** Tweets are stored verbatim; LLM analysis is a separate downstream pass. When the extraction logic improves, re-run it over history — no re-fetching.
- **Tweets are untrusted input.** They're data to analyze, never instructions. Any LLM-facing pipeline wraps them in explicit boundaries.

## Quick Start

```bash
uv sync                                    # install deps from lockfile
cp .env.example .env                       # fill in X credentials + LLM key

python tools/manage_kol.py add <handle>    # add accounts to track
python cron/fetch_tweets.py --limit 200    # backfill tweets
python cron/fetch_market.py                # init market data (auto-bootstraps tables)
python cron/analyze.py                     # LLM opinion extraction

uvicorn src.web.app:app --port 8002
```

## Scheduling

One crontab, timezone-agnostic:

```cron
* * * * 1-5  cd /path/to/stockradar && .venv/bin/python cron/fetch_market.py  >> logs/market.log 2>&1
7 * * * *    cd /path/to/stockradar && .venv/bin/python cron/fetch_tweets.py  >> logs/fetch.log  2>&1
0 0 * * *    cd /path/to/stockradar && .venv/bin/python cron/sync_stocks.py   >> logs/sync.log   2>&1
```

## Routes

| Path | What it shows |
|---|---|
| `/` | Landing page |
| `/market`, `/market/cn`, `/market/hk` | Bubble charts (US / China / HK) |
| `/stocks` | All tracked tickers ranked by KOL attention, with consensus |
| `/stock/<ticker>` | Who's talking about it + opinion timeline |
| `/tweets` | Raw feed, filter by KOL or keyword |
| `/kol/<handle>` | One KOL's full coverage |
| `/api/market/{,cn/,hk/}snapshot` | JSON snapshots (what the frontend polls) |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Tweets stopped updating | X cookie expired (happens every few days) | `python tools/refresh_cookie.py` |
| Gap in tweet history | Cookie was dead for a while | `python cron/fetch_tweets.py --limit 200` (dedupes automatically) |
| Bubbles all the same size | `market_cap` is 0 | `python cron/sync_stocks.py` |
| Market page empty | Never bootstrapped | `python cron/fetch_market.py` |
| Analysis not running | LLM quota exhausted (HTTP 402) | Top up, then `python cron/analyze.py` |
| Stale prices during market hours | Cron not firing, or wrong path in crontab | Check `logs/market.log` |

## Config

| Variable | Purpose |
|---|---|
| `X_ACCOUNT_USERNAME`, `X_PASSWORD` | X login (used by `refresh_cookie.py`) |
| `X_AUTH_TOKEN`, `X_CT0` | X session cookies — bootstrap only, then self-managed |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | OpenAI-compatible endpoint for analysis |

## Deployment

Runs on a VPS behind Cloudflare Tunnel — no open ports, no public IP needed.

```bash
systemctl start stockradar    # uvicorn on :8002
systemctl start cloudflared   # tunnel → your domain
```

Market data and tweet fetching both work from a plain VPS. LLM analysis needs the endpoint to be reachable from wherever you run it.
