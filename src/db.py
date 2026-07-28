"""SQLite 数据库:KOL 名单、推文存储、ticker 提及。"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "stockradar.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kol (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handle TEXT UNIQUE NOT NULL,
    display_name TEXT DEFAULT '',
    category TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    user_id INTEGER,
    last_tweet_id INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tweet (
    id INTEGER PRIMARY KEY,
    kol_id INTEGER NOT NULL,
    raw_content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_retweet INTEGER DEFAULT 0,
    is_reply INTEGER DEFAULT 0,
    is_quote INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    retweet_count INTEGER DEFAULT 0,
    reply_count INTEGER DEFAULT 0,
    view_count INTEGER DEFAULT 0,
    url TEXT DEFAULT '',
    fetched_at TEXT NOT NULL,
    analyzed INTEGER DEFAULT 0,
    FOREIGN KEY (kol_id) REFERENCES kol(id)
);

CREATE TABLE IF NOT EXISTS mention (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    match_type TEXT DEFAULT 'symbol',
    FOREIGN KEY (tweet_id) REFERENCES tweet(id)
);

CREATE INDEX IF NOT EXISTS idx_tweet_kol ON tweet(kol_id);
CREATE INDEX IF NOT EXISTS idx_tweet_created ON tweet(created_at);
CREATE INDEX IF NOT EXISTS idx_mention_ticker ON mention(ticker);

CREATE TABLE IF NOT EXISTS stock_opinion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id INTEGER NOT NULL,
    kol_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT DEFAULT 'neutral',
    summary TEXT DEFAULT '',
    catalyst TEXT DEFAULT '',
    analyzed_at TEXT NOT NULL,
    FOREIGN KEY (tweet_id) REFERENCES tweet(id),
    FOREIGN KEY (kol_id) REFERENCES kol(id),
    UNIQUE(tweet_id, ticker)
);

CREATE TABLE IF NOT EXISTS kol_stock_view (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kol_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT DEFAULT 'neutral',
    summary TEXT DEFAULT '',
    mention_count_30d INTEGER DEFAULT 0,
    mention_count_7d INTEGER DEFAULT 0,
    first_mentioned_at TEXT,
    last_updated_at TEXT,
    FOREIGN KEY (kol_id) REFERENCES kol(id),
    UNIQUE(kol_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_opinion_kol_ticker ON stock_opinion(kol_id, ticker);
CREATE INDEX IF NOT EXISTS idx_opinion_ticker ON stock_opinion(ticker);
CREATE INDEX IF NOT EXISTS idx_view_ticker ON kol_stock_view(ticker);

CREATE TABLE IF NOT EXISTS stock_us (
    ticker TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    sector TEXT DEFAULT '',
    market_cap REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stock_cn (
    code TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    sector TEXT DEFAULT '',
    market_cap REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS snapshot_us (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    price REAL DEFAULT 0,
    change_pct REAL DEFAULT 0,
    volume REAL DEFAULT 0,
    market_cap REAL DEFAULT 0,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_cn (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    price REAL DEFAULT 0,
    change_pct REAL DEFAULT 0,
    volume REAL DEFAULT 0,
    market_cap REAL DEFAULT 0,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snap_us_ts ON snapshot_us(timestamp);
CREATE INDEX IF NOT EXISTS idx_snap_cn_ts ON snapshot_cn(timestamp);

CREATE TABLE IF NOT EXISTS stock_hk (
    code TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    sector TEXT DEFAULT '',
    market_cap REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS snapshot_hk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    price REAL DEFAULT 0,
    change_pct REAL DEFAULT 0,
    volume REAL DEFAULT 0,
    market_cap REAL DEFAULT 0,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snap_hk_ts ON snapshot_hk(timestamp);
"""


