# Finnhub Tool Selection Playbook

Use these examples as few-shot guidance for the LLM.

## Valuation Metrics

User: `苹果公司现在的 PE 是多少？`

Call:

```powershell
python skills\api-skills\finnhub-skill\scripts\fundamentals.py metrics --symbol AAPL --question "苹果公司现在的 PE 是多少？"
```

Why: PE is a valuation metric from `/stock/metric`, not a quote.

## Current Quote

User: `Tesla current price?`

Call:

```powershell
python skills\api-skills\finnhub-skill\scripts\stock_market.py quote --symbol TSLA --question "Tesla current price?"
```

## Company News

User: `总结一下英伟达最近的消息面`

Call:

```powershell
python skills\api-skills\finnhub-skill\scripts\news.py company-news --symbol NVDA --lookback-days 14 --limit 10 --question "总结一下英伟达最近的消息面"
```

## Broad Market News

User: `今天美股市场有什么重要新闻？`

Call:

```powershell
python skills\api-skills\finnhub-skill\scripts\news.py market-news --category general --limit 10 --question "今天美股市场有什么重要新闻？"
```

Why: There is no single company symbol, so do not invent one.

## Technical Indicator

User: `特斯拉 RSI 现在怎么样？`

Call:

```powershell
python skills\api-skills\finnhub-skill\scripts\technical.py indicator --symbol TSLA --indicator rsi --lookback-days 30 --question "特斯拉 RSI 现在怎么样？"
```

## Analyst View

User: `微软的分析师目标价是多少？`

Call:

```powershell
python skills\api-skills\finnhub-skill\scripts\analyst.py price-target --symbol MSFT --question "微软的分析师目标价是多少？"
```

## Ambiguous Symbol

User: `苹果的 ticker 是什么？`

Call:

```powershell
python skills\api-skills\finnhub-skill\scripts\symbols.py search --query "Apple" --question "苹果的 ticker 是什么？"
```

Then select `AAPL` only if the returned description and exchange match Apple Inc.

## Chinese A-Share Filing Question

User: `宁德时代 2026 一季度 营业收入 净利润`

Do not use this Finnhub skill. Route to Milvus filings because the expected
evidence is a Chinese filing table with page/chunk provenance.
