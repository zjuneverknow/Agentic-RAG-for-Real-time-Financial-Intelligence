import asyncio
import json
import os
import shlex
from datetime import date, timedelta
from typing import Any, Dict, Iterable, Optional

from nodes.retrieval.finnhub_mcp import FINNHUB_TOOLS, route_finnhub_tool, tool_result_to_text, to_finnhub_document

GIT_TOOL_HINTS: Dict[str, tuple[str, ...]] = {
    "stock_price": ("finnhub_stock_market_data", "stock_market_data", "market_data"),
    "stock_candles": ("finnhub_stock_market_data", "stock_market_data", "market_data"),
    "company_profile": ("finnhub_stock_fundamentals", "stock_fundamentals", "fundamentals"),
    "company_peers": ("finnhub_stock_fundamentals", "stock_fundamentals", "fundamentals"),
    "basic_financials": ("finnhub_stock_fundamentals", "stock_fundamentals", "fundamentals"),
    "financial_statements": ("finnhub_stock_fundamentals", "stock_fundamentals", "fundamentals"),
    "earnings_history": ("finnhub_stock_fundamentals", "stock_fundamentals", "fundamentals"),
    "earnings_calendar": ("finnhub_calendar_data", "calendar_data", "calendar"),
    "stock_dividends": ("finnhub_stock_fundamentals", "stock_fundamentals", "fundamentals"),
    "analyst_recommendations": ("finnhub_stock_estimates", "stock_estimates", "estimates"),
    "price_target": ("finnhub_stock_estimates", "stock_estimates", "estimates"),
    "upgrade_downgrade": ("finnhub_market_events", "market_events", "events"),
    "insider_transactions": ("finnhub_stock_ownership", "stock_ownership", "ownership"),
    "institutional_ownership": ("finnhub_stock_ownership", "stock_ownership", "ownership"),
    "company_news": ("finnhub_news_sentiment", "news_sentiment", "news"),
    "market_news": ("finnhub_news_sentiment", "news_sentiment", "news"),
    "news_sentiment": ("finnhub_news_sentiment", "news_sentiment", "news"),
    "technical_indicator": ("finnhub_technical_analysis", "technical_analysis", "technical"),
    "stock_symbols": ("finnhub_stock_market_data", "stock_market_data", "market_data"),
    "stock_search": ("finnhub_stock_market_data", "stock_market_data", "market_data"),
}

GIT_OPERATION_HINTS: Dict[str, tuple[str, ...]] = {
    "stock_price": ("get_quote", "quote"),
    "stock_candles": ("get_candles", "candles", "get_stock_candles"),
    "company_profile": ("get_company_profile", "get_profile", "company_profile"),
    "company_peers": ("get_company_peers", "get_peers", "company_peers"),
    "basic_financials": ("get_basic_financials", "basic_financials"),
    "financial_statements": ("get_financials_reported", "financials_reported", "get_financials"),
    "earnings_history": ("get_earnings", "earnings"),
    "earnings_calendar": ("get_earnings_calendar", "earnings_calendar"),
    "stock_dividends": ("get_dividends", "dividends"),
    "analyst_recommendations": ("get_recommendation_trends", "recommendation_trends", "get_analyst_recommendations"),
    "price_target": ("get_price_target", "price_target"),
    "upgrade_downgrade": ("get_upgrades_downgrades", "get_upgrade_downgrade", "upgrade_downgrade"),
    "insider_transactions": ("get_insider_transactions", "get_insider_trades", "insider_transactions"),
    "institutional_ownership": ("get_institutional_ownership", "institutional_ownership"),
    "company_news": ("get_company_news", "company_news"),
    "market_news": ("get_market_news", "market_news", "general_news"),
    "news_sentiment": ("get_news_sentiment", "news_sentiment"),
    "technical_indicator": ("get_indicator", "indicator", "get_technical_indicator"),
    "stock_symbols": ("get_stock_symbols", "stock_symbols", "list_symbols"),
    "stock_search": ("search_symbol", "search_symbols", "symbol_lookup", "search"),
}


def _tool_collection(result: Any) -> Iterable[Any]:
    if result is None:
        return []
    if isinstance(result, list):
        return result
    tools = getattr(result, "tools", None)
    if tools is not None:
        return tools
    return []


def _tool_input_schema(tool: Any) -> Dict[str, Any]:
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
    return schema if isinstance(schema, dict) else {}


def _tool_uses_instruction_only(tool: Any) -> bool:
    schema = _tool_input_schema(tool)
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    return list(properties.keys()) == ["instruction"] or required == ["instruction"]


def _pick_git_tool_name(route, tools: Iterable[Any]) -> str:
    tools = list(tools)
    hints = GIT_TOOL_HINTS.get(route.tool_name, ())
    ranked = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "")
        description = str(getattr(tool, "description", "") or "")
        haystack = f"{name} {description}".lower()
        score = 0
        for hint in hints:
            if hint.lower() in haystack:
                score += len(hint)
        ranked.append((score, name))

    ranked.sort(reverse=True)
    best_score, best_name = ranked[0] if ranked else (0, "")
    if best_score <= 0:
        available = [str(getattr(tool, "name", "") or "") for tool in tools]
        raise ValueError(f"No matching mcp-finnhub tool found for route '{route.tool_name}', available_tools={available}")
    return best_name


