from __future__ import annotations

import argparse

from tool_common import add_common_args, emit, help_payload, run_finnhub_tool


DESCRIPTION = "News and sentiment data: company news, market news, and company news sentiment."
OPERATIONS = {
    "company-news": {
        "endpoint": "/company-news",
        "when": "company-specific headlines, news flow, recent events, catalysts",
        "required": ["symbol"],
        "optional": ["lookback-days", "limit", "question"],
    },
    "market-news": {
        "endpoint": "/news",
        "when": "broad market headlines, macro/market news without a single company symbol",
        "required": [],
        "optional": ["category", "limit", "question"],
    },
    "sentiment": {
        "endpoint": "/news-sentiment",
        "when": "news sentiment score, bullish/bearish news mood, company media sentiment",
        "required": ["symbol"],
        "optional": ["question"],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("help")

    company = sub.add_parser("company-news")
    add_common_args(company)

    market = sub.add_parser("market-news")
    add_common_args(market, symbol=False)
    market.add_argument("--category", default="general", help="Finnhub news category, e.g. general, forex, crypto, merger.")

    sentiment = sub.add_parser("sentiment")
    add_common_args(sentiment)

    args = parser.parse_args()
    if args.operation == "help":
        emit(help_payload("news", DESCRIPTION, OPERATIONS))
        return 0
    if args.operation == "company-news":
        return run_finnhub_tool(
            tool_name="company_news",
            question=args.question,
            symbol=args.symbol,
            limit=args.limit,
            lookback_days=args.lookback_days,
            fallback_tools=["news_sentiment", "market_news"],
        )
    if args.operation == "market-news":
        return run_finnhub_tool(tool_name="market_news", question=args.question, limit=args.limit, lookback_days=args.lookback_days, category=args.category)
    if args.operation == "sentiment":
        return run_finnhub_tool(tool_name="news_sentiment", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days, fallback_tools=["company_news"])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
