from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import finnhub

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


FINNHUB_TOOLS: Dict[str, Dict[str, Any]] = {
    "stock_price": {"endpoint": "/quote", "desc": "latest quote", "need_symbol": True},
    "stock_candles": {"endpoint": "/stock/candle", "desc": "historical candles", "need_symbol": True},
    "company_profile": {"endpoint": "/stock/profile2", "desc": "company profile", "need_symbol": True},
    "company_peers": {"endpoint": "/stock/peers", "desc": "peer companies", "need_symbol": True},
    "basic_financials": {"endpoint": "/stock/metric", "desc": "financial and valuation metrics", "need_symbol": True},
    "financial_statements": {"endpoint": "/stock/financials-reported", "desc": "reported financial statements", "need_symbol": True},
    "earnings_history": {"endpoint": "/stock/earnings", "desc": "earnings history", "need_symbol": True},
    "earnings_calendar": {"endpoint": "/calendar/earnings", "desc": "earnings calendar", "need_symbol": False},
    "stock_dividends": {"endpoint": "/stock/dividend", "desc": "dividend history", "need_symbol": True},
    "analyst_recommendations": {"endpoint": "/stock/recommendation", "desc": "analyst recommendations", "need_symbol": True},
    "price_target": {"endpoint": "/stock/price-target", "desc": "analyst price target", "need_symbol": True},
    "upgrade_downgrade": {"endpoint": "/stock/upgrade-downgrade", "desc": "rating changes", "need_symbol": True},
    "insider_transactions": {"endpoint": "/stock/insider-transactions", "desc": "insider transactions", "need_symbol": True},
    "institutional_ownership": {"endpoint": "/stock/institutional-ownership", "desc": "institutional ownership", "need_symbol": True},
    "company_news": {"endpoint": "/company-news", "desc": "company news", "need_symbol": True},
    "market_news": {"endpoint": "/news", "desc": "market news", "need_symbol": False},
    "news_sentiment": {"endpoint": "/news-sentiment", "desc": "news sentiment", "need_symbol": True},
    "technical_indicator": {"endpoint": "/indicator", "desc": "technical indicator", "need_symbol": True},
    "stock_symbols": {"endpoint": "/stock/symbol", "desc": "market symbols", "need_symbol": False},
    "stock_search": {"endpoint": "/search", "desc": "symbol search", "need_symbol": False},
}


BASIC_FINANCIAL_KEYS = (
    "peTTM",
    "peBasicExclExtraTTM",
    "peNormalizedAnnual",
    "forwardPE",
    "pbAnnual",
    "pbQuarterly",
    "psTTM",
    "epsTTM",
    "epsBasicExclExtraItemsTTM",
    "marketCapitalization",
    "enterpriseValue",
    "52WeekHigh",
    "52WeekLow",
)


@dataclass
class FinnhubRoute:
    tool_name: str = "stock_price"
    symbol: str = ""
    resolution: str = "D"
    indicator: str = "rsi"
    market: str = "US"
    category: str = "general"
    lookback_days: int = 7
    limit: int = 5
    reason: str = ""
    fallback_tools: List[str] = field(default_factory=list)
    not_applicable_reason: str = ""

    @property
    def endpoint(self) -> str:
        return str(FINNHUB_TOOLS.get(self.tool_name, {}).get("endpoint", ""))

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["endpoint"] = self.endpoint
        return data


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lower = (text or "").lower()
    return any(term.lower() in lower for term in terms)


def _safe_limit(value: int, default: int = 5, max_limit: int = 20) -> int:
    return min(max(int(value or default), 1), max_limit)


def _safe_days(value: int, default: int = 7, max_days: int = 365) -> int:
    return min(max(int(value or default), 1), max_days)


def api_key() -> str:
    return os.getenv("FINNHUB_API_KEY") or os.getenv("FINN_HUB_API") or ""


def client() -> Optional[finnhub.Client]:
    token = api_key()
    return finnhub.Client(api_key=token) if token else None


def resolve_symbol(query: str) -> str:
    cli = client()
    if cli is None:
        return ""
    try:
        result = cli.symbol_lookup(query)
    except Exception:
        return ""
    for item in result.get("result", []):
        symbol = str(item.get("symbol") or "").upper()
        if symbol and "." not in symbol:
            return symbol
    return ""


