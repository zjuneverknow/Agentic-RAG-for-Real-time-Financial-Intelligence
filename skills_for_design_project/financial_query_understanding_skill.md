# Financial Query Understanding Skill

Status: active prompt reference for local semantic query analyzer.
Purpose: help Qwen2.5-7B-Instruct parse financial questions into strict JSON for routing, entity resolution, and source planning.

## Task

Given a user question and lexical hints, return strict JSON only. Do not answer the financial question.

The model handles semantic understanding. The resolver confirms final security identifiers. Do not invent ticker, exchange, CIK, ISIN, or A-share code.

## Output JSON Schema

```json
{
  "intent": "fact | summary | compare | reasoning | chat | trend_analysis | valuation_analysis | risk_analysis | news_monitoring",
  "entity_mentions": [
    {
      "text": "original mention",
      "type": "company | market_index | etf | sector | macro_indicator | commodity | currency | crypto | financial_metric | document_type | event",
      "normalized_name_candidate": "semantic name only, not authoritative ticker",
      "ambiguity_candidates": ["candidate 1", "candidate 2"],
      "confidence": 0.0
    }
  ],
  "metrics": ["营业收入 | 净利润 | 归母净利润 | cash flow metric names"],
  "market_metrics": ["pe | pb | ps | eps | price | market_cap | valuation | trend | technical_indicator | volume"],
  "sub_questions": [
    {"question": "sub question", "focus": "main focus", "type": "single | metric_lookup | news_summary | trend_analysis | comparison | reasoning"}
  ],
  "source_requirements": {
    "needs_document_evidence": false,
    "needs_filing_evidence": false,
    "needs_fresh_market_data": false,
    "needs_structured_metrics": false,
    "needs_news": false,
    "needs_policy_context": false,
    "needs_macro_context": false,
    "needs_internal_docs": false,
    "needs_market_index_data": false,
    "needs_price_trend": false,
    "needs_technical_indicator": false
  },
  "confidence": 0.0,
  "ambiguities": []
}
```

## Entity Types

- company: listed company, issuer, or operating company.
- market_index: Nasdaq Composite, Nasdaq 100, S&P 500, Dow Jones, Hang Seng Index, ChiNext Index.
- etf: ETF or fund, such as QQQ, SPY, 2800.HK, 510300.
- sector: industry/theme, such as AI, semiconductor, new energy.
- macro_indicator: CPI, GDP, interest rate, nonfarm payrolls, PMI.
- commodity: gold, crude oil, copper.
- currency: USD/CNY, EUR/USD.
- crypto: BTC, ETH.
- financial_metric: PE, PB, revenue, net profit, EPS.
- document_type: annual report, quarterly report, 10-K, 10-Q, filing, announcement.
- event: earnings call, rate decision, product launch, policy announcement.

## Intent Rules

- fact: asks for one factual value or a small set of factual values.
- summary: asks to summarize, recap, organize, or synthesize.
- compare: compares entities, periods, industries, or instruments.
- reasoning: asks why, impact, risks, whether expensive/cheap, future implications.
- trend_analysis: asks about price/index trend, chart, K-line, technical direction.
- valuation_analysis: asks whether valuation is expensive/cheap, PE/PB/PS/EPS context, peer comparison.
- risk_analysis: asks risks, downside, uncertainty.
- news_monitoring: asks latest news, sentiment, market narrative.
- chat: non-financial conversation.

If the downstream system supports only fact/summary/compare/reasoning/chat, choose the closest base intent and keep richer detail in sub_questions and source_requirements.

## Source Requirement Rules

- Revenue, net profit, attributable net profit, balance sheet, cash flow: document + filing evidence.
- PE, PB, PS, EPS, market cap, price: structured metrics + fresh market data.
- Trend, chart, K-line, technical indicators, support/resistance: price trend + technical indicator.
- News, headlines, sentiment, market narrative, policy, recent changes: news.
- Macro topics: macro context.
- Internal research, memo, notes: internal docs.
- Market indices: market index data. If trend is requested, also price trend.
- Valuation reasoning: structured metrics + fresh market data + usually news.

## Disambiguation Rules

Nasdaq:
- "纳斯达克", "纳指", "Nasdaq" without company context usually means a market index.
- "纳斯达克100", "Nasdaq 100", "NDX", "QQQ", or large-cap tech context means Nasdaq 100.
- "纳斯达克综合指数", "Nasdaq Composite", broad Nasdaq market context means Nasdaq Composite.
- "Nasdaq Inc.", "NDAQ", company, revenue, earnings, filings means Nasdaq Inc. company.
- "Nasdaq exchange", listing rules, delisting rules means exchange/policy context.
- If unclear, expose candidates instead of pretending certainty.

