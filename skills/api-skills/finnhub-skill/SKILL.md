---
name: finnhub-skill
description: >
  Let a finance agent decide and execute Finnhub API scripts for US/global market
  data. Use when the user asks for quotes, PE/PB/EPS/market-cap metrics, company
  profile, peers, news, sentiment, analyst recommendations, target price,
  earnings, dividends, technical indicators, or symbol lookup. This skill is an
  LLM-facing tool manual plus executable scripts. Do NOT use it for A-share PDF
  table extraction, Milvus filing retrieval, internal knowledge-base retrieval,
  or final answer generation.
allowed-tools: Read, Bash(python:*)
---

# Finnhub Skill

## What This Skill Is

This skill gives the runtime LLM a Finnhub API capability. The LLM should read this
manual, choose the most appropriate script and operation, execute it, then pass the
normalized evidence JSON to the evidence ledger.

This skill is **not** a pure rule filter. Rules may exist as compatibility fallback,
but the intended path is:

```text
user question + query analyzer output
  -> LLM reads this skill
  -> LLM selects a script family and operation
  -> script calls Finnhub API
  -> script returns normalized evidence JSON
  -> evidence ledger
  -> answer contract
```

## First Decision

Use Finnhub when the needed evidence is live or vendor API market data:

- Quote/current price, recent price movement, candle history.
- Valuation and market metrics: PE, PB, PS, EPS, market cap, 52-week high/low.
- Company profile, exchange, industry, peers.
- Company news, market news, and news sentiment.
- Analyst recommendation, target price, upgrade/downgrade.
- Earnings history/calendar and dividend history.
- Technical indicators such as RSI, MACD, SMA, EMA.
- Symbol lookup when the entity is not resolved.

Do not use Finnhub when the needed evidence is:

- Chinese filing PDF chunks or page-level financial-statement tables: use Milvus filings.
- Stable finance theory, methodology, or definitions: use knowledge-base skill.
- Broad web articles not covered by Finnhub: use web/news skill.
- A final investment recommendation without evidence and assumptions.

## Script Catalog

Always prefer the narrowest script. If unsure, run `<script> help` first.

```powershell
python skills\api-skills\finnhub-skill\scripts\symbols.py help
python skills\api-skills\finnhub-skill\scripts\stock_market.py help
python skills\api-skills\finnhub-skill\scripts\fundamentals.py help
python skills\api-skills\finnhub-skill\scripts\news.py help
python skills\api-skills\finnhub-skill\scripts\analyst.py help
python skills\api-skills\finnhub-skill\scripts\technical.py help
```

If the runtime architecture wants a strict "LLM selects, executor runs" boundary,
the LLM should output a JSON object that matches `assets/finnhub-tool-call.schema.json`
and pass it to:

```powershell
python skills\api-skills\finnhub-skill\scripts\skill_executor.py --tool-call-json "{\"script\":\"fundamentals.py\",\"operation\":\"metrics\",\"args\":{\"symbol\":\"AAPL\",\"question\":\"苹果公司现在PE是多少\"},\"reason\":\"PE is a valuation metric from /stock/metric\"}"
```

On PowerShell, prefer stdin or a JSON file to avoid quote escaping:

```powershell
'{"script":"fundamentals.py","operation":"metrics","args":{"symbol":"AAPL","question":"苹果公司现在PE是多少"},"reason":"PE is a valuation metric"}' |
  python skills\api-skills\finnhub-skill\scripts\skill_executor.py
```

The executor only validates and runs allowed local scripts; it does not decide the
best endpoint. The LLM is responsible for that decision.

### symbols.py

Use for entity resolution and ticker lookup.

```powershell
python skills\api-skills\finnhub-skill\scripts\symbols.py search --query "Apple" --question "苹果公司的ticker是什么"
python skills\api-skills\finnhub-skill\scripts\symbols.py stock-symbols --market US --limit 10
```

### stock_market.py

Use for quote, price trend, company profile, and peers.

```powershell
python skills\api-skills\finnhub-skill\scripts\stock_market.py quote --symbol AAPL --question "苹果现在股价是多少"
python skills\api-skills\finnhub-skill\scripts\stock_market.py candles --symbol AAPL --lookback-days 30 --resolution D --question "苹果最近走势"
python skills\api-skills\finnhub-skill\scripts\stock_market.py profile --symbol AAPL --question "苹果是哪家交易所上市"
python skills\api-skills\finnhub-skill\scripts\stock_market.py peers --symbol AAPL --question "苹果的可比公司有哪些"
```

### fundamentals.py

Use for PE/PB/EPS/market cap, reported financials, earnings, dividends, and earnings calendar.

