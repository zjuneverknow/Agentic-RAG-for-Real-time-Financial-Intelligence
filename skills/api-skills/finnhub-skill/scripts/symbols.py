from __future__ import annotations

import argparse

from tool_common import add_common_args, emit, help_payload, run_finnhub_tool


DESCRIPTION = "Symbol discovery: search company names/tickers and list exchange symbols."
OPERATIONS = {
    "search": {
        "endpoint": "/search",
        "when": "user gave company name, Chinese alias, ambiguous ticker, or asks for ticker/symbol",
        "required": ["query"],
        "optional": ["question"],
    },
    "stock-symbols": {
        "endpoint": "/stock/symbol",
        "when": "list all stock symbols for a market/exchange",
        "required": ["market"],
        "optional": ["limit", "question"],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("help")

    search = sub.add_parser("search")
    search.add_argument("--query", required=True, help="Company or ticker search text.")
    search.add_argument("--question", default="", help="Original user question for evidence traceability.")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--lookback-days", type=int, default=7)

    stocks = sub.add_parser("stock-symbols")
    add_common_args(stocks, symbol=False)
    stocks.add_argument("--market", default="US", help="Market/exchange code, e.g. US.")

    args = parser.parse_args()
    if args.operation == "help":
        emit(help_payload("symbols", DESCRIPTION, OPERATIONS))
        return 0
    if args.operation == "search":
        return run_finnhub_tool(tool_name="stock_search", question=args.question or args.query, symbol=args.query, limit=args.limit, lookback_days=args.lookback_days)
    if args.operation == "stock-symbols":
        return run_finnhub_tool(tool_name="stock_symbols", question=args.question, limit=args.limit, lookback_days=args.lookback_days, market=args.market)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
