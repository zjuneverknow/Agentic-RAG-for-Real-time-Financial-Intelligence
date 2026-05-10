# Finnhub API Catalog For LLM Tool Selection

This catalog is adapted for the finance agent skill layer. It maps user intent to
script operations, not to hidden routing rules.

## Authentication

All scripts read `FINNHUB_API_KEY` from `.env` or the process environment. The
Finnhub REST shape is:

```text
GET https://finnhub.io/api/v1/{endpoint}?token=FINNHUB_API_KEY
```

## Implemented Script Families

| Script | Operation | Finnhub endpoint | Use when |
| --- | --- | --- | --- |
| `symbols.py` | `search` | `/search` | Resolve company name, ticker, Chinese alias, or ambiguous entity. |
| `symbols.py` | `stock-symbols` | `/stock/symbol` | List symbols for a market such as US. |
| `stock_market.py` | `quote` | `/quote` | Current price, open/high/low/previous close. |
| `stock_market.py` | `candles` | `/stock/candle` | Historical price, trend, K-line/candles. |
| `stock_market.py` | `profile` | `/stock/profile2` | Company profile, exchange, industry, IPO date. |
| `stock_market.py` | `peers` | `/stock/peers` | Competitors and comparable companies. |
| `fundamentals.py` | `metrics` | `/stock/metric` | PE/PB/PS/EPS, market cap, 52-week high/low. |
| `fundamentals.py` | `financials` | `/stock/financials-reported` | Finnhub reported financial statements. |
| `fundamentals.py` | `earnings` | `/stock/earnings` | Earnings history, EPS actual/estimate. |
| `fundamentals.py` | `dividends` | `/stock/dividend` | Dividend history. |
| `fundamentals.py` | `earnings-calendar` | `/calendar/earnings` | Earnings event calendar. |
| `news.py` | `company-news` | `/company-news` | Company-specific news and catalysts. |
| `news.py` | `market-news` | `/news` | Broad market news without one symbol. |
| `news.py` | `sentiment` | `/news-sentiment` | Company news sentiment. |
| `analyst.py` | `recommendations` | `/stock/recommendation` | Analyst buy/hold/sell trends. |
| `analyst.py` | `price-target` | `/stock/price-target` | Consensus/high/low target price. |
| `analyst.py` | `upgrades` | `/stock/upgrade-downgrade` | Rating changes. |
| `technical.py` | `indicator` | `/indicator` | RSI, MACD, SMA, EMA and other technical indicators. |

## Finnhub Areas Not Yet Exposed As Scripts

The source document also mentions crypto, forex, ETF/fund, bond, economic data,
calendar, WebSocket, sector metrics, patterns, support/resistance, and other
alternative data. Do not pretend these are implemented. Add a new script family
before using them in the agent pipeline.

Recommended future script families:

- `crypto.py`: `/crypto/symbol`, `/crypto/candle`, `/crypto/profile`
- `forex.py`: `/forex/symbol`, `/forex/candle`, `/forex/exchange`
- `funds.py`: `/etf/profile`, `/etf/holdings`, `/mutual-fund/profile`
- `macro.py`: `/economic-data`, `/economic-calendar`
- `events.py`: `/calendar/ipo`, `/calendar/economic`

## Design Inspiration

The external mcp-finnhub project groups Finnhub into AI-facing tool families:
market data, technical analysis, news/sentiment, fundamentals, estimates,
ownership, multi-asset data, calendars, and project/job management. This skill
uses the same principle but exposes local scripts instead of an MCP server.
