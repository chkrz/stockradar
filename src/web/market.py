"""S&P 500 气泡图后端:从 DB 读快照。"""
from fastapi import APIRouter
from src.db import get_db

router = APIRouter()


@router.get("/api/market/snapshot")
async def market_snapshot():
    conn = get_db()
    rows = conn.execute(
        """SELECT s.ticker, su.name, su.sector, s.price, s.change_pct, su.market_cap
           FROM snapshot_us s JOIN stock_us su ON s.ticker=su.ticker
           WHERE s.timestamp = (SELECT MAX(timestamp) FROM snapshot_us)"""
    ).fetchall()
    conn.close()
    return {
        "stocks": [dict(r) for r in rows],
        "count": len(rows),
    }
