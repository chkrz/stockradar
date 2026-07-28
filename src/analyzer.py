"""LLM 批量分析推文:提取股票观点 + 更新 kol_stock_view。"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .db import (
    get_db, get_unanalyzed_tweets, mark_analyzed,
    insert_stock_opinion, upsert_kol_stock_view,
)

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts"

load_dotenv(ROOT / ".env")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://models-proxy.stepfun-inc.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-pro")
BATCH_SIZE = int(os.getenv("ANALYZE_BATCH_SIZE", "10"))
MAX_TWEET_LEN = int(os.getenv("ANALYZE_MAX_TWEET_LEN", "500"))


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _call_llm(prompt: str, max_tokens: int = 8192) -> str:
    for attempt in range(2):
        try:
            resp = httpx.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
                timeout=180,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (httpx.ReadTimeout, httpx.ConnectTimeout):
            if attempt == 0:
                print("    超时,重试...")
                continue
            raise
    return ""


def _parse_json(text: str) -> list | dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("LLM 返回空内容")
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        if start == -1:
            start = text.find("{")
        if start >= 0:
            return json.loads(text[start:])
        raise


# ─── 批量提取 ───────────────────────────────────────────────

def analyze_batch(tweets: list[dict], conn) -> set[tuple[int, str]]:
    """分析一批推文,返回受影响的 (kol_id, ticker) 集合。"""
    prompt = _load_prompt("extract.txt")
    for tw in tweets:
        content = tw["raw_content"][:MAX_TWEET_LEN]
        prompt += f"\n[tweet_id={tw['id']}] @{tw['handle']} ({tw['created_at'][:10]}):\n{content}\n"

    raw = _call_llm(prompt)
    results = _parse_json(raw)

    affected = set()
    tweet_map = {tw["id"]: tw for tw in tweets}

    for item in results:
        tid = item["tweet_id"]
        tw = tweet_map.get(tid)
        if not tw:
            continue
        for s in item.get("stocks", []):
            insert_stock_opinion(conn, {
                "tweet_id": tid,
                "kol_id": tw["kol_id"],
                "ticker": s["ticker"].upper(),
                "direction": s.get("direction", "neutral"),
                "summary": s.get("summary", ""),
                "catalyst": s.get("catalyst", ""),
            })
            affected.add((tw["kol_id"], s["ticker"].upper()))

    mark_analyzed(conn, [tw["id"] for tw in tweets])
    return affected


# ─── 总体观点更新 ────────────────────────────────────────────

def update_kol_stock_views(conn, affected: set[tuple[int, str]]):
    """对受影响的 kol×ticker 对,重新生成总体观点。"""
    now = datetime.now(timezone.utc)
    d30 = (now - timedelta(days=30)).isoformat()
    d7 = (now - timedelta(days=7)).isoformat()

    for kol_id, ticker in affected:
        opinions_30d = [dict(r) for r in conn.execute(
            """SELECT so.direction, so.summary, so.catalyst, t.created_at
               FROM stock_opinion so JOIN tweet t ON so.tweet_id=t.id
               WHERE so.kol_id=? AND so.ticker=? AND t.created_at>=?
               ORDER BY t.created_at""",
            (kol_id, ticker, d30)).fetchall()]

        count_30d = len(opinions_30d)
        count_7d = sum(1 for o in opinions_30d if o["created_at"] >= d7)

        if not opinions_30d:
            continue

        kol_row = conn.execute("SELECT handle FROM kol WHERE id=?", (kol_id,)).fetchone()
        handle = kol_row["handle"] if kol_row else "unknown"

        if count_30d <= 3:
            latest = opinions_30d[-1]
            upsert_kol_stock_view(conn, kol_id, ticker,
                                  latest["direction"], latest["summary"],
                                  count_30d, count_7d)
        else:
            opinion_text = "\n".join(
                f"- {o['created_at'][:10]} [{o['direction']}] {o['summary']}"
                + (f" (催化剂:{o['catalyst']})" if o["catalyst"] else "")
                for o in opinions_30d
            )
            prompt = _load_prompt("summarize.txt").format(
                ticker=ticker, opinions=opinion_text
            )
            raw = _call_llm(prompt, max_tokens=1024)
            result = _parse_json(raw)
            upsert_kol_stock_view(conn, kol_id, ticker,
                                  result.get("direction", "neutral"),
                                  result.get("summary", ""),
                                  count_30d, count_7d)

        print(f"  更新 @{handle} × {ticker}: {count_30d}条(30d) {count_7d}条(7d)")


# ─── 入口 ───────────────────────────────────────────────────

def run_analysis(limit: int = 100):
    conn = get_db()
    tweets = get_unanalyzed_tweets(conn, limit=limit)
    if not tweets:
        print("没有未分析的推文。")
        conn.close()
        return

    print(f"待分析: {len(tweets)} 条推文")
    all_affected = set()

    for i in range(0, len(tweets), BATCH_SIZE):
        batch = tweets[i:i + BATCH_SIZE]
        print(f"\n批次 {i // BATCH_SIZE + 1}: {len(batch)} 条")
        try:
            affected = analyze_batch(batch, conn)
            all_affected |= affected
            print(f"  提取到 {len(affected)} 个 KOL×股票 对")
        except Exception as e:
            print(f"  [失败] {e}")
            mark_analyzed(conn, [tw["id"] for tw in batch])
            continue

    if all_affected:
        print(f"\n更新 {len(all_affected)} 个总体观点...")
        update_kol_stock_views(conn, all_affected)

    conn.close()
    print("\n分析完成。")
