"""自动登录 X 获取 cookie,更新 twscrape 账号池。

用法: .venv/bin/python scripts/refresh_cookie.py

需要 .env 中:
  X_LOGIN_USERNAME  — X 登录用户名/邮箱/手机号
  X_LOGIN_PASSWORD  — X 登录密码
  X_LOGIN_EMAIL     — (可选) X 有时要求验证邮箱/手机号
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _require(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        print(f"[错误] .env 缺少 {name}")
        sys.exit(1)
    return val


def get_cookies_via_playwright() -> dict:
    """自动登录 X 获取 cookie。遇到验证时打开有头浏览器等待手动处理。"""
    from playwright.sync_api import sync_playwright

    username = _require("X_ACCOUNT_USERNAME")
    password = _require("X_PASSWORD")
    email = os.getenv("X_EMAIL", "").strip()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()

        print("打开登录页...")
        page.goto("https://x.com/i/flow/login", timeout=60000)
        page.wait_for_timeout(5000)

        # 输入用户名
        print(f"输入用户名: @{username}")
        username_input = page.get_by_label("电子邮箱或用户名").or_(
            page.get_by_label("Email or username")).or_(
            page.get_by_placeholder("电子邮箱或用户名")).or_(
            page.get_by_placeholder("Email or username"))
        username_input.wait_for(timeout=20000)
        username_input.click()
        page.keyboard.type(f"@{username}", delay=50)
        page.wait_for_timeout(500)
        page.keyboard.press("Enter")
        page.wait_for_timeout(4000)

        # 检查是否需要额外验证(手机号/邮箱)
        phone_check = page.locator('text=Enter your phone number')
        email_check = page.locator('input[data-testid="ocfEnterTextTextInput"]')

        if phone_check.count() > 0 or email_check.count() > 0:
            if email_check.count() > 0 and email:
                print(f"需要邮箱验证,自动填入: {email[:3]}***")
                email_check.fill(email)
                page.locator('button:has-text("Continue")').or_(
                    page.locator('button:has-text("Next")')).first.click()
                page.wait_for_timeout(3000)
            else:
                print("\n⚠️  X 要求额外验证(手机号),请在浏览器窗口中手动完成。")
                print("完成后脚本会自动继续...\n")
                # 等待验证完成(密码框出现)
                page.locator('input[type="password"]').wait_for(timeout=120000)

        # 输入密码
        print("输入密码...")
        pwd_input = page.locator('#layers input[type="password"]').first
        pwd_input.wait_for(timeout=15000)
        pwd_input.click()
        page.keyboard.type(password, delay=30)
        page.wait_for_timeout(500)
        page.keyboard.press("Enter")

        # 等待登录完成
        print("等待登录完成...")
        for _ in range(60):
            page.wait_for_timeout(1000)
            cookies = ctx.cookies("https://x.com")
            cookie_map = {c["name"]: c["value"] for c in cookies}
            if cookie_map.get("auth_token") and cookie_map.get("ct0"):
                break
        else:
            # 可能还有额外验证,等用户手动处理
            print("⚠️  未自动完成,请在浏览器中手动完成剩余步骤...")
            for _ in range(120):
                page.wait_for_timeout(1000)
                cookies = ctx.cookies("https://x.com")
                cookie_map = {c["name"]: c["value"] for c in cookies}
                if cookie_map.get("auth_token") and cookie_map.get("ct0"):
                    break
            else:
                print("[错误] 超时。")
                browser.close()
                sys.exit(1)

        auth_token = cookie_map["auth_token"]
        ct0 = cookie_map["ct0"]
        browser.close()

        print(f"[ok] 拿到 cookie: auth_token={auth_token[:8]}... ct0={ct0[:8]}...")
        return {"auth_token": auth_token, "ct0": ct0}


async def update_twscrape_pool(auth_token: str, ct0: str):
    """用新 cookie 更新 twscrape 账号池。"""
    from twscrape import API

    username = os.getenv("X_ACCOUNT_USERNAME", "scraper")
    db_path = ROOT / "data" / "accounts.db"

    api = API(str(db_path))

    try:
        await api.pool.delete_accounts([username])
    except:
        pass

    cookies = f"auth_token={auth_token}; ct0={ct0}"
    await api.pool.add_account(
        username=username,
        password=os.getenv("X_PASSWORD", "-"),
        email=os.getenv("X_EMAIL", f"{username}@example.com"),
        email_password="-",
        cookies=cookies,
    )
    await api.pool.login_all()

    for info in await api.pool.accounts_info():
        print(f"  账号 {info['username']}: active={info['active']} logged_in={info['logged_in']}")


def update_env_file(auth_token: str, ct0: str):
    """更新 .env 文件中的 cookie 值。"""
    env_path = ROOT / ".env"
    content = env_path.read_text()

    import re
    content = re.sub(r'^X_AUTH_TOKEN=.*$', f'X_AUTH_TOKEN={auth_token}', content, flags=re.MULTILINE)
    content = re.sub(r'^X_CT0=.*$', f'X_CT0={ct0}', content, flags=re.MULTILINE)
    env_path.write_text(content)
    print("[ok] .env 已更新")


def main():
    print("=== 自动刷新 X Cookie ===\n")

    # 1. 登录拿 cookie
    cookies = get_cookies_via_playwright()

    # 2. 更新 twscrape 账号池
    print("\n更新 twscrape 账号池...")
    asyncio.run(update_twscrape_pool(cookies["auth_token"], cookies["ct0"]))

    # 3. 更新 .env
    print("\n更新 .env...")
    update_env_file(cookies["auth_token"], cookies["ct0"])

    print("\n=== 完成!可以跑 fetch_all.py 了 ===")


if __name__ == "__main__":
    main()
