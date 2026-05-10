from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any, Dict, Iterable

from finnhub_api import FinnhubRoute, call


def emit(data: Dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def help_payload(tool: str, description: str, operations: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "ok": True,
        "tool": tool,
        "description": description,
        "operations": operations,
        "usage": f"python skills/api-skills/finnhub-skill/scripts/{tool}.py <operation> [args]",
    }


def add_common_args(parser: argparse.ArgumentParser, *, symbol: bool = True) -> None:
    if symbol:
        parser.add_argument("--symbol", required=True, help="Finnhub symbol, e.g. AAPL, TSLA, MSFT.")
    parser.add_argument("--question", default="", help="Original user question for evidence traceability.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum returned rows/articles where applicable.")
    parser.add_argument("--lookback-days", type=int, default=30, help="Lookback window for dated endpoints.")


def run_finnhub_tool(
    *,
    tool_name: str,
    question: str = "",
    symbol: str = "",
    reason: str = "",
    fallback_tools: Iterable[str] = (),
    **route_kwargs: Any,
) -> int:
    route = FinnhubRoute(
        tool_name=tool_name,
        symbol=(symbol or "").upper(),
        reason=reason or f"llm_selected:{tool_name}",
        fallback_tools=list(fallback_tools),
        **route_kwargs,
    )
    result = call(question=question or f"Finnhub {tool_name} {symbol}".strip(), symbol=symbol, route_override=route)
    if result.get("ok") and result.get("route"):
        result["llm_tool_call"] = {
            "tool_name": tool_name,
            "route_override": asdict(route),
            "selection_reason": reason,
        }
    emit(result)
    return 0 if result.get("ok") else 1