Apple:
- In financial context, "苹果" or "Apple" usually means Apple Inc.
- Do not treat it as fruit unless non-financial context is explicit.

Hong Kong:
- "腾讯" means Tencent Holdings semantic candidate.
- "阿里巴巴港股" means Alibaba HK share semantic candidate.
- "恒生指数" means Hang Seng Index market_index.
- "盈富基金" or "2800.HK" means Tracker Fund ETF.

A-share:
- "宁德时代" means CATL / 300750 candidate.
- "比亚迪" means BYD / 002594 candidate.
- "贵州茅台" or "茅台" means Kweichow Moutai / 600519 candidate.

Forbidden behavior:
- Do not invent authoritative ticker, CIK, ISIN, or exchange.
- Do not classify PE/PB/PS/EPS/ROE/ROA/Q1/Q2/Q3/Q4 as ticker symbols.
- Do not use web search as the only source when structured market data is required.
- Do not classify "summary/summarize/总结/归纳/梳理/概括" as fact.
- If ambiguous, return ambiguity_candidates.

## Few-shot Examples

### 1. A-share filing fact
Question: 宁德时代 2026 一季度 营业收入 净利润
JSON:
```json
{
  "intent": "fact",
  "entity_mentions": [{"text": "宁德时代", "type": "company", "normalized_name_candidate": "CATL", "ambiguity_candidates": [], "confidence": 0.95}],
  "metrics": ["营业收入", "净利润"],
  "market_metrics": [],
  "sub_questions": [
    {"question": "宁德时代 2026 一季度营业收入是多少？", "focus": "营业收入", "type": "metric_lookup"},
    {"question": "宁德时代 2026 一季度净利润是多少？", "focus": "净利润", "type": "metric_lookup"}
  ],
  "source_requirements": {"needs_document_evidence": true, "needs_filing_evidence": true},
  "confidence": 0.95,
  "ambiguities": []
}
```

### 2. US stock valuation summary
Question: 用中文总结一下苹果最近的估值和消息面
JSON:
```json
{
  "intent": "summary",
  "entity_mentions": [{"text": "苹果", "type": "company", "normalized_name_candidate": "Apple Inc.", "ambiguity_candidates": [], "confidence": 0.9}],
  "metrics": [],
  "market_metrics": ["valuation"],
  "sub_questions": [
    {"question": "苹果当前估值指标如何？", "focus": "valuation", "type": "metric_lookup"},
    {"question": "苹果最近消息面有哪些重要变化？", "focus": "news", "type": "news_summary"}
  ],
  "source_requirements": {"needs_fresh_market_data": true, "needs_structured_metrics": true, "needs_news": true},
  "confidence": 0.9,
  "ambiguities": []
}
```

### 3. Market index ambiguity
Question: 纳斯达克股价走势怎么样？
JSON:
```json
{
  "intent": "trend_analysis",
  "entity_mentions": [{"text": "纳斯达克", "type": "market_index", "normalized_name_candidate": "Nasdaq Composite", "ambiguity_candidates": ["Nasdaq Composite", "Nasdaq 100", "Nasdaq Inc."], "confidence": 0.78}],
  "metrics": [],
  "market_metrics": ["trend", "price", "technical_indicator"],
  "sub_questions": [
    {"question": "纳斯达克指数近期价格走势如何？", "focus": "price_trend", "type": "trend_analysis"},
    {"question": "纳斯达克指数近期消息面有哪些影响？", "focus": "news", "type": "news_summary"}
  ],
  "source_requirements": {"needs_market_index_data": true, "needs_price_trend": true, "needs_technical_indicator": true, "needs_news": true},
  "confidence": 0.78,
  "ambiguities": ["纳斯达克 could mean Nasdaq Composite, Nasdaq 100, or Nasdaq Inc."]
}
```

### 4. Nasdaq 100 explicit
Question: 纳斯达克100走势怎么样？
JSON:
```json
{
  "intent": "trend_analysis",
  "entity_mentions": [{"text": "纳斯达克100", "type": "market_index", "normalized_name_candidate": "Nasdaq 100", "ambiguity_candidates": [], "confidence": 0.93}],
  "metrics": [],
  "market_metrics": ["trend", "price", "technical_indicator"],
  "sub_questions": [{"question": "纳斯达克100近期价格走势如何？", "focus": "price_trend", "type": "trend_analysis"}],
  "source_requirements": {"needs_market_index_data": true, "needs_price_trend": true, "needs_technical_indicator": true},
  "confidence": 0.93,
  "ambiguities": []
}
```

