"""每天更新股票主表:同步成分股 + 更新市值。

用法:
  .venv/bin/python cron/sync_stocks.py           # 两个市场都更新
  .venv/bin/python cron/sync_stocks.py --market cn
  .venv/bin/python cron/sync_stocks.py --market us
"""
import json
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import get_db

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def sync_cn(conn):
    """同步沪深300成分股 + yfinance 更新市值。"""
    import akshare as ak

    # 1. 拉最新成分股
    df = ak.index_stock_cons_csindex(symbol="000300")
    latest_codes = set(str(r).zfill(6) for r in df["成分券代码"])
    print(f"  沪深300最新: {len(latest_codes)} 只")

    # 加载行业映射
    industry_map = {}
    p = DATA_DIR / "sw_industry_map.json"
    if p.exists():
        with open(p) as f:
            industry_map = json.load(f)

    # 新增成分股
    existing = set(r[0] for r in conn.execute("SELECT code FROM stock_cn").fetchall())
    added = latest_codes - existing
    removed = existing - latest_codes
    for code in added:
        name_row = df[df["成分券代码"].astype(str).str.zfill(6) == code]
        name = name_row.iloc[0]["成分券名称"] if len(name_row) > 0 else ""
        conn.execute("INSERT OR IGNORE INTO stock_cn (code, name, sector) VALUES (?,?,?)",
                     (code, name, industry_map.get(code, "其他")))
    if added:
        print(f"  新增 {len(added)} 只: {', '.join(sorted(added)[:5])}...")

    # 剔除旧成分股
    if removed:
        for code in removed:
            conn.execute("DELETE FROM stock_cn WHERE code=?", (code,))
        print(f"  剔除 {len(removed)} 只: {', '.join(sorted(removed)[:5])}...")

    conn.commit()

    # 2. yfinance 更新市值(分批)
    codes = [r[0] for r in conn.execute("SELECT code FROM stock_cn").fetchall()]
    count = 0
    for i in range(0, len(codes), 50):
        batch = codes[i:i+50]
        symbols = " ".join(
            c + (".SS" if c.startswith("6") else ".SZ") for c in batch
        )
        tickers = yf.Tickers(symbols)
        for code in batch:
            sym = code + (".SS" if code.startswith("6") else ".SZ")
            try:
                cap = tickers.tickers[sym].fast_info.get("marketCap", 0) or 0
                if cap > 0:
                    conn.execute("UPDATE stock_cn SET market_cap=? WHERE code=?", (cap, code))
                    count += 1
            except:
                pass
        conn.commit()
        print(f"  市值批次 {i//50+1}: {count} 只已更新")

    print(f"  stock_cn 完成: {len(codes)} 只, 市值更新 {count} 只")


def sync_us(conn):
    """同步 S&P 500(从 Wikipedia 实时拉) + yfinance 更新市值。"""
    import io
    import pandas as pd

    # 实时拉最新 S&P 500 成分股
    print("  从 Wikipedia 拉 S&P 500 列表...")
    try:
        html = __import__("httpx").get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15
        ).text
        df = pd.read_html(io.StringIO(html))[0]
        stocks = []
        for _, row in df.iterrows():
            t = str(row["Symbol"]).replace(".", "-")
            if t in ("GOOG", "BRK-A"):
                continue
            stocks.append({"ticker": t, "name": row["Security"], "sector": row["GICS Sector"]})
    except Exception as e:
        print(f"  Wikipedia 拉取失败({e}),用本地 sp500.json")
        sp500_path = DATA_DIR / "sp500.json"
        if not sp500_path.exists():
            print("  [跳过] sp500.json 也不存在")
            return
        with open(sp500_path) as f:
            stocks = [s for s in json.load(f) if s["ticker"] not in ("GOOG", "BRK-A")]

    latest_tickers = set(s["ticker"] for s in stocks if s["ticker"] not in {"GOOG", "BRK-A"})
    existing = set(r[0] for r in conn.execute("SELECT ticker FROM stock_us").fetchall())

    added = latest_tickers - existing
    for s in stocks:
        if s["ticker"] in added:
            conn.execute("INSERT OR IGNORE INTO stock_us (ticker, name, sector) VALUES (?,?,?)",
                         (s["ticker"], s["name"], s.get("sector", "")))
    if added:
        print(f"  新增 {len(added)} 只")

    removed = existing - latest_tickers
    if removed:
        for t in removed:
            conn.execute("DELETE FROM stock_us WHERE ticker=?", (t,))
        print(f"  剔除 {len(removed)} 只")

    conn.commit()

    # yfinance 更新市值
    tickers = [r[0] for r in conn.execute("SELECT ticker FROM stock_us").fetchall()]
    count = 0
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i+50]
        data = yf.Tickers(" ".join(batch))
        for t in batch:
            try:
                cap = data.tickers[t].fast_info.get("marketCap", 0) or 0
                if cap > 0:
                    conn.execute("UPDATE stock_us SET market_cap=? WHERE ticker=?", (cap, t))
                    count += 1
            except:
                pass
        conn.commit()
        print(f"  市值批次 {i//50+1}: {count} 只已更新")

    print(f"  stock_us 完成: {len(tickers)} 只, 市值更新 {count} 只")


def main():
    market = "all"
    if "--market" in sys.argv:
        idx = sys.argv.index("--market")
        market = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "all"

    conn = get_db()

    if market in ("cn", "all"):
        print("同步 A 股(沪深300)...")
        sync_cn(conn)
    if market in ("us", "all"):
        print("同步美股(S&P 500)...")
        sync_us(conn)

    conn.close()
    print("完成。")


if __name__ == "__main__":
    main()