def route(question: str, symbol: str = "") -> FinnhubRoute:
    symbol = (symbol or "").upper()
    if not symbol and _contains_any(question, ("ticker", "symbol", "\u4ee3\u7801", "\u80a1\u7968\u4ee3\u7801")):
        return FinnhubRoute(
            tool_name="stock_search",
            symbol="",
            reason="symbol lookup query",
            fallback_tools=[],
        )

    if symbol and _contains_any(
        question,
        (
            "pe",
            "p/e",
            "pb",
            "p/b",
            "ps",
            "p/s",
            "eps",
            "valuation",
            "market cap",
            "\u5e02\u76c8\u7387",
            "\u5e02\u51c0\u7387",
            "\u5e02\u9500\u7387",
            "\u4f30\u503c",
            "\u6bcf\u80a1\u6536\u76ca",
            "\u5e02\u503c",
        ),
    ):
        return FinnhubRoute(
            tool_name="basic_financials",
            symbol=symbol,
            reason="valuation or market metric query",
            fallback_tools=["company_profile", "stock_price"],
        )

    if symbol and _contains_any(question, ("price target", "target price", "analyst target", "\u76ee\u6807\u4ef7")):
        return FinnhubRoute(
            tool_name="price_target",
            symbol=symbol,
            lookback_days=30,
            reason="analyst target price query",
            fallback_tools=["analyst_recommendations"],
        )

    if symbol and _contains_any(
        question,
        ("recommendation", "rating", "analyst view", "analyst", "\u8bc4\u7ea7", "\u5206\u6790\u5e08", "\u4e70\u5165", "\u5356\u51fa", "\u6301\u6709"),
    ):
        return FinnhubRoute(
            tool_name="analyst_recommendations",
            symbol=symbol,
            lookback_days=30,
            reason="analyst recommendation query",
            fallback_tools=["price_target"],
        )

    if symbol and _contains_any(question, ("news", "headline", "\u6d88\u606f", "\u65b0\u95fb", "\u6d88\u606f\u9762", "\u4e8b\u4ef6")):
        return FinnhubRoute(
            tool_name="company_news",
            symbol=symbol,
            lookback_days=14,
            limit=10,
            reason="company-specific news query",
            fallback_tools=["news_sentiment", "market_news"],
        )

    if symbol and _contains_any(question, ("sentiment", "\u60c5\u7eea", "\u8206\u60c5")):
        return FinnhubRoute(
            tool_name="news_sentiment",
            symbol=symbol,
            lookback_days=14,
            reason="company news sentiment query",
            fallback_tools=["company_news"],
        )

    if symbol and _contains_any(question, ("rsi", "macd", "sma", "ema", "technical", "\u6280\u672f\u6307\u6807")):
        lower = question.lower()
        indicator = "macd" if "macd" in lower else "sma" if "sma" in lower else "ema" if "ema" in lower else "rsi"
        return FinnhubRoute(
            tool_name="technical_indicator",
            symbol=symbol,
            indicator=indicator,
            lookback_days=30,
            limit=10,
            reason="technical indicator query",
            fallback_tools=["stock_candles"],
        )

    if symbol and _contains_any(question, ("trend", "chart", "k-line", "kline", "recent performance", "\u8d70\u52bf", "\u8d8b\u52bf", "k\u7ebf", "\u5386\u53f2\u4ef7\u683c")):
        return FinnhubRoute(
            tool_name="stock_candles",
            symbol=symbol,
            lookback_days=30,
            limit=10,
            reason="price trend or candle query",
            fallback_tools=["stock_price"],
        )

    if symbol and _contains_any(question, ("profile", "company intro", "industry", "exchange", "\u516c\u53f8\u4ecb\u7ecd", "\u884c\u4e1a", "\u4ea4\u6613\u6240")):
        return FinnhubRoute(
            tool_name="company_profile",
            symbol=symbol,
            reason="company profile query",
            fallback_tools=["stock_price"],
        )

    if _contains_any(question, ("market news", "market headlines", "\u5e02\u573a\u65b0\u95fb", "\u5927\u76d8\u65b0\u95fb")):
        return FinnhubRoute(
            tool_name="market_news",
            category="general",
            limit=10,
            reason="broad market news query",
        )

    if symbol:
        return FinnhubRoute(tool_name="stock_price", symbol=symbol, reason="default symbol market data query")

    return FinnhubRoute(
        tool_name="stock_search",
        symbol="",
        reason="symbol missing; search is the safest Finnhub action",
        not_applicable_reason="No symbol was provided for a symbol-required Finnhub endpoint.",
    )


