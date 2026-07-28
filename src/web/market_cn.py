"""A 股沪深300气泡图后端:从 DB 读快照。"""
from fastapi import APIRouter
from src.db import get_db

router = APIRouter()


@router.get("/api/market/cn/snapshot")
async def cn_snapshot():
    conn = get_db()
    rows = conn.execute(
        """SELECT s.code as ticker, sc.name, sc.sector, s.price, s.change_pct, sc.market_cap
           FROM snapshot_cn s JOIN stock_cn sc ON s.code=sc.code
           WHERE s.timestamp = (SELECT MAX(timestamp) FROM snapshot_cn)"""
    ).fetchall()
    conn.close()
    return {
        "stocks": [dict(r) for r in rows],
        "count": len(rows),
    }