### 5. Hong Kong stock
Question: 腾讯控股最近业绩和股价表现怎么样？
JSON:
```json
{
  "intent": "summary",
  "entity_mentions": [{"text": "腾讯控股", "type": "company", "normalized_name_candidate": "Tencent Holdings", "ambiguity_candidates": [], "confidence": 0.9}],
  "metrics": ["revenue", "net profit"],
  "market_metrics": ["price", "trend"],
  "sub_questions": [
    {"question": "腾讯控股最近业绩表现如何？", "focus": "filing_or_earnings", "type": "metric_lookup"},
    {"question": "腾讯控股近期股价走势如何？", "focus": "price_trend", "type": "trend_analysis"}
  ],
  "source_requirements": {"needs_document_evidence": true, "needs_fresh_market_data": true, "needs_price_trend": true},
  "confidence": 0.9,
  "ambiguities": []
}
```

### 6. ETF
Question: QQQ 和 SPY 最近表现对比一下
JSON:
```json
{
  "intent": "compare",
  "entity_mentions": [
    {"text": "QQQ", "type": "etf", "normalized_name_candidate": "Invesco QQQ Trust", "ambiguity_candidates": [], "confidence": 0.95},
    {"text": "SPY", "type": "etf", "normalized_name_candidate": "SPDR S&P 500 ETF Trust", "ambiguity_candidates": [], "confidence": 0.95}
  ],
  "metrics": [],
  "market_metrics": ["price", "trend", "volume"],
  "sub_questions": [{"question": "QQQ 和 SPY 近期价格、涨跌幅和成交量表现如何？", "focus": "comparison", "type": "comparison"}],
  "source_requirements": {"needs_fresh_market_data": true, "needs_price_trend": true, "needs_structured_metrics": true},
  "confidence": 0.95,
  "ambiguities": []
}
```

### 7. Crypto
Question: BTC 这两天为什么跌？
JSON:
```json
{
  "intent": "reasoning",
  "entity_mentions": [{"text": "BTC", "type": "crypto", "normalized_name_candidate": "Bitcoin", "ambiguity_candidates": [], "confidence": 0.95}],
  "metrics": [],
  "market_metrics": ["price", "trend", "volume"],
  "sub_questions": [
    {"question": "BTC 近期价格走势如何？", "focus": "price_trend", "type": "trend_analysis"},
    {"question": "BTC 近期消息面或宏观因素有哪些影响？", "focus": "news_macro", "type": "reasoning"}
  ],
  "source_requirements": {"needs_fresh_market_data": true, "needs_price_trend": true, "needs_news": true, "needs_macro_context": true},
  "confidence": 0.9,
  "ambiguities": []
}
```

### 8. Macro
Question: 美联储降息预期对纳指有什么影响？
JSON:
```json
{
  "intent": "reasoning",
  "entity_mentions": [
    {"text": "美联储降息预期", "type": "macro_indicator", "normalized_name_candidate": "Fed rate cut expectations", "ambiguity_candidates": [], "confidence": 0.9},
    {"text": "纳指", "type": "market_index", "normalized_name_candidate": "Nasdaq Composite", "ambiguity_candidates": ["Nasdaq Composite", "Nasdaq 100"], "confidence": 0.78}
  ],
  "metrics": [],
  "market_metrics": ["trend", "valuation"],
  "sub_questions": [
    {"question": "美联储降息预期最近如何变化？", "focus": "macro", "type": "news_summary"},
    {"question": "降息预期对纳指估值和走势的影响是什么？", "focus": "reasoning", "type": "reasoning"}
  ],
  "source_requirements": {"needs_macro_context": true, "needs_market_index_data": true, "needs_price_trend": true, "needs_news": true},
  "confidence": 0.86,
  "ambiguities": ["纳指 may refer to Nasdaq Composite or Nasdaq 100"]
}
```

### 9. Ambiguous company vs exchange
Question: Nasdaq 公司近三年营收怎么样？
JSON:
```json
{
  "intent": "fact",
  "entity_mentions": [{"text": "Nasdaq 公司", "type": "company", "normalized_name_candidate": "Nasdaq Inc.", "ambiguity_candidates": ["Nasdaq Inc.", "Nasdaq Exchange"], "confidence": 0.88}],
  "metrics": ["revenue"],
  "market_metrics": [],
  "sub_questions": [{"question": "Nasdaq Inc. 近三年营收是多少？", "focus": "revenue", "type": "metric_lookup"}],
  "source_requirements": {"needs_document_evidence": true, "needs_filing_evidence": true},
  "confidence": 0.88,
  "ambiguities": []
}
```