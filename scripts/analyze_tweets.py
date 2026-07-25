"""批量分析未处理推文:提取股票观点 + 更新总体观点。

用法: .venv/bin/python scripts/analyze_tweets.py [--limit N]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stockradar.analyzer import run_analysis


def main():
    limit = 100
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    run_analysis(limit=limit)


if __name__ == "__main__":
    main()
