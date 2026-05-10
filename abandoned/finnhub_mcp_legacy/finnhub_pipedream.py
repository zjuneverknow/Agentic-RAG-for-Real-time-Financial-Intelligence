import asyncio
import json
import os
from datetime import date, timedelta
from typing import Any, Dict, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nodes.retrieval.finnhub_mcp import FINNHUB_TOOLS, route_finnhub_tool, to_finnhub_document


PIPEDREAM_TOOL_HINTS: Dict[str, tuple[str, ...]] = {
    "stock_price": ("quote", "price", "stock quote", "latest price"),
    "stock_candles": ("candle", "candles", "ohlc", "chart"),
    "company_profile": ("profile", "company profile", "company"),
    "company_peers": ("peer", "peers", "competitor"),
    "basic_financials": ("financial", "metrics", "pe", "pb", "valuation", "fundamental"),
    "financial_statements": ("financial statements", "reported financials", "report"),
    "earnings_history": ("earnings", "eps", "earnings history"),
    "earnings_calendar": ("earnings calendar", "calendar"),
    "stock_dividends": ("dividend", "dividends"),
    "analyst_recommendations": ("recommendation", "analyst recommendation", "rating"),
    "price_target": ("price target", "target"),
    "upgrade_downgrade": ("upgrade", "downgrade"),
    "insider_transactions": ("insider", "insider transactions"),
    "institutional_ownership": ("institutional ownership", "holder", "ownership"),
    "company_news": ("company news", "news"),
    "market_news": ("market news", "general news"),
    "news_sentiment": ("sentiment", "news sentiment"),
    "technical_indicator": ("indicator", "rsi", "macd", "sma"),
    "stock_symbols": ("symbols", "symbol list"),
    "stock_search": ("search", "ticker search", "symbol lookup"),
}


def _selected_tool_mode() -> str:
    return (os.getenv("PIPEDREAM_MCP_TOOL_MODE") or "tools-only").strip().lower()


def _required_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_access_token() -> str:
    client_id = _required_env("PIPEDREAM_CLIENT_ID")
    client_secret = _required_env("PIPEDREAM_CLIENT_SECRET")

    body = json.dumps(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")
    request = Request(
        "https://api.pipedream.com/v1/oauth/token",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Pipedream OAuth token request failed: HTTP {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Pipedream OAuth token request failed: {exc.reason}") from exc

    access_token = (payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Pipedream OAuth token response did not include access_token.")
    return access_token


def _pipedream_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {_get_access_token()}",
    }
    optional_headers = {
        "x-pd-project-id": _required_env("PIPEDREAM_PROJECT_ID"),
        "x-pd-environment": _required_env("PIPEDREAM_ENVIRONMENT"),
        "x-pd-external-user-id": _required_env("PIPEDREAM_MCP_EXTERNAL_USER_ID"),
        "x-pd-app-slug": _required_env("PIPEDREAM_MCP_APP_SLUG"),
        "x-pd-tool-mode": _selected_tool_mode(),
        "x-pd-account-id": os.getenv("PIPEDREAM_MCP_ACCOUNT_ID"),
    }
    for key, value in optional_headers.items():
        if value:
            headers[key] = value
    return headers


def _tool_collection(result: Any) -> Iterable[Any]:
    if result is None:
        return []
    if isinstance(result, list):
        return result
    tools = getattr(result, "tools", None)
    if tools is not None:
        return tools
    return []


def _pick_pipedream_tool_name(route, tools: Iterable[Any]) -> str:
    tools = list(tools)
    hints = PIPEDREAM_TOOL_HINTS.get(route.tool_name, ())
    ranked = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "")
        description = str(getattr(tool, "description", "") or "")
        haystack = f"{name} {description}".lower()
        score = 0
        for hint in hints:
            if hint.lower() in haystack:
                score += len(hint)
        if route.tool_name.lower() in haystack:
            score += 50
        ranked.append((score, name))

    ranked.sort(reverse=True)
    best_score, best_name = ranked[0] if ranked else (0, "")
    if best_score <= 0:
        mode = _selected_tool_mode()
        if mode == "sub-agent" and len(tools) == 1:
            return str(getattr(tools[0], "name", "") or "")
        available = [str(getattr(tool, "name", "") or "") for tool in tools]
        raise ValueError(
            f"No matching Pipedream Finnhub tool found for route '{route.tool_name}'. "
            f"tool_mode='{mode}', available_tools={available}"
        )
    return best_name


def _tool_input_schema(tool: Any) -> Dict[str, Any]:
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
    return schema if isinstance(schema, dict) else {}


def _tool_uses_instruction_only(tool: Any) -> bool:
    schema = _tool_input_schema(tool)
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    return list(properties.keys()) == ["instruction"] or required == ["instruction"]


def _pipedream_tool_args(route, question: str) -> Dict[str, Any]:
    symbol = (route.symbol or "").upper()
    today = date.today()
    from_day = today - timedelta(days=route.lookback_days)
    args: Dict[str, Any] = {
        "symbol": symbol,
        "query": symbol or question,
        "resolution": route.resolution,
        "indicator": route.indicator,
        "market": route.market,
        "category": route.category,
        "from": from_day.isoformat(),
        "to": today.isoformat(),
        "limit": route.limit,
    }
    return {key: value for key, value in args.items() if value not in {"", None}}


def _tool_call_args(selected_tool_name: str, route, question: str, tools: Iterable[Any]) -> Dict[str, Any]:
    tools_by_name = {str(getattr(tool, "name", "") or ""): tool for tool in tools}
    tool = tools_by_name.get(selected_tool_name)
    if tool is not None and _tool_uses_instruction_only(tool):
        return {"instruction": question}
    return _pipedream_tool_args(route, question)


async def _call_pipedream_mcp_async(question: str, symbol: str):
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError as exc:
        raise RuntimeError("Python package 'mcp' is required for Pipedream MCP support.") from exc

    route = route_finnhub_tool(question=question, symbol=symbol)
    if FINNHUB_TOOLS[route.tool_name]["need_symbol"] and not route.symbol:
        return None

    server_url = (os.getenv("PIPEDREAM_MCP_SERVER_URL") or "https://remote.mcp.pipedream.net").strip()
    headers = _pipedream_headers()

    async with streamablehttp_client(
        server_url,
        headers=headers,
        timeout=timedelta(seconds=30),
        sse_read_timeout=timedelta(seconds=300),
    ) as streams:
        read_stream, write_stream, session_id_callback = streams
        async with ClientSession(
            read_stream=read_stream,
            write_stream=write_stream,
            read_timeout_seconds=timedelta(seconds=300),
        ) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tools = list(_tool_collection(tools_result))
            selected_tool = _pick_pipedream_tool_name(route, tools)
            tool_result = await session.call_tool(selected_tool, _tool_call_args(selected_tool, route, question, tools))

    doc = to_finnhub_document(route, tool_result, question, "Pipedream Finnhub MCP", "pipedream_finnhub")
    if doc is not None:
        doc.metadata["pipedream_session_id"] = session_id_callback() if callable(session_id_callback) else None
    return doc


def call_pipedream_finnhub(question: str, symbol: str) -> Optional[object]:
    return asyncio.run(_call_pipedream_mcp_async(question, symbol))
