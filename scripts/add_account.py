"""把 .env 里的抓取小号加入 twscrape 账号池。

用法: .venv/bin/python scripts/add_account.py
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from twscrape import API

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "accounts.db"


def _require(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        print(f"[错误] .env 缺少 {name},请填写后重试。")
        sys.exit(1)
    return val


async def main() -> None:
    load_dotenv(ROOT / ".env")
    DATA_DIR.mkdir(exist_ok=True)

    username = _require("X_ACCOUNT_USERNAME")
    auth_token = _require("X_AUTH_TOKEN")
    ct0 = _require("X_CT0")

    password = os.getenv("X_PASSWORD", "").strip() or "-"
    email = os.getenv("X_EMAIL", "").strip() or f"{username}@example.com"
    email_password = os.getenv("X_EMAIL_PASSWORD", "").strip() or "-"
    proxy = os.getenv("X_PROXY", "").strip() or None

    cookies = f"auth_token={auth_token}; ct0={ct0}"

    api = API(str(DB_PATH))

    try:
        await api.pool.delete_accounts([username])
    except Exception:
        pass

    await api.pool.add_account(
        username=username,
        password=password,
        email=email,
        email_password=email_password,
        cookies=cookies,
        proxy=proxy,
    )
    print(f"[ok] 已添加 {username},正在激活…")
    await api.pool.login_all()

    print("\n账号池:")
    for info in await api.pool.accounts_info():
        print(f"  {info['username']}: active={info['active']}")


if __name__ == "__main__":
    asyncio.run(main())
