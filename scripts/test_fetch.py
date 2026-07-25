"""跑通验证:登录校验 + 拉 list 时间线 + 抓指定 KOL 最近推文。

用法:
    .venv/bin/python scripts/test_fetch.py                    # 只验证 list
    .venv/bin/python scripts/test_fetch.py handle1 handle2     # 额外抓这些 handle 的推文

list_id 默认用蔡老师给的那个;可用 --list=xxx 覆盖。
"""
import asyncio
import sys
from pathlib import Path

from twscrape import API

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "accounts.db"
DEFAULT_LIST_ID = 1725663780337738162


async def main() -> None:
    args = [a for a in sys.argv[1:]]
    list_id = DEFAULT_LIST_ID
    handles = []
    for a in args:
        if a.startswith("--list="):
            list_id = int(a.split("=", 1)[1])
        else:
            handles.append(a.lstrip("@"))

    api = API(str(DB_PATH))

    infos = await api.pool.accounts_info()
    active = [i for i in infos if i["active"]]
    print(f"账号池:{len(infos)} 个,active={len(active)}")
    if not active:
        print("[错误] 没有 active 账号。请先 .venv/bin/python scripts/add_account.py")
        sys.exit(1)

    # 1) 验证能读 list 时间线
    print(f"\n=== list {list_id} 最近推文(取 5 条)===")
    n = 0
    async for tw in api.list_timeline(list_id, limit=5):
        n += 1
        print(f"[{n}] @{tw.user.username} · {tw.date:%Y-%m-%d %H:%M} · "
              f"❤{tw.likeCount} 🔁{tw.retweetCount}")
        print(f"    {tw.rawContent[:120].replace(chr(10),' ')}")
    print(f"list 抓到 {n} 条。")

    # 2) 指定 handle 抓推文
    for h in handles:
        print(f"\n=== @{h} 最近推文(取 5 条)===")
        user = await api.user_by_login(h)
        if not user:
            print(f"    找不到 @{h},请确认 handle 是否正确。")
            continue
        print(f"    {user.displayname} · 粉丝 {user.followersCount} · id={user.id}")
        m = 0
        async for tw in api.user_tweets(user.id, limit=5):
            m += 1
            print(f"    [{m}] {tw.date:%Y-%m-%d %H:%M} · ❤{tw.likeCount} · "
                  f"{tw.rawContent[:100].replace(chr(10),' ')}")
        print(f"    @{h} 抓到 {m} 条。")


if __name__ == "__main__":
    asyncio.run(main())