def get_db(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def upsert_kol(conn: sqlite3.Connection, handle: str, **kwargs) -> int:
    handle = handle.lower().lstrip("@")
    row = conn.execute("SELECT id FROM kol WHERE handle=?", (handle,)).fetchone()
    if row:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        if sets:
            conn.execute(f"UPDATE kol SET {sets} WHERE handle=?",
                         (*kwargs.values(), handle))
            conn.commit()
        return row["id"]
    cols = ["handle"] + list(kwargs.keys())
    placeholders = ",".join(["?"] * len(cols))
    conn.execute(f"INSERT INTO kol ({','.join(cols)}) VALUES ({placeholders})",
                 (handle, *kwargs.values()))
    conn.commit()
    return conn.execute("SELECT id FROM kol WHERE handle=?", (handle,)).fetchone()["id"]


def list_kols(conn: sqlite3.Connection, enabled_only: bool = True) -> list[dict]:
    q = "SELECT * FROM kol"
    if enabled_only:
        q += " WHERE enabled=1"
    return [dict(r) for r in conn.execute(q).fetchall()]


def get_kol(conn: sqlite3.Connection, handle: str) -> dict | None:
    row = conn.execute("SELECT * FROM kol WHERE handle=?",
                       (handle.lower().lstrip("@"),)).fetchone()
    return dict(row) if row else None


def insert_tweet(conn: sqlite3.Connection, tweet: dict) -> bool:
    try:
        conn.execute(
            """INSERT OR IGNORE INTO tweet
            (id, kol_id, raw_content, created_at, is_retweet, is_reply, is_quote,
             like_count, retweet_count, reply_count, view_count, url, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tweet["id"], tweet["kol_id"], tweet["raw_content"], tweet["created_at"],
             tweet.get("is_retweet", 0), tweet.get("is_reply", 0), tweet.get("is_quote", 0),
             tweet.get("like_count", 0), tweet.get("retweet_count", 0),
             tweet.get("reply_count", 0), tweet.get("view_count", 0),
             tweet.get("url", ""),
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_kol_cursor(conn: sqlite3.Connection, handle: str, last_tweet_id: int):
    conn.execute("UPDATE kol SET last_tweet_id=? WHERE handle=?",
                 (last_tweet_id, handle.lower().lstrip("@")))
    conn.commit()


def insert_mentions(conn: sqlite3.Connection, tweet_id: int, tickers: list[str]):
    for t in tickers:
        conn.execute(
            "INSERT OR IGNORE INTO mention (tweet_id, ticker, match_type) VALUES (?,?,?)",
            (tweet_id, t.upper(), "symbol"))
    conn.commit()


def get_unanalyzed_tweets(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        """SELECT t.*, k.handle, k.display_name
           FROM tweet t JOIN kol k ON t.kol_id=k.id
           WHERE t.analyzed=0
           ORDER BY t.created_at DESC LIMIT ?""", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def mark_analyzed(conn: sqlite3.Connection, tweet_ids: list[int]):
    conn.executemany("UPDATE tweet SET analyzed=1 WHERE id=?",
                     [(tid,) for tid in tweet_ids])
    conn.commit()


def insert_stock_opinion(conn: sqlite3.Connection, opinion: dict):
    conn.execute(
        """INSERT OR REPLACE INTO stock_opinion
        (tweet_id, kol_id, ticker, direction, summary, catalyst, analyzed_at)
        VALUES (?,?,?,?,?,?,?)""",
        (opinion["tweet_id"], opinion["kol_id"], opinion["ticker"],
         opinion["direction"], opinion["summary"], opinion.get("catalyst", ""),
         datetime.now(timezone.utc).isoformat()))
    conn.commit()


def upsert_kol_stock_view(conn: sqlite3.Connection, kol_id: int, ticker: str,
                          direction: str, summary: str,
                          count_30d: int, count_7d: int):
    first = conn.execute(
        "SELECT MIN(analyzed_at) FROM stock_opinion WHERE kol_id=? AND ticker=?",
        (kol_id, ticker)).fetchone()[0]
    conn.execute(
        """INSERT INTO kol_stock_view
        (kol_id, ticker, direction, summary, mention_count_30d, mention_count_7d,
         first_mentioned_at, last_updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(kol_id, ticker) DO UPDATE SET
            direction=excluded.direction, summary=excluded.summary,
            mention_count_30d=excluded.mention_count_30d,
            mention_count_7d=excluded.mention_count_7d,
            last_updated_at=excluded.last_updated_at""",
        (kol_id, ticker, direction, summary, count_30d, count_7d,
         first, datetime.now(timezone.utc).isoformat()))
    conn.commit()
