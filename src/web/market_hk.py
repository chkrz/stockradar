"""港股恒生科技气泡图后端:从 DB 读快照。"""
from fastapi import APIRouter
from src.db import get_db

router = APIRouter()


@router.get("/api/market/hk/snapshot")
async def hk_snapshot():
    conn = get_db()
    rows = conn.execute(
        """SELECT s.code as ticker, sh.name, sh.sector, s.price, s.change_pct,
                  COALESCE(NULLIF(s.market_cap, 0), sh.market_cap) as market_cap
           FROM snapshot_hk s JOIN stock_hk sh ON s.code=sh.code
           WHERE s.timestamp = (SELECT MAX(timestamp) FROM snapshot_hk)"""
    ).fetchall()
    conn.close()
    return {
        "stocks": [dict(r) for r in rows],
        "count": len(rows),
    }
