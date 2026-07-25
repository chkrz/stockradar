"""S&P 500 气泡图后端:snapshot + WebSocket 实时推送。"""
import asyncio
import json
from pathlib import Path

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
SP500_PATH = DATA_DIR / "sp500.json"

ALPACA_KEY = "PKY2IU4GAJQKC5FXXDAVMCQ7CN"
ALPACA_SECRET = "ExVop4ejfi3Dcootp8tnCZaYoabJL2Q5wv8oDj72nGPd"
ALPACA_DATA_URL = "https://data.alpaca.markets"
ALPACA_HEADERS = {
    "APCA-API-KEY-ID": ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
}

router = APIRouter()


def _load_sp500() -> list[dict]:
    with open(SP500_PATH) as f:
        return json.load(f)


async def _fetch_snapshots(tickers: list[str]) -> dict:
    """批量拿 snapshot(分批,每批最多 50 只)。"""
    # 去掉 dual-class 重复
    FILTER_OUT = {"GOOG", "BRK-A", "GOOGL-A"}
    tickers = [t for t in tickers if t not in FILTER_OUT]

    all_data = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for i in range(0, len(tickers), 50):
            batch = tickers[i:i+50]
            symbols = ",".join(batch)
            resp = await client.get(
                f"{ALPACA_DATA_URL}/v2/stocks/snapshots",
                headers=ALPACA_HEADERS,
                params={"symbols": symbols, "feed": "iex"},
            )
            if resp.status_code == 200:
                all_data.update(resp.json())
    return all_data


@router.get("/api/market/snapshot")
async def market_snapshot():
    """返回 S&P 500 全量 snapshot。"""
    stocks = _load_sp500()
    tickers = [s["ticker"] for s in stocks]
    snapshots = await _fetch_snapshots(tickers)

    sector_map = {s["ticker"]: s["sector"] for s in stocks}
    name_map = {s["ticker"]: s["name"] for s in stocks}
    cap_map = {s["ticker"]: s.get("market_cap", 0) for s in stocks}

    result = []
    for ticker, snap in snapshots.items():
        daily = snap.get("dailyBar", {})
        prev = snap.get("prevDailyBar", {})
        trade = snap.get("latestTrade", {})

        price = trade.get("p", 0) or daily.get("c", 0)
        prev_close = prev.get("c", 0)
        if not prev_close or not price:
            continue

        change_pct = (price - prev_close) / prev_close * 100

        result.append({
            "ticker": ticker,
            "name": name_map.get(ticker, ""),
            "sector": sector_map.get(ticker, "Other"),
            "price": round(price, 2),
            "change_pct": round(change_pct, 2),
            "market_cap": cap_map.get(ticker, 0),
        })

    return {"stocks": result, "count": len(result)}


# WebSocket: 每 30 秒推送最新 snapshot
connected_clients: set[WebSocket] = set()


@router.websocket("/ws/market")
async def market_ws(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.discard(websocket)


async def _broadcast_loop():
    """后台任务:定期拉 snapshot 推送给所有 WS 客户端。"""
    stocks = _load_sp500()
    tickers = [s["ticker"] for s in stocks]
    sector_map = {s["ticker"]: s["sector"] for s in stocks}
    name_map = {s["ticker"]: s["name"] for s in stocks}

    while True:
        await asyncio.sleep(30)
        if not connected_clients:
            continue
        try:
            snapshots = await _fetch_snapshots(tickers)
            result = []
            for ticker, snap in snapshots.items():
                daily = snap.get("dailyBar", {})
                prev = snap.get("prevDailyBar", {})
                trade = snap.get("latestTrade", {})
                price = trade.get("p", 0) or daily.get("c", 0)
                prev_close = prev.get("c", 0)
                if not prev_close or not price:
                    continue
                change_pct = (price - prev_close) / prev_close * 100
                result.append({
                    "ticker": ticker,
                    "name": name_map.get(ticker, ""),
                    "sector": sector_map.get(ticker, "Other"),
                    "price": round(price, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": daily.get("v", 0),
                })

            payload = json.dumps({"stocks": result})
            dead = set()
            for ws in connected_clients:
                try:
                    await ws.send_text(payload)
                except:
                    dead.add(ws)
            connected_clients -= dead
        except Exception as e:
            print(f"[broadcast] error: {e}")


@router.on_event("startup")
async def start_broadcast():
    asyncio.create_task(_broadcast_loop())