```powershell
python skills\api-skills\finnhub-skill\scripts\fundamentals.py metrics --symbol AAPL --question "苹果公司现在PE是多少"
python skills\api-skills\finnhub-skill\scripts\fundamentals.py earnings --symbol AAPL --limit 8 --question "苹果最近几个季度EPS"
python skills\api-skills\finnhub-skill\scripts\fundamentals.py dividends --symbol AAPL --lookback-days 365 --question "苹果最近分红"
python skills\api-skills\finnhub-skill\scripts\fundamentals.py earnings-calendar --symbol AAPL --lookback-days 30 --question "苹果近期财报日"
```

### news.py

Use for company news, broad market news, and sentiment.

```powershell
python skills\api-skills\finnhub-skill\scripts\news.py company-news --symbol NVDA --lookback-days 14 --limit 10 --question "英伟达最近消息面"
python skills\api-skills\finnhub-skill\scripts\news.py market-news --category general --limit 10 --question "今天美股市场新闻"
python skills\api-skills\finnhub-skill\scripts\news.py sentiment --symbol TSLA --question "特斯拉新闻情绪"
```

### analyst.py

Use for analyst recommendations, target price, and rating changes.

```powershell
python skills\api-skills\finnhub-skill\scripts\analyst.py recommendations --symbol MSFT --question "微软分析师评级"
python skills\api-skills\finnhub-skill\scripts\analyst.py price-target --symbol MSFT --question "微软目标价"
python skills\api-skills\finnhub-skill\scripts\analyst.py upgrades --symbol MSFT --lookback-days 90 --question "微软最近评级变化"
```

### technical.py

Use for indicators. Choose the exact indicator from the question when possible.

```powershell
python skills\api-skills\finnhub-skill\scripts\technical.py indicator --symbol TSLA --indicator rsi --lookback-days 30 --question "特斯拉RSI"
python skills\api-skills\finnhub-skill\scripts\technical.py indicator --symbol TSLA --indicator macd --lookback-days 60 --question "特斯拉MACD"
```

## Selection Playbook

- "苹果 PE/市盈率/估值/市值/EPS" -> `fundamentals.py metrics --symbol AAPL`
- "苹果现在股价/current price/quote" -> `stock_market.py quote --symbol AAPL`
- "苹果最近走势/K线/过去30天" -> `stock_market.py candles --symbol AAPL`
- "苹果最近新闻/消息面/catalyst" -> `news.py company-news --symbol AAPL`
- "纳斯达克市场新闻/美股市场消息" -> `news.py market-news`
- "苹果目标价/分析师怎么看" -> `analyst.py price-target` or `analyst.py recommendations`
- "RSI/MACD/SMA/技术指标" -> `technical.py indicator`
- "不知道 ticker / 中文公司名 / 模糊公司" -> `symbols.py search`

## Entity Handling

Prefer explicit identifiers from query analyzer:

```json
{
  "entity": {
    "company": "Apple",
    "display_name": "苹果公司",
    "identifiers": {
      "symbol": "AAPL",
      "exchange": "NASDAQ",
      "market": "US"
    }
  }
}
```

If the symbol is missing or uncertain, call `symbols.py search` first and use the
best result only if the company, exchange, and market match the question. If still
ambiguous, return a clarification need instead of guessing.

## Output Contract

Every script returns JSON:

```json
{
  "ok": true,
  "route": {
    "tool_name": "basic_financials",
    "endpoint": "/stock/metric",
    "symbol": "AAPL"
  },
  "evidence": {
    "content": "Finnhub API tool=basic_financials ...",
    "metadata": {
      "source_type": "finnhub",
      "source_name": "Finnhub API",
      "endpoint": "/stock/metric",
      "symbol": "AAPL",
      "timestamp": "..."
    }
  }
}
```

Pass `evidence.content` and `evidence.metadata` into the evidence ledger. Do not let
the answer generator cite Finnhub unless the evidence metadata is present.

## References

- `references/finnhub-api-catalog.md`: endpoint and script map.
- `references/tool-selection-playbook.md`: more examples for LLM selection.
- `references/evidence-policy.md`: citation and failure handling.

## Gotchas

- Do not route a Milvus filing question to Finnhub just because the company has a ticker.
- Do not answer "latest" from stale cached content; scripts call the live API.
- Do not invent symbols. Use `symbols.py search` or ask for clarification.
- PE/PB/EPS questions must use `fundamentals.py metrics`, not `stock_market.py quote`.
- Broad market questions without a symbol should use `news.py market-news` or another source skill, not a fake ticker.
- If a script returns `ok=false`, preserve its structured error for the planner.
