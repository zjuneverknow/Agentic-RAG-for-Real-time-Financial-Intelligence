from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from nodes.retrieval.finnhub_mcp import FINNHUB_TOOLS, finnhub_client, route_finnhub_tool, to_finnhub_document


def _fallback_route(route, tool_name: str):
    update = route.model_copy(update={"tool_name": tool_name})
    if tool_name == "market_news":
        update.symbol = ""
    return update


def _call_finnhub_tool(client, route, question: str) -> Any:
    tool = route.tool_name
    symbol = (route.symbol or "").upper()
    today = date.today()
    from_day = today - timedelta(days=route.lookback_days)

    if tool == "stock_price":
        return client.quote(symbol)
    if tool == "stock_candles":
        start_ts = int(datetime.combine(from_day, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
        end_ts = int(datetime.now(timezone.utc).timestamp())
        return client.stock_candles(symbol, route.resolution, start_ts, end_ts)
    if tool == "company_profile":
        return client.company_profile2(symbol=symbol)
    if tool == "company_peers":
        return client.company_peers(symbol)
    if tool == "basic_financials":
        return client.company_basic_financials(symbol, "all")
    if tool == "financial_statements":
        return client.financials_reported(symbol=symbol)
    if tool == "earnings_history":
        return client.company_earnings(symbol, limit=route.limit)
    if tool == "earnings_calendar":
        return client.earnings_calendar(_from=from_day.isoformat(), to=today.isoformat(), symbol=symbol or None)
    if tool == "stock_dividends":
        return client.stock_dividends(symbol, _from=from_day.isoformat(), to=today.isoformat())
    if tool == "analyst_recommendations":
        return client.recommendation_trends(symbol)
    if tool == "price_target":
        return client.price_target(symbol)
    if tool == "upgrade_downgrade":
        return client.upgrade_downgrade(symbol=symbol, _from=from_day.isoformat(), to=today.isoformat())
    if tool == "insider_transactions":
        return client.stock_insider_transactions(symbol=symbol, _from=from_day.isoformat(), to=today.isoformat())
    if tool == "institutional_ownership":
        return client.institutional_ownership(symbol=symbol, limit=route.limit)
    if tool == "company_news":
        return client.company_news(symbol=symbol, _from=from_day.isoformat(), to=today.isoformat())
    if tool == "market_news":
        return client.general_news(route.category, min_id=0)
    if tool == "news_sentiment":
        return client.news_sentiment(symbol)
    if tool == "technical_indicator":
        start_ts = int(datetime.combine(from_day, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
        end_ts = int(datetime.now(timezone.utc).timestamp())
        return client.technical_indicator(
            symbol=symbol,
            resolution=route.resolution,
            _from=start_ts,
            to=end_ts,
            indicator=route.indicator,
            indicator_fields={},
        )
    if tool == "stock_symbols":
        return client.stock_symbols(route.market)
    if tool == "stock_search":
        query = symbol or question
        return client.symbol_lookup(query)
    raise ValueError("Unsupported tool_name")


def call_native_finnhub(question: str, symbol: str) -> Optional[object]:
    client = finnhub_client()
    if client is None:
        return None

    route = route_finnhub_tool(question=question, symbol=symbol)
    routes = [route]
    for tool_name in route.fallback_tools:
        if tool_name in FINNHUB_TOOLS and tool_name != route.tool_name:
            routes.append(_fallback_route(route, tool_name))

    for candidate in routes:
        if FINNHUB_TOOLS[candidate.tool_name]["need_symbol"] and not candidate.symbol:
            continue
        payload = _call_finnhub_tool(client, candidate, question)
        doc = to_finnhub_document(candidate, payload, question, "Finnhub MCP", "finnhub")
        if doc is not None:
            if candidate.tool_name != route.tool_name:
                doc.metadata["selected_tool_name"] = route.tool_name
                doc.metadata["fallback_used"] = candidate.tool_name
            return doc
    return None
