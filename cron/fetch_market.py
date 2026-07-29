"""拉取市场数据写入 DB。

用法:
  .venv/bin/python scripts/fetch_market.py --market us   # S&P 500
  .venv/bin/python scripts/fetch_market.py --market cn   # 沪深300
  .venv/bin/python scripts/fetch_market.py               # 两个都拉
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import get_db

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# Alpaca config
ALPACA_KEY = "PKY2IU4GAJQKC5FXXDAVMCQ7CN"
ALPACA_SECRET = "ExVop4ejfi3Dcootp8tnCZaYoabJL2Q5wv8oDj72nGPd"
ALPACA_DATA_URL = "https://data.alpaca.markets"
ALPACA_HEADERS = {
    "APCA-API-KEY-ID": ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
}

FILTER_OUT_US = {"GOOG", "BRK-A"}


def init_stock_us(conn):
    """从 sp500.json 初始化美股主表。"""
    count = conn.execute("SELECT COUNT(*) FROM stock_us").fetchone()[0]
    if count > 0:
        return
    sp500_path = DATA_DIR / "sp500.json"
    if not sp500_path.exists():
        print("[跳过] data/sp500.json 不存在")
        return
    with open(sp500_path) as f:
        stocks = json.load(f)
    for s in stocks:
        if s["ticker"] in FILTER_OUT_US:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO stock_us (ticker, name, sector, market_cap) VALUES (?,?,?,?)",
            (s["ticker"], s["name"], s.get("sector", ""), s.get("market_cap", 0)))
    conn.commit()
    print(f"  初始化 stock_us: {len(stocks)} 只")


def init_stock_cn(conn):
    """从 AkShare 初始化 A 股主表(沪深300),含市值。"""
    count = conn.execute("SELECT COUNT(*) FROM stock_cn").fetchone()[0]
    if count > 0:
        return
    import akshare as ak
    import yfinance as yf
    df = ak.index_stock_cons_csindex(symbol="000300")
    industry_path = DATA_DIR / "sw_industry_map.json"
    industry_map = {}
    if industry_path.exists():
        with open(industry_path) as f:
            industry_map = json.load(f)
    codes = []
    for _, row in df.iterrows():
        code = str(row["成分券代码"]).zfill(6)
        name = row["成分券名称"]
        sector = industry_map.get(code, "其他")
        conn.execute(
            "INSERT OR IGNORE INTO stock_cn (code, name, sector) VALUES (?,?,?)",
            (code, name, sector))
        codes.append(code)
    conn.commit()
    print(f"  初始化 stock_cn: {len(df)} 只(沪深300)")
    # 拉市值
    print("  拉取市值...")
    for i in range(0, len(codes), 50):
        batch = codes[i:i+50]
        symbols = " ".join(c + (".SS" if c.startswith("6") else ".SZ") for c in batch)
        tickers = yf.Tickers(symbols)
        for code in batch:
            sym = code + (".SS" if code.startswith("6") else ".SZ")
            try:
                cap = tickers.tickers[sym].fast_info.get("marketCap", 0) or 0
                if cap > 0:
                    conn.execute("UPDATE stock_cn SET market_cap=? WHERE code=?", (cap, code))
            except:
                pass
        conn.commit()


def fetch_us(conn):
    """拉 S&P 500 快照写入 snapshot_us。"""
    tickers = [r[0] for r in conn.execute("SELECT ticker FROM stock_us").fetchall()]
    if not tickers:
        print("  stock_us 为空,先初始化")
        init_stock_us(conn)
        tickers = [r[0] for r in conn.execute("SELECT ticker FROM stock_us").fetchall()]

    now = datetime.now(timezone.utc).isoformat()
    count = 0

    for i in range(0, len(tickers), 50):
        batch = tickers[i:i+50]
        resp = httpx.get(
            f"{ALPACA_DATA_URL}/v2/stocks/snapshots",
            headers=ALPACA_HEADERS,
            params={"symbols": ",".join(batch), "feed": "iex"},
            timeout=30)
        if resp.status_code != 200:
            continue
        for ticker, snap in resp.json().items():
            daily = snap.get("dailyBar", {})
            prev = snap.get("prevDailyBar", {})
            price = daily.get("c", 0)
            prev_close = prev.get("c", 0)
            if not prev_close or not price:
                continue
            change_pct = (price - prev_close) / prev_close * 100
            cap = conn.execute("SELECT market_cap FROM stock_us WHERE ticker=?", (ticker,)).fetchone()
            market_cap = cap[0] if cap else 0
            conn.execute(
                "INSERT INTO snapshot_us (ticker, price, change_pct, volume, market_cap, timestamp) VALUES (?,?,?,?,?,?)",
                (ticker, round(price, 2), round(change_pct, 2), daily.get("v", 0), market_cap, now))
            count += 1
    conn.commit()
    print(f"  snapshot_us: {count} 条 @ {now[:19]}")


def fetch_cn(conn):
    """拉沪深300快照写入 snapshot_cn。"""
    import akshare as ak

    codes = [r[0] for r in conn.execute("SELECT code FROM stock_cn").fetchall()]
    if not codes:
        print("  stock_cn 为空,先初始化")
        init_stock_cn(conn)
        codes = [r[0] for r in conn.execute("SELECT code FROM stock_cn").fetchall()]

    code_set = set(codes)
    now = datetime.now(timezone.utc).isoformat()

    df = ak.stock_zh_a_spot()
    df["code6"] = df["代码"].str[-6:]
    df = df[df["code6"].isin(code_set)]

    count = 0
    for _, r in df.iterrows():
        code = r["code6"]
        price = float(r["最新价"]) if r["最新价"] else 0
        change = float(r["涨跌幅"]) if r["涨跌幅"] else 0
        volume = float(r["成交额"]) if r["成交额"] else 0
        if not price:
            continue
        cap = conn.execute("SELECT market_cap FROM stock_cn WHERE code=?", (code,)).fetchone()
        market_cap = cap[0] if cap else 0
        conn.execute(
            "INSERT INTO snapshot_cn (code, price, change_pct, volume, market_cap, timestamp) VALUES (?,?,?,?,?,?)",
            (code, round(price, 2), round(change, 2), volume, market_cap, now))
        count += 1
    conn.commit()
    print(f"  snapshot_cn: {count} 条 @ {now[:19]}")


def cleanup_old_snapshots(conn, keep_hours=48):
    """清理超过 N 小时的旧快照。"""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=keep_hours)).isoformat()
    conn.execute("DELETE FROM snapshot_us WHERE timestamp < ?", (cutoff,))
    conn.execute("DELETE FROM snapshot_cn WHERE timestamp < ?", (cutoff,))
    conn.execute("DELETE FROM snapshot_hk WHERE timestamp < ?", (cutoff,))
    conn.commit()


def init_stock_hk(conn):
    """从 hstech.json 初始化港股主表,含市值。"""
    count = conn.execute("SELECT COUNT(*) FROM stock_hk").fetchone()[0]
    if count > 0:
        return
    import yfinance as yf
    hk_path = DATA_DIR / "hstech.json"
    if not hk_path.exists():
        print("  [跳过] data/hstech.json 不存在")
        return
    with open(hk_path) as f:
        stocks = json.load(f)
    for s in stocks:
        conn.execute("INSERT OR IGNORE INTO stock_hk (code, name, sector) VALUES (?,?,?)",
                     (s["code"], s["name"], s.get("sector", "")))
    conn.commit()
    print(f"  初始化 stock_hk: {len(stocks)} 只(恒生科技)")
    # 拉市值
    print("  拉取市值...")
    for s in stocks:
        code = s["code"]
        sym = code[-4:] + ".HK"
        try:
            cap = yf.Ticker(sym).fast_info.get("marketCap", 0) or 0
            if cap > 0:
                conn.execute("UPDATE stock_hk SET market_cap=? WHERE code=?", (cap, code))
        except:
            pass
    conn.commit()


def fetch_hk(conn):
    """拉恒生科技快照写入 snapshot_hk。用 yfinance 批量拿 30 只。"""
    import yfinance as yf

    codes = [r[0] for r in conn.execute("SELECT code FROM stock_hk").fetchall()]
    if not codes:
        print("  stock_hk 为空,先初始化")
        init_stock_hk(conn)
        codes = [r[0] for r in conn.execute("SELECT code FROM stock_hk").fetchall()]

    # 港股 yfinance 格式:00700→0700.HK
    symbols = [c[-4:] + ".HK" for c in codes]
    sym_to_code = {c[-4:] + ".HK": c for c in codes}

    now = datetime.now(timezone.utc).isoformat()
    count = 0

    tickers = yf.Tickers(" ".join(symbols))
    for sym, code in sym_to_code.items():
        try:
            info = tickers.tickers[sym].fast_info
            price = info.get("lastPrice", 0) or 0
            prev = info.get("previousClose", 0) or 0
            if not price or not prev:
                continue
            change_pct = (price - prev) / prev * 100
            cap = conn.execute("SELECT market_cap FROM stock_hk WHERE code=?", (code,)).fetchone()
            market_cap = cap[0] if cap else 0
            conn.execute(
                "INSERT INTO snapshot_hk (code, price, change_pct, volume, market_cap, timestamp) VALUES (?,?,?,?,?,?)",
                (code, round(price, 2), round(change_pct, 2), 0, market_cap, now))
            count += 1
        except:
            pass
    conn.commit()
    print(f"  snapshot_hk: {count} 条 @ {now[:19]}")


def _in_trading_hours(market: str) -> bool:
    """判断当前是否在该市场交易时段(基于 UTC,和机器时区无关)。"""
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:
        return False
    h = now_utc.hour + now_utc.minute / 60
    if market == "cn":
        return 1.5 <= h <= 7.0  # A股 9:30-15:00 北京 = UTC 1:30-7:00
    elif market == "hk":
        return 1.5 <= h <= 8.0  # 港股 9:30-16:00 HKT = UTC 1:30-8:00
    elif market == "us":
        return 13.5 <= h <= 20.0  # 美股 9:30-16:00 ET = UTC 13:30-20:00
    return True


def main():
    markets = sys.argv[1:] if len(sys.argv) > 1 else ["--market", "all"]
    market = "all"
    if "--market" in markets:
        idx = markets.index("--market")
        market = markets[idx + 1] if idx + 1 < len(markets) else "all"

    conn = get_db()

    if market in ("us", "all"):
        if _in_trading_hours("us"):
            print("拉取美股...")
            fetch_us(conn)
        else:
            print("[跳过] 美股非交易时段")
    if market in ("cn", "all"):
        if _in_trading_hours("cn"):
            print("拉取A股...")
            fetch_cn(conn)
        else:
            print("[跳过] A股非交易时段")
    if market in ("hk", "all"):
        if _in_trading_hours("hk"):
            print("拉取港股...")
            fetch_hk(conn)
        else:
            print("[跳过] 港股非交易时段")

    cleanup_old_snapshots(conn)
    conn.close()
    print("完成。")


if __name__ == "__main__":
    main()
