from __future__ import annotations

import argparse

from tool_common import add_common_args, emit, help_payload, run_finnhub_tool


DESCRIPTION = "Fundamental data: valuation metrics, reported financials, earnings, dividends, and earnings calendar."
OPERATIONS = {
    "metrics": {
        "endpoint": "/stock/metric",
        "when": "PE/PB/PS/EPS, market capitalization, 52-week high/low, valuation ratios",
        "required": ["symbol"],
        "optional": ["question"],
    },
    "financials": {
        "endpoint": "/stock/financials-reported",
        "when": "reported financial statements from Finnhub, not original PDF table evidence",
        "required": ["symbol"],
        "optional": ["question"],
    },
    "earnings": {
        "endpoint": "/stock/earnings",
        "when": "EPS actual/estimate history, earnings surprises",
        "required": ["symbol"],
        "optional": ["limit", "question"],
    },
    "dividends": {
        "endpoint": "/stock/dividend",
        "when": "dividend history, dividend date and amount",
        "required": ["symbol"],
        "optional": ["lookback-days", "question"],
    },
    "earnings-calendar": {
        "endpoint": "/calendar/earnings",
        "when": "upcoming or recent earnings calendar for a symbol or market-wide date window",
        "required": [],
        "optional": ["symbol", "lookback-days", "question"],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("help")

    metrics = sub.add_parser("metrics")
    add_common_args(metrics)

    financials = sub.add_parser("financials")
    add_common_args(financials)

    earnings = sub.add_parser("earnings")
    add_common_args(earnings)

    dividends = sub.add_parser("dividends")
    add_common_args(dividends)

    calendar = sub.add_parser("earnings-calendar")
    add_common_args(calendar, symbol=False)
    calendar.add_argument("--symbol", default="", help="Optional Finnhub symbol.")

    args = parser.parse_args()
    if args.operation == "help":
        emit(help_payload("fundamentals", DESCRIPTION, OPERATIONS))
        return 0
    if args.operation == "metrics":
        return run_finnhub_tool(
            tool_name="basic_financials",
            question=args.question,
            symbol=args.symbol,
            limit=args.limit,
            lookback_days=args.lookback_days,
            fallback_tools=["company_profile", "stock_price"],
        )
    if args.operation == "financials":
        return run_finnhub_tool(tool_name="financial_statements", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days)
    if args.operation == "earnings":
        return run_finnhub_tool(tool_name="earnings_history", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days)
    if args.operation == "dividends":
        return run_finnhub_tool(tool_name="stock_dividends", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days)
    if args.operation == "earnings-calendar":
        return run_finnhub_tool(tool_name="earnings_calendar", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
