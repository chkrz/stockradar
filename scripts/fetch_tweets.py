"""批量抓取所有 enabled KOL 的最新推文,去重入库。

用法: .venv/bin/python scripts/fetch_all.py [--limit N]
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.scraper import fetch_all


async def main():
    limit = 50
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    print(f"开始批量抓取 (limit={limit}/KOL)...")
    stats = await fetch_all(limit=limit)
    print(f"\n完成: {stats['kols']} 个 KOL, "
          f"新增 {stats['new_tweets']} 条推文, "
          f"提取 {stats['tickers_found']} 个 ticker")


if __name__ == "__main__":
    asyncio.run(main())
