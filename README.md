# StockRadar

美股基本面投资"信息雷达"。自动抓取 Twitter KOL 推文,LLM 提取股票观点,网页浏览。

## 功能

- **推文抓取**:定时从 Twitter 拉取 KOL 推文(twscrape + cron)
- **LLM 观点分析**:批量识别推文中的股票 + 提取看多/看空/中性观点(DeepSeek V4 Pro)
- **两层数据**:推文级观点(`stock_opinion`) + KOL×股票 聚合总结(`kol_stock_view`)
- **Web 界面**:推文流 / 大V视角 / 股票视角,三个维度浏览

## 快速开始

```bash
# 环境
python3.13 -m venv .venv
.venv/bin/pip install twscrape python-dotenv fastapi uvicorn jinja2 httpx

# 配置
cp .env.example .env  # 填入 X cookie + LLM API key

# 添加 KOL
.venv/bin/python scripts/manage_kol.py add aleabitoreddit --category "半导体/AI"
.venv/bin/python scripts/manage_kol.py add hanking66 --category "存储/宏观"

# 抓取
.venv/bin/python scripts/fetch_all.py

# LLM 分析
.venv/bin/python scripts/analyze_tweets.py

# 启动网页
.venv/bin/uvicorn stockradar.web.app:app --port 8002
```

## 目录结构

```
stockradar/
  stockradar/         # 源码包
    db.py             # SQLite 数据模型与 CRUD
    scraper.py        # twscrape 抓取逻辑
    tickers.py        # $TICKER 正则提取
    analyzer.py       # LLM 批量分析
    web/              # FastAPI + Jinja2 网页
  scripts/            # CLI 脚本
  prompts/            # LLM prompt 模板(可独立编辑)
  docs/               # 需求文档与设计
  data/               # SQLite 库(gitignore)
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
| LLM_BASE_URL | LLM API 地址 |
| LLM_API_KEY | LLM API key |
| LLM_MODEL | 模型名(默认 deepseek-v4-pro) |
