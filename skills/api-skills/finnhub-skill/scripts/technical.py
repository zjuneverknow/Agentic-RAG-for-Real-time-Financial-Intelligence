from __future__ import annotations

import argparse

from tool_common import add_common_args, emit, help_payload, run_finnhub_tool


DESCRIPTION = "Technical analysis data: indicators such as RSI, MACD, SMA, EMA over historical candles."
OPERATIONS = {
    "indicator": {
        "endpoint": "/indicator",
        "when": "technical indicator value/series: RSI, MACD, SMA, EMA, Bollinger Bands if supported",
        "required": ["symbol", "indicator"],
        "optional": ["resolution", "lookback-days", "limit", "question"],
    }
}


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("help")

    indicator = sub.add_parser("indicator")
    add_common_args(indicator)
    indicator.add_argument("--indicator", required=True, help="Finnhub indicator name, e.g. rsi, macd, sma, ema.")
    indicator.add_argument("--resolution", default="D", choices=["1", "5", "15", "30", "60", "D", "W", "M"])

    args = parser.parse_args()
    if args.operation == "help":
        emit(help_payload("technical", DESCRIPTION, OPERATIONS))
        return 0
    if args.operation == "indicator":
        return run_finnhub_tool(
            tool_name="technical_indicator",
            question=args.question,
            symbol=args.symbol,
            limit=args.limit,
            lookback_days=args.lookback_days,
            indicator=args.indicator,
            resolution=args.resolution,
            fallback_tools=["stock_candles"],
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
