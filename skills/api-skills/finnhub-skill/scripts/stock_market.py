from __future__ import annotations

import argparse

from tool_common import add_common_args, emit, help_payload, run_finnhub_tool


DESCRIPTION = "Stock market data: real-time quote, historical candles, company profile, and peers."
OPERATIONS = {
    "quote": {
        "endpoint": "/quote",
        "when": "latest/current price, open/high/low/previous close, intraday quote",
        "required": ["symbol"],
        "optional": ["question"],
    },
    "candles": {
        "endpoint": "/stock/candle",
        "when": "price trend, K-line/candle history, recent performance over a time window",
        "required": ["symbol"],
        "optional": ["resolution", "lookback-days", "limit", "question"],
    },
    "profile": {
        "endpoint": "/stock/profile2",
        "when": "company identity, exchange, industry, IPO date, logo, market cap profile",
        "required": ["symbol"],
        "optional": ["question"],
    },
    "peers": {
        "endpoint": "/stock/peers",
        "when": "competitors, peer companies, comparable companies",
        "required": ["symbol"],
        "optional": ["question"],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("help")

    quote = sub.add_parser("quote")
    add_common_args(quote)

    candles = sub.add_parser("candles")
    add_common_args(candles)
    candles.add_argument("--resolution", default="D", choices=["1", "5", "15", "30", "60", "D", "W", "M"])

    profile = sub.add_parser("profile")
    add_common_args(profile)

    peers = sub.add_parser("peers")
    add_common_args(peers)

    args = parser.parse_args()
    if args.operation == "help":
        emit(help_payload("stock_market", DESCRIPTION, OPERATIONS))
        return 0
    if args.operation == "quote":
        return run_finnhub_tool(tool_name="stock_price", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days)
    if args.operation == "candles":
        return run_finnhub_tool(
            tool_name="stock_candles",
            question=args.question,
            symbol=args.symbol,
            limit=args.limit,
            lookback_days=args.lookback_days,
            resolution=args.resolution,
            fallback_tools=["stock_price"],
        )
    if args.operation == "profile":
        return run_finnhub_tool(tool_name="company_profile", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days)
    if args.operation == "peers":
        return run_finnhub_tool(tool_name="company_peers", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