def _extract_operation_names(help_result: Any) -> list[str]:
    candidates: list[str] = []
    structured = getattr(help_result, "structuredContent", None)
    if isinstance(structured, dict):
        for key in ("operations", "valid_operations"):
            value = structured.get(key)
            if isinstance(value, list):
                candidates.extend(str(item) for item in value if item)
    if candidates:
        return candidates

    text = tool_result_to_text(help_result)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        for key in ("operations", "valid_operations"):
            value = parsed.get(key)
            if isinstance(value, list):
                candidates.extend(str(item) for item in value if item)
    return candidates


async def _resolve_operation_name(session, tool_name: str, route) -> str:
    preferred = GIT_OPERATION_HINTS.get(route.tool_name, ())
    try:
        help_result = await session.call_tool(tool_name, {"operation": "help"})
    except Exception:
        return preferred[0] if preferred else "help"

    operations = _extract_operation_names(help_result)
    if not operations:
        return preferred[0] if preferred else "help"

    best_score = -1
    best_name = operations[0]
    for operation in operations:
        haystack = operation.lower()
        score = 0
        for hint in preferred:
            if hint.lower() in haystack:
                score += len(hint)
        if score > best_score:
            best_score = score
            best_name = operation
    return best_name


def _build_candidate_args(route, question: str, operation: str) -> Dict[str, Any]:
    symbol = (route.symbol or "").upper()
    today = date.today()
    from_day = today - timedelta(days=route.lookback_days)
    project = (os.getenv("FINNHUB_GIT_PROJECT") or "").strip()
    args: Dict[str, Any] = {
        "operation": operation,
        "symbol": symbol,
        "query": symbol or question,
        "instruction": question,
        "resolution": route.resolution,
        "indicator": route.indicator,
        "market": route.market,
        "exchange": route.market,
        "category": route.category,
        "from": from_day.isoformat(),
        "to": today.isoformat(),
        "from_date": from_day.isoformat(),
        "to_date": today.isoformat(),
        "start_date": from_day.isoformat(),
        "end_date": today.isoformat(),
        "limit": route.limit,
        "project": project,
    }
    return {key: value for key, value in args.items() if value not in {"", None}}


def _tool_call_args(tool: Any, route, question: str, operation: str) -> Dict[str, Any]:
    if _tool_uses_instruction_only(tool):
        return {"instruction": question}

    args = _build_candidate_args(route, question, operation)
    schema = _tool_input_schema(tool)
    properties = schema.get("properties") or {}
    if not properties:
        return args
    filtered = {key: value for key, value in args.items() if key in properties}
    if "operation" in properties and "operation" not in filtered:
        filtered["operation"] = operation
    return filtered


def _server_command() -> tuple[str, list[str]]:
    command = (os.getenv("FINNHUB_GIT_COMMAND") or "mcp-finnhub").strip()
    args_raw = (os.getenv("FINNHUB_GIT_ARGS") or "").strip()
    args = shlex.split(args_raw, posix=os.name != "nt") if args_raw else []
    return command, args


def _server_env() -> Dict[str, str]:
    env = {str(key): str(value) for key, value in os.environ.items() if value is not None}
    if "FINNHUB_API_KEY" not in env and env.get("FINN_HUB_API"):
        env["FINNHUB_API_KEY"] = env["FINN_HUB_API"]
    env.setdefault("FINNHUB_STORAGE_DIR", os.getenv("FINNHUB_GIT_STORAGE_DIR", os.path.join(os.getcwd(), "documents", "finnhub_mcp")))
    return env


async def _call_git_mcp_async(question: str, symbol: str):
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise RuntimeError("Python package 'mcp' is required for git-based Finnhub MCP support.") from exc

    route = route_finnhub_tool(question=question, symbol=symbol)
    if FINNHUB_TOOLS[route.tool_name]["need_symbol"] and not route.symbol:
        return None

    command, args = _server_command()
    server_params = StdioServerParameters(command=command, args=args, env=_server_env())

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(
            read_stream=read_stream,
            write_stream=write_stream,
            read_timeout_seconds=timedelta(seconds=300),
        ) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tools = list(_tool_collection(tools_result))
            selected_tool = _pick_git_tool_name(route, tools)
            tools_by_name = {str(getattr(tool, "name", "") or ""): tool for tool in tools}
            selected_tool_def = tools_by_name.get(selected_tool)
            operation = await _resolve_operation_name(session, selected_tool, route)
            tool_result = await session.call_tool(
                selected_tool,
                _tool_call_args(selected_tool_def, route, question, operation) if selected_tool_def is not None else _build_candidate_args(route, question, operation),
            )

    doc = to_finnhub_document(route, tool_result, question, "Git Finnhub MCP", "git_finnhub")
    if doc is not None:
        doc.metadata["git_mcp_command"] = command
        doc.metadata["git_mcp_operation"] = operation
        doc.metadata["git_mcp_tool"] = selected_tool
    return doc


def call_git_finnhub(question: str, symbol: str) -> Optional[object]:
    return asyncio.run(_call_git_mcp_async(question, symbol))
