from __future__ import annotations

import argparse

from tool_common import add_common_args, emit, help_payload, run_finnhub_tool


DESCRIPTION = "Analyst data: recommendations, price target, upgrades and downgrades."
OPERATIONS = {
    "recommendations": {
        "endpoint": "/stock/recommendation",
        "when": "analyst buy/hold/sell recommendation trends",
        "required": ["symbol"],
        "optional": ["question"],
    },
    "price-target": {
        "endpoint": "/stock/price-target",
        "when": "analyst target price, consensus target, high/low target",
        "required": ["symbol"],
        "optional": ["question"],
    },
    "upgrades": {
        "endpoint": "/stock/upgrade-downgrade",
        "when": "analyst rating changes, upgrade/downgrade events",
        "required": ["symbol"],
        "optional": ["lookback-days", "limit", "question"],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("help")

    rec = sub.add_parser("recommendations")
    add_common_args(rec)

    target = sub.add_parser("price-target")
    add_common_args(target)

    upgrades = sub.add_parser("upgrades")
    add_common_args(upgrades)

    args = parser.parse_args()
    if args.operation == "help":
        emit(help_payload("analyst", DESCRIPTION, OPERATIONS))
        return 0
    if args.operation == "recommendations":
        return run_finnhub_tool(tool_name="analyst_recommendations", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days, fallback_tools=["price_target"])
    if args.operation == "price-target":
        return run_finnhub_tool(tool_name="price_target", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days, fallback_tools=["analyst_recommendations"])
    if args.operation == "upgrades":
        return run_finnhub_tool(tool_name="upgrade_downgrade", question=args.question, symbol=args.symbol, limit=args.limit, lookback_days=args.lookback_days)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
