# StockRadar

Investment intelligence radar. Auto-fetches Twitter KOL tweets, LLM-powered opinion extraction, and real-time market visualization.

## Architecture

```
stockradar/
├── src/              # Core library (imported, not executed directly)
│   ├── db.py         # SQLite schema (10 tables)
│   ├── scraper.py    # twscrape tweet fetching
│   ├── analyzer.py   # LLM batch analysis (reads prompts/)
│   ├── tickers.py    # $TICKER regex extraction
│   └── web/          # FastAPI web service
│       ├── app.py    # Main routes
│       ├── market.py # S&P 500 API (reads DB)
│       ├── market_cn.py  # HS300 API
│       └── market_hk.py  # HSTECH API
├── cron/             # Scheduled jobs (cron, unattended)
│   ├── fetch_tweets.py   # Pull KOL tweets
│   ├── fetch_market.py   # Pull market snapshots (auto timezone)
│   ├── sync_stocks.py    # Sync constituents + market cap
│   └── analyze.py        # LLM analysis
├── tools/            # Manual tools (human-triggered)
│   ├── manage_kol.py     # KOL add/remove/list
│   └── refresh_cookie.py # Refresh X cookie (browser popup)
├── prompts/          # LLM prompt templates
├── docs/             # Design docs
├── data/             # SQLite + JSON (gitignored)
└── logs/             # Runtime logs (gitignored)
```

## Quick Start

```bash
# Install dependencies (using uv)
uv sync

# Or with pip
pip install -e .

# Config
cp .env.example .env   # Fill in X credentials + LLM key

# Init KOLs
.venv/bin/python tools/manage_kol.py add aleabitoreddit --category "Semis/AI"
.venv/bin/python tools/manage_kol.py add hanking66 --category "Memory/Macro"

# Fetch data
.venv/bin/python cron/fetch_tweets.py --limit 200
.venv/bin/python cron/fetch_market.py

# Start web
.venv/bin/uvicorn src.web.app:app --port 8002
```

## Pipeline

```
Twitter ──→ tweet table ──→ LLM ──→ stock_opinion / kol_stock_view
              (cron/fetch_tweets)     (cron/analyze)
                                                    ↓
Alpaca (US) ──→ snapshot_us ─────────────────────→ Web frontend (read-only)
AkShare (CN) ──→ snapshot_cn ────────────────────→ (30s polling)
yfinance (HK) ──→ snapshot_hk ──────────────────→
              (cron/fetch_market)
```

## Cron

Trading hours are handled **in code** (UTC-based), not in cron schedule. One universal crontab works on any timezone:

```
* * * * 1-5  cd /path/to/stockradar && .venv/bin/python cron/fetch_market.py >> logs/market.log 2>&1
7 * * * *    cd /path/to/stockradar && .venv/bin/python cron/fetch_tweets.py >> logs/fetch.log 2>&1
0 0 * * *    cd /path/to/stockradar && .venv/bin/python cron/sync_stocks.py >> logs/sync.log 2>&1
```

## Web Routes

| Path | Description | Source |
|---|---|---|
| `/` | Landing page | - |
| `/market` | S&P 500 bubble chart | snapshot_us |
| `/market/cn` | HS300 bubble chart | snapshot_cn |
| `/market/hk` | HSTECH bubble chart | snapshot_hk |
| `/stocks` | Stock insights (KOL opinions) | kol_stock_view |
| `/stock/<ticker>` | Per-stock opinion timeline | stock_opinion |
| `/tweets` | Tweet feed (filterable) | tweet |
| `/kol/<handle>` | Per-KOL stock views | kol_stock_view |

## Recovery

| Issue | Cause | Fix |
|---|---|---|
| Tweets not updating | X cookie expired | `tools/refresh_cookie.py` |
| Missed tweets | Cookie was dead for a while | `cron/fetch_tweets.py --limit 200` |
| LLM analysis stuck | API quota (402) | Top up, rerun `cron/analyze.py` |
| Market data empty | Never ran fetch_market | `cron/fetch_market.py` (auto-inits) |
| Bubble sizes wrong | market_cap = 0 | `cron/sync_stocks.py` |

## Config (.env)

| Variable | Description | Required |
|---|---|---|
| X_ACCOUNT_USERNAME | X login username | ✓ |
| X_PASSWORD | X login password | ✓ |
| X_AUTH_TOKEN | X cookie (auto-refreshable) | init |
| X_CT0 | X cookie (auto-refreshable) | init |
| LLM_BASE_URL | LLM API endpoint | for analysis |
| LLM_API_KEY | LLM API key | for analysis |
| LLM_MODEL | Model name (default: deepseek-v4-pro) | |

## Deployment

Running on Vultr VPS with Cloudflare Tunnel:
```bash
# Service
systemctl start stockradar    # uvicorn on port 8002

# Tunnel
systemctl start cloudflared   # stock-radar.net → localhost:8002
```