def _call_tool(cli: finnhub.Client, route_info: FinnhubRoute, question: str) -> Any:
    today = date.today()
    from_day = today - timedelta(days=route_info.lookback_days)
    symbol = route_info.symbol.upper()
    tool = route_info.tool_name

    if tool == "stock_price":
        return cli.quote(symbol)
    if tool == "stock_candles":
        start_ts = int(datetime.combine(from_day, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
        end_ts = int(datetime.now(timezone.utc).timestamp())
        return cli.stock_candles(symbol, route_info.resolution, start_ts, end_ts)
    if tool == "company_profile":
        return cli.company_profile2(symbol=symbol)
    if tool == "company_peers":
        return cli.company_peers(symbol)
    if tool == "basic_financials":
        return cli.company_basic_financials(symbol, "all")
    if tool == "financial_statements":
        return cli.financials_reported(symbol=symbol)
    if tool == "earnings_history":
        return cli.company_earnings(symbol, limit=route_info.limit)
    if tool == "earnings_calendar":
        return cli.earnings_calendar(_from=from_day.isoformat(), to=today.isoformat(), symbol=symbol or None)
    if tool == "stock_dividends":
        return cli.stock_dividends(symbol, _from=from_day.isoformat(), to=today.isoformat())
    if tool == "analyst_recommendations":
        return cli.recommendation_trends(symbol)
    if tool == "price_target":
        return cli.price_target(symbol)
    if tool == "upgrade_downgrade":
        return cli.upgrade_downgrade(symbol=symbol, _from=from_day.isoformat(), to=today.isoformat())
    if tool == "insider_transactions":
        return cli.stock_insider_transactions(symbol=symbol, _from=from_day.isoformat(), to=today.isoformat())
    if tool == "institutional_ownership":
        return cli.institutional_ownership(symbol=symbol, limit=route_info.limit)
    if tool == "company_news":
        return cli.company_news(symbol=symbol, _from=from_day.isoformat(), to=today.isoformat())
    if tool == "market_news":
        return cli.general_news(route_info.category, min_id=0)
    if tool == "news_sentiment":
        return cli.news_sentiment(symbol)
    if tool == "technical_indicator":
        start_ts = int(datetime.combine(from_day, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
        end_ts = int(datetime.now(timezone.utc).timestamp())
        return cli.technical_indicator(
            symbol=symbol,
            resolution=route_info.resolution,
            _from=start_ts,
            to=end_ts,
            indicator=route_info.indicator,
            indicator_fields={},
        )
    if tool == "stock_symbols":
        return cli.stock_symbols(route_info.market)
    if tool == "stock_search":
        return cli.symbol_lookup(symbol or question)
    raise ValueError(f"Unsupported Finnhub tool: {tool}")


def _payload_text(payload: Any, limit: int, route_info: Optional[FinnhubRoute] = None) -> str:
    if route_info and route_info.tool_name == "basic_financials" and isinstance(payload, dict):
        metrics = payload.get("metric") or {}
        compact_metrics = {
            key: metrics.get(key)
            for key in BASIC_FINANCIAL_KEYS
            if isinstance(metrics, dict) and metrics.get(key) not in (None, "", [], {})
        }
        return json.dumps(
            {
                "symbol": payload.get("symbol"),
                "metricType": payload.get("metricType"),
                "metric": compact_metrics,
            },
            ensure_ascii=False,
            default=str,
        )
    body = payload[:limit] if isinstance(payload, list) else payload
    return json.dumps(body, ensure_ascii=False, default=str)


def _headline(route_info: FinnhubRoute, payload: Any) -> str:
    if route_info.tool_name != "basic_financials" or not isinstance(payload, dict):
        return ""
    metrics = payload.get("metric") or {}
    if not isinstance(metrics, dict):
        return ""
    lines = ["# Key Finnhub metrics"]
    for key in BASIC_FINANCIAL_KEYS:
        value = metrics.get(key)
        if value not in (None, "", [], {}):
            lines.append(f"{key}: {value}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _empty_payload(payload: Any) -> bool:
    return payload in (None, "", [], {})


def normalize(route_info: FinnhubRoute, payload: Any, question: str, fallback_used: str = "") -> Dict[str, Any]:
    meta = FINNHUB_TOOLS[route_info.tool_name]
    headline = _headline(route_info, payload)
    raw_text = _payload_text(payload, route_info.limit, route_info)
    content = (
        f"Finnhub API tool={route_info.tool_name} endpoint={meta['endpoint']} "
        f"desc={meta['desc']} question={question}\n"
    )
    if headline:
        content += f"result={headline}\n\n# Raw Finnhub payload\n{raw_text}"
    else:
        content += f"result={raw_text}"
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "content": content,
        "metadata": {
            "source": f"finnhub_{route_info.tool_name}",
            "source_type": "finnhub",
            "source_name": "Finnhub API",
            "retrieval_source": "Finnhub API",
            "symbol": route_info.symbol.upper(),
            "tool_name": route_info.tool_name,
            "endpoint": meta["endpoint"],
            "timestamp": timestamp,
            "route_reason": route_info.reason,
            "fallback_tools": list(route_info.fallback_tools),
            "fallback_used": fallback_used,
        },
    }


def call(question: str, symbol: str = "", route_override: Optional[FinnhubRoute] = None) -> Dict[str, Any]:
    route_info = route_override or route(question, symbol)
    route_info.limit = _safe_limit(route_info.limit)
    route_info.lookback_days = _safe_days(route_info.lookback_days)
    cli = client()
    if cli is None:
        return {"ok": False, "route": route_info.to_dict(), "evidence": None, "errors": ["FINNHUB_API_KEY is not configured."]}

    candidates = [route_info]
    for tool_name in route_info.fallback_tools:
        if tool_name in FINNHUB_TOOLS and tool_name != route_info.tool_name:
            candidate = FinnhubRoute(**{**asdict(route_info), "tool_name": tool_name})
            if tool_name == "market_news":
                candidate.symbol = ""
            candidates.append(candidate)

    errors: List[str] = []
    for candidate in candidates:
        if FINNHUB_TOOLS[candidate.tool_name]["need_symbol"] and not candidate.symbol:
            errors.append(f"{candidate.tool_name}: symbol is required")
            continue
        try:
            payload = _call_tool(cli, candidate, question)
        except Exception as exc:
            errors.append(f"{candidate.tool_name}: {type(exc).__name__}: {exc}")
            continue
        if _empty_payload(payload):
            errors.append(f"{candidate.tool_name}: empty payload")
            continue
        fallback_used = candidate.tool_name if candidate.tool_name != route_info.tool_name else ""
        return {
            "ok": True,
            "route": candidate.to_dict(),
            "selected_route": route_info.to_dict(),
            "evidence": normalize(candidate, payload, question, fallback_used=fallback_used),
            "errors": errors,
        }

    return {"ok": False, "route": route_info.to_dict(), "evidence": None, "errors": errors}


def validate() -> Dict[str, Any]:
    cases = [
        ("\u82f9\u679c\u516c\u53f8\u73b0\u5728\u7684PE\u662f\u591a\u5c11\uff1f", "AAPL", "basic_financials"),
        ("What is Tesla current stock price?", "TSLA", "stock_price"),
        ("\u603b\u7ed3\u4e00\u4e0b\u82f1\u4f1f\u8fbe\u6700\u8fd1\u7684\u6d88\u606f\u9762", "NVDA", "company_news"),
        ("\u82f9\u679c\u7684\u76ee\u6807\u4ef7\u662f\u591a\u5c11\uff1f", "AAPL", "price_target"),
        ("\u82f9\u679cRSI\u662f\u591a\u5c11\uff1f", "AAPL", "technical_indicator"),
    ]
    failures = []
    for question, symbol, expected in cases:
        actual = route(question, symbol).tool_name
        if actual != expected:
            failures.append({"question": question, "expected": expected, "actual": actual})
    return {"ok": not failures, "failures": failures, "case_count": len(cases)}


def _print_json(data: Dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description="Finnhub API skill runtime.")
    sub = parser.add_subparsers(dest="command", required=True)

    route_parser = sub.add_parser("route")
    route_parser.add_argument("--question", required=True)
    route_parser.add_argument("--symbol", default="")

    call_parser = sub.add_parser("call")
    call_parser.add_argument("--question", required=True)
    call_parser.add_argument("--symbol", default="")

    sub.add_parser("validate")

    args = parser.parse_args()
    if args.command == "route":
        _print_json(route(args.question, args.symbol).to_dict())
        return 0
    if args.command == "call":
        result = call(args.question, args.symbol)
        _print_json(result)
        return 0 if result.get("ok") else 1
    if args.command == "validate":
        result = validate()
        _print_json(result)
        return 0 if result.get("ok") else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
