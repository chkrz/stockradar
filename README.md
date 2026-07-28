# StockRadar

美股基本面投资"信息雷达"。Twitter KOL 推文抓取 + LLM 观点分析 + 市场地图。

## 目录结构

```
stockradar/
├── src/              # 核心库(不直接执行,被 import)
│   ├── db.py         # SQLite 数据模型(8张表)
│   ├── scraper.py    # twscrape 抓取逻辑
│   ├── analyzer.py   # LLM 批量分析(读 prompts/)
│   ├── tickers.py    # $TICKER 正则提取
│   └── web/          # FastAPI Web 服务
│       ├── app.py    # 主路由 + Basic Auth
│       ├── market.py # S&P 500 API(读 DB)
│       └── market_cn.py  # 沪深300 API(读 DB)
├── cron/             # 定时任务(cron 自动跑,无人值守)
│   ├── fetch_tweets.py   # 拉 KOL 推文入库
│   ├── fetch_market.py   # 拉市场快照(美股/A股)入库
│   └── analyze.py        # LLM 分析未处理推文
├── tools/            # 手动工具(人触发)
│   ├── manage_kol.py     # KOL 增删查
│   └── refresh_cookie.py # 刷新 X cookie(浏览器弹窗)
├── prompts/          # LLM prompt 模板(改 prompt 不动代码)
├── docs/             # 需求文档
├── data/             # SQLite + JSON(gitignore)
└── logs/             # 运行日志(gitignore)
```

## 快速开始

```bash
# 环境
python3.13 -m venv .venv
.venv/bin/pip install twscrape python-dotenv fastapi uvicorn jinja2 httpx pandas lxml yfinance akshare playwright
.venv/bin/playwright install chromium

# 配置
cp .env.example .env   # 填写 X 账号 + LLM key

# 初始化 KOL
.venv/bin/python tools/manage_kol.py add aleabitoreddit --category "半导体/AI"
.venv/bin/python tools/manage_kol.py add hanking66 --category "存储/宏观"

# 首次拉取
.venv/bin/python cron/fetch_tweets.py --limit 200
.venv/bin/python cron/fetch_market.py
.venv/bin/python cron/analyze.py

# 启动 Web
.venv/bin/uvicorn src.web.app:app --port 8002
```

## Pipeline 全览

### 数据流

```
                    ┌──────────────┐
  Twitter ────────→ │ tweet 表      │ ──→ LLM 分析 ──→ stock_opinion 表
  (cron/fetch_tweets)│              │      (cron/analyze)  kol_stock_view 表
                    └──────────────┘
                                                    ↓
  Alpaca (美股) ──→ snapshot_us 表 ───────────────→ Web 前端(只读 DB)
  (cron/fetch_market)                               ↑
  AkShare (A股) ──→ snapshot_cn 表 ───────────────→ │
                                                    │
                    stock_us / stock_cn 表 ─────────→│
```

### 定时任务(cron)

| 脚本 | 频率 | 作用 |
|---|---|---|
| `cron/fetch_tweets.py` | 每小时 | 拉 KOL 推文,增量入库 |
| `cron/analyze.py` | 每小时(跟在 fetch 后) | LLM 分析未处理推文,更新观点 |
| `cron/fetch_market.py` | 交易时段每分钟(可选) | 拉市场快照写入 DB |

当前 crontab:
```
7 * * * * cd ~/money/stockradar && .venv/bin/python cron/fetch_tweets.py >> logs/fetch.log 2>&1 && .venv/bin/python cron/analyze.py >> logs/analyze.log 2>&1
```

### Web 服务

启动: `.venv/bin/uvicorn src.web.app:app --port 8002`

| 路径 | 说明 | 数据来源 |
|---|---|---|
| `/` | 推文流(按时间/KOL/关键词筛选) | tweet 表 |
| `/kol/<handle>` | 大V视角(该 KOL 关注的所有股票观点) | kol_stock_view 表 |
| `/stocks` | 股票列表(按热度排序,显示共识) | kol_stock_view 表 |
| `/stock/<ticker>` | 股票视角(哪些大V在喊+时间线) | stock_opinion 表 |
| `/market` | S&P 500 气泡图 | snapshot_us 表 |
| `/market/cn` | 沪深300 气泡图 | snapshot_cn 表 |
| `/api/market/snapshot` | 美股 JSON API | snapshot_us 表 |
| `/api/market/cn/snapshot` | A股 JSON API | snapshot_cn 表 |

前端每 30 秒轮询 API 刷新气泡图。所有页面需要密码(Basic Auth, 密码在 .env `AUTH_PASSWORD`)。

### 故障恢复 / 补数据

| 问题 | 原因 | 恢复方式 |
|---|---|---|
| 推文停止更新 | X cookie 过期 | `tools/refresh_cookie.py`(弹浏览器登录拿新 cookie) |
| 推文有遗漏 | cookie 失效期间漏拉 | `cron/fetch_tweets.py --limit 200`(重拉,自动去重) |
| LLM 分析未执行 | API 额度用完(402) | 续费后重跑 `cron/analyze.py` |
| 市场数据为空 | 未运行 fetch_market | `cron/fetch_market.py`(首次自动初始化股票表) |
| 气泡图没有市值大小 | stock_cn/stock_us 市值为0 | 重新用 MCP/yfinance 更新市值到 stock 表 |

### 数据库表(8张)

| 表 | 用途 |
|---|---|
| `kol` | KOL 名单(handle, 昵称, 分类, 抓取游标) |
| `tweet` | 推文原文(490+ 条) |
| `stock_opinion` | 推文级观点(tweet × ticker, LLM 生成) |
| `kol_stock_view` | 聚合观点(KOL × ticker, 30天窗口) |
| `stock_us` | 美股主表(S&P 500, 含市值) |
| `stock_cn` | A股主表(沪深300, 含市值) |
| `snapshot_us` | 美股价格快照 |
| `snapshot_cn` | A股价格快照 |
| `mention` | (废弃,被 stock_opinion 替代) |

## 配置项(.env)

| 变量 | 说明 | 必填 |
|---|---|---|
| X_ACCOUNT_USERNAME | X 登录用户名 | ✓ |
| X_PASSWORD | X 登录密码 | ✓ |
| X_AUTH_TOKEN | X cookie(自动更新) | 初始 |
| X_CT0 | X cookie(自动更新) | 初始 |
| LLM_BASE_URL | LLM API 地址 | ✓ |
| LLM_API_KEY | LLM API key | ✓ |
| LLM_MODEL | 模型名(默认 deepseek-v4-pro) | |
| AUTH_PASSWORD | Web 访问密码 | ✓ |

## 部署

本地服务 + Cloudflare Tunnel 暴露公网:
```bash
# 启动服务
.venv/bin/uvicorn src.web.app:app --port 8002 &

# 启动隧道(需 VPN 能访问外网)
cloudflared tunnel --url http://localhost:8002 --protocol http2
```
