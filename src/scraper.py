"""抓取逻辑:从 twscrape 拉推文,入库。"""
import asyncio
from pathlib import Path

from twscrape import API

from .db import (
    get_db, list_kols, get_kol, insert_tweet,
    update_kol_cursor, insert_mentions, upsert_kol,
)
from .tickers import extract_tickers

ACCOUNTS_DB = Path(__file__).resolve().parent.parent / "data" / "accounts.db"


def _tweet_to_dict(tw, kol_id: int) -> dict:
    return {
        "id": tw.id,
        "kol_id": kol_id,
        "raw_content": tw.rawContent,
        "created_at": tw.date.isoformat(),
        "is_retweet": 1 if tw.rawContent.startswith("RT @") else 0,
        "is_reply": 1 if tw.inReplyToTweetId else 0,
        "is_quote": 1 if tw.quotedTweet else 0,
        "like_count": tw.likeCount,
        "retweet_count": tw.retweetCount,
        "reply_count": tw.replyCount,
        "view_count": getattr(tw, "viewCount", 0) or 0,
        "url": f"https://x.com/{tw.user.username}/status/{tw.id}",
    }


async def fetch_kol_tweets(api: API, kol_row: dict, limit: int = 50) -> list[dict]:
    user_id = kol_row["user_id"]
    if not user_id:
        user = await api.user_by_login(kol_row["handle"])
        if not user:
            print(f"  [跳过] 找不到 @{kol_row['handle']}")
            return []
        user_id = user.id

    last_id = kol_row.get("last_tweet_id", 0) or 0
    tweets = []
    old_count = 0
    async for tw in api.user_tweets(user_id, limit=limit):
        if tw.id <= last_id:
            old_count += 1
            if old_count >= 10:
                break
            continue
        tweets.append(_tweet_to_dict(tw, kol_row["id"]))
    return tweets


async def fetch_all(db_path: Path | None = None, limit: int = 50) -> dict:
    conn = get_db(db_path) if db_path else get_db()
    api = API(str(ACCOUNTS_DB))

    kols = list_kols(conn, enabled_only=True)
    stats = {"kols": len(kols), "new_tweets": 0, "tickers_found": 0}

    for kol in kols:
        print(f"\n抓取 @{kol['handle']}...")
        if not kol["user_id"]:
            user = await api.user_by_login(kol["handle"])
            if not user:
                print(f"  [跳过] 找不到")
                continue
            upsert_kol(conn, kol["handle"], user_id=user.id, display_name=user.displayname)
            kol["user_id"] = user.id

        tweets = await fetch_kol_tweets(api, kol, limit=limit)
        if not tweets:
            print(f"  无新推文")
            continue

        max_id = 0
        for t in tweets:
            inserted = insert_tweet(conn, t)
            if inserted:
                stats["new_tweets"] += 1
                tickers = extract_tickers(t["raw_content"])
                if tickers:
                    insert_mentions(conn, t["id"], tickers)
                    stats["tickers_found"] += len(tickers)
            max_id = max(max_id, t["id"])

        if max_id > (kol.get("last_tweet_id") or 0):
            update_kol_cursor(conn, kol["handle"], max_id)
        print(f"  新增 {len(tweets)} 条,提取 ticker {sum(len(extract_tickers(t['raw_content'])) for t in tweets)} 个")

    conn.close()
    return stats
