# StockRadar

美股基本面投资"信息雷达"。自动抓取 Twitter KOL 推文,LLM 提取股票观点,S&P 500 实时市场图。

## 功能

- **推文抓取**:定时从 Twitter 拉取 KOL 推文(twscrape + cron)
- **LLM 观点分析**:批量识别推文中的股票 + 提取看多/看空/中性观点(DeepSeek V4 Pro)
- **两层数据**:推文级观点(`stock_opinion`) + KOL×股票 聚合总结(`kol_stock_view`,30 天滑动窗口)
- **Web 界面**:
  - 推文流:按时间浏览,支持 KOL 过滤和关键词搜索
  - 大V视角:选一个 KOL → 看他关注哪些票、每个票的观点卡片
  - 股票视角:选一个 ticker → 看哪些大V在喊、共识/分歧、观点时间线
  - 市场地图:S&P 500 气泡图(D3.js 力模拟,实时 WebSocket 30s 刷新)

## 快速开始

```bash
# 环境
python3.13 -m venv .venv
.venv/bin/pip install twscrape python-dotenv fastapi uvicorn jinja2 httpx pandas lxml yfinance

# 配置
cp .env.example .env  # 填入 X cookie + LLM API key + Alpaca key

# 添加 KOL
.venv/bin/python scripts/manage_kol.py add aleabitoreddit --category "半导体/AI"
.venv/bin/python scripts/manage_kol.py add hanking66 --category "存储/宏观"

# 抓取推文
.venv/bin/python scripts/fetch_all.py

# LLM 分析观点
.venv/bin/python scripts/analyze_tweets.py

# 启动网页
.venv/bin/uvicorn stockradar.web.app:app --port 8002
```

## 目录结构

```
stockradar/
  stockradar/         # 源码包
    db.py             # SQLite 数据模型(kol/tweet/stock_opinion/kol_stock_view)
    scraper.py        # twscrape 抓取逻辑
    tickers.py        # $TICKER 正则提取
    analyzer.py       # LLM 批量分析(从 prompts/ 读 prompt)
    web/
      app.py          # FastAPI 路由
      market.py       # S&P 500 气泡图后端(Alpaca API + WebSocket)
      templates/      # Jinja2 模板
  scripts/            # CLI 脚本(fetch_all / analyze_tweets / manage_kol)
  prompts/            # LLM prompt 模板(可独立编辑,不动代码)
  data/               # SQLite 库 + sp500.json(gitignore)
  docs/               # 需求文档与设计
```

## 定时任务

```bash
# 每小时第 7 分钟自动抓取
7 * * * * cd ~/money/stockradar && .venv/bin/python scripts/fetch_all.py >> logs/fetch.log 2>&1
```

## 配置项(.env)

| 变量 | 说明 |
|---|---|
| X_ACCOUNT_USERNAME | X 抓取小号 handle |
| X_AUTH_TOKEN | X cookie auth_token |
| X_CT0 | X cookie ct0 |
| LLM_BASE_URL | LLM API 地址(StepFun proxy) |
| LLM_API_KEY | LLM API key |
| LLM_MODEL | 模型名(默认 deepseek-v4-pro) |
| ALPACA_KEY | Alpaca API Key(市场地图用) |
| ALPACA_SECRET | Alpaca API Secret |
