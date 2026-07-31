"""StockRadar Web — 推文浏览 + 大V视角 + 股票视角 + 市场地图。"""
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from src.db import get_db
from src.web.market import router as market_router
from src.web.market_cn import router as market_cn_router
from src.web.market_hk import router as market_hk_router

app = FastAPI(title="StockRadar")
app.include_router(market_router)
app.include_router(market_cn_router)
app.include_router(market_hk_router)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _get_nav(conn):
    return [dict(r) for r in conn.execute(
        "SELECT handle, display_name FROM kol WHERE enabled=1 ORDER BY handle"
    ).fetchall()]


@app.get("/market", response_class=HTMLResponse)
async def market_page(request: Request):
    conn = get_db()
    kols = _get_nav(conn)
    conn.close()
    return templates.TemplateResponse(request=request, name="market.html", context={"kols": kols})


@app.get("/market/cn", response_class=HTMLResponse)
async def market_cn_page(request: Request):
    conn = get_db()
    kols = _get_nav(conn)
    conn.close()
    return templates.TemplateResponse(request=request, name="market_cn.html", context={"kols": kols})


@app.get("/market/hk", response_class=HTMLResponse)
async def market_hk_page(request: Request):
    conn = get_db()
    kols = _get_nav(conn)
    conn.close()
    return templates.TemplateResponse(request=request, name="market_hk.html", context={"kols": kols})


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    conn = get_db()
    kol_count = conn.execute("SELECT COUNT(*) FROM kol WHERE enabled=1").fetchone()[0]
    tweet_count = conn.execute("SELECT COUNT(*) FROM tweet").fetchone()[0]
    opinion_count = conn.execute("SELECT COUNT(*) FROM stock_opinion").fetchone()[0]
    stock_count = conn.execute("SELECT COUNT(*) FROM kol_stock_view").fetchone()[0]
    conn.close()
    return templates.TemplateResponse(request=request, name="home.html", context={
        "kol_count": kol_count, "tweet_count": tweet_count,
        "opinion_count": opinion_count, "stock_count": stock_count,
    })


@app.get("/tweets", response_class=HTMLResponse)
async def tweets_feed(
    request: Request,
    kol: str = Query("", description="按 handle 过滤"),
    q: str = Query("", description="关键词搜索"),
    page: int = Query(1, ge=1),
):
    per_page = 50
    conn = get_db()
    kols = _get_nav(conn)

    where_clauses, params = [], []
    if kol:
        where_clauses.append("k.handle = ?")
        params.append(kol.lower())
    if q:
        where_clauses.append("t.raw_content LIKE ?")
        params.append(f"%{q}%")
    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count = conn.execute(
        f"SELECT COUNT(*) FROM tweet t JOIN kol k ON t.kol_id=k.id{where_sql}", params
    ).fetchone()[0]

    offset = (page - 1) * per_page
    tweets = [dict(r) for r in conn.execute(
        f"""SELECT t.*, k.handle, k.display_name
            FROM tweet t JOIN kol k ON t.kol_id=k.id
            {where_sql} ORDER BY t.created_at DESC LIMIT ? OFFSET ?""",
        params + [per_page, offset]
    ).fetchall()]

    total_pages = max(1, (count + per_page - 1) // per_page)
    conn.close()
    return templates.TemplateResponse(request=request, name="index.html", context={
        "tweets": tweets, "kols": kols, "current_kol": kol, "q": q,
        "page": page, "total_pages": total_pages, "total_count": count,
    })


@app.get("/kol/{handle}", response_class=HTMLResponse)
async def kol_view(request: Request, handle: str):
    conn = get_db()
    kols = _get_nav(conn)
    kol = conn.execute("SELECT * FROM kol WHERE handle=?", (handle.lower(),)).fetchone()
    if not kol:
        conn.close()
        return HTMLResponse("KOL not found", status_code=404)
    kol = dict(kol)

    views = [dict(r) for r in conn.execute(
        """SELECT * FROM kol_stock_view WHERE kol_id=?
           ORDER BY mention_count_30d DESC""", (kol["id"],)
    ).fetchall()]

    conn.close()
    return templates.TemplateResponse(request=request, name="kol_view.html", context={
        "kols": kols, "kol": kol, "views": views,
    })


@app.get("/stocks", response_class=HTMLResponse)
async def stocks_list(request: Request):
    conn = get_db()
    kols = _get_nav(conn)

    stocks = [dict(r) for r in conn.execute(
        """SELECT ticker,
                  COUNT(DISTINCT kol_id) as kol_count,
                  SUM(mention_count_30d) as total_30d,
                  SUM(mention_count_7d) as total_7d
           FROM kol_stock_view
           GROUP BY ticker ORDER BY total_30d DESC"""
    ).fetchall()]

    for s in stocks:
        dirs = [r[0] for r in conn.execute(
            "SELECT direction FROM kol_stock_view WHERE ticker=?", (s["ticker"],)
        ).fetchall()]
        bull = dirs.count("bullish")
        bear = dirs.count("bearish")
        s["consensus"] = "看多" if bull > bear else ("看空" if bear > bull else "分歧")

    conn.close()
    return templates.TemplateResponse(request=request, name="stocks.html", context={
        "kols": kols, "stocks": stocks,
    })


@app.get("/stock/{ticker}", response_class=HTMLResponse)
async def stock_view(request: Request, ticker: str):
    conn = get_db()
    kols = _get_nav(conn)
    ticker = ticker.upper()

    views = [dict(r) for r in conn.execute(
        """SELECT v.*, k.handle, k.display_name
           FROM kol_stock_view v JOIN kol k ON v.kol_id=k.id
           WHERE v.ticker=? ORDER BY v.mention_count_30d DESC""", (ticker,)
    ).fetchall()]

    opinions = [dict(r) for r in conn.execute(
        """SELECT so.*, t.raw_content, t.created_at, t.like_count, t.url, k.handle, k.display_name
           FROM stock_opinion so
           JOIN tweet t ON so.tweet_id=t.id
           JOIN kol k ON so.kol_id=k.id
           WHERE so.ticker=? ORDER BY t.created_at DESC LIMIT 30""", (ticker,)
    ).fetchall()]

    conn.close()
    return templates.TemplateResponse(request=request, name="stock_view.html", context={
        "kols": kols, "ticker": ticker, "views": views, "opinions": opinions,
    })
