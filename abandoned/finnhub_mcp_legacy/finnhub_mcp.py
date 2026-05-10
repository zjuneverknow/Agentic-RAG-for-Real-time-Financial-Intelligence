import json
import os
from pathlib import Path
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional

import finnhub
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from nodes.evidence.evidence_utils import document_to_evidence, extend_evidence

FINNHUB_TOOLS: Dict[str, Dict[str, Any]] = {
    "stock_price": {"endpoint": "/quote", "desc": "latest stock price", "need_symbol": True},
    "stock_candles": {"endpoint": "/stock/candle", "desc": "historical candles", "need_symbol": True},
    "company_profile": {"endpoint": "/stock/profile2", "desc": "company profile", "need_symbol": True},
    "company_peers": {"endpoint": "/stock/peers", "desc": "peer companies", "need_symbol": True},
    "basic_financials": {"endpoint": "/stock/metric", "desc": "key metrics", "need_symbol": True},
    "financial_statements": {"endpoint": "/stock/financials-reported", "desc": "financial reports", "need_symbol": True},
    "earnings_history": {"endpoint": "/stock/earnings", "desc": "historical earnings", "need_symbol": True},
    "earnings_calendar": {"endpoint": "/calendar/earnings", "desc": "upcoming earnings", "need_symbol": False},
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


class FinnhubToolRoute(BaseModel):
    tool_name: Literal[
        "stock_price",
        "stock_candles",
        "company_profile",
        "company_peers",
        "basic_financials",
        "financial_statements",
        "earnings_history",
        "earnings_calendar",
        "stock_dividends",
        "analyst_recommendations",
        "price_target",
        "upgrade_downgrade",
        "insider_transactions",
        "institutional_ownership",
        "company_news",
        "market_news",
        "news_sentiment",
        "technical_indicator",
        "stock_symbols",
        "stock_search",
    ] = Field(description="Selected Finnhub tool name.")
    symbol: str = Field(default="", description="Ticker symbol if required, else empty.")
    resolution: str = Field(default="D", description="For candles/indicator, D/W/M/1/5/15/30/60.")
    indicator: str = Field(default="rsi", description="For technical indicator tool.")
    market: str = Field(default="US", description="For stock_symbols tool.")
    category: str = Field(default="general", description="For market_news tool.")
    lookback_days: int = Field(default=7, description="Lookback days for date-range APIs.")
    limit: int = Field(default=5, description="Top-N rows to keep in document.")
    reason: str = Field(default="", description="Short reason for tool choice.")
    fallback_tools: List[str] = Field(default_factory=list, description="Fallback tools to try if selected tool returns no data.")
    not_applicable_reason: str = Field(default="", description="Why Finnhub should not be used for this query.")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FINNHUB_TOOL_SELECTION_SKILL = PROJECT_ROOT / "skills" / "finnhub-tool-selection" / "SKILL.md"
FINNHUB_TOOL_SELECTION_REFERENCES = (
    PROJECT_ROOT / "skills" / "finnhub-tool-selection" / "references" / "endpoint-argument-map.md",
    PROJECT_ROOT / "skills" / "finnhub-tool-selection" / "references" / "few-shot-examples.md",
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


@lru_cache(maxsize=1)
def finnhub_tool_selection_instructions() -> str:
    parts = [_read_text(FINNHUB_TOOL_SELECTION_SKILL)]
    parts.extend(_read_text(path) for path in FINNHUB_TOOL_SELECTION_REFERENCES)
    text = "\n\n".join(part for part in parts if part.strip()).strip()
    if text:
        return text
    return (
        "Select exactly one Finnhub tool. Use basic_financials for valuation metrics, "
        "stock_price for current quote, stock_candles for trend, company_news for "
        "company-specific news, analyst_recommendations for analyst ratings, and "
        "price_target for target price."
    )


FINNHUB_ROUTER_PROMPT = """
You are a Finnhub tool router for a financial RAG system.
Follow the Finnhub tool-selection skill exactly.
Return only the structured route requested by the schema.

{skill_instructions}
""".strip()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_limit(limit: int, default: int = 5, max_limit: int = 20) -> int:
    if limit <= 0:
        return default
    return min(limit, max_limit)


def safe_days(days: int, default: int = 7, max_days: int = 365) -> int:
    if days <= 0:
        return default
    return min(days, max_days)


def selected_mcp_provider() -> str:
    return (os.getenv("FINNHUB_MCP_PROVIDER") or "native").strip().lower()


def finnhub_client() -> Optional[finnhub.Client]:
    api_key = os.getenv("FINNHUB_API_KEY") or os.getenv("FINN_HUB_API")
    if not api_key:
        return None
    return finnhub.Client(api_key=api_key)


@lru_cache(maxsize=1)
def build_finnhub_router_chain():
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", FINNHUB_ROUTER_PROMPT),
            ("human", "Question: {question}\nSymbol: {symbol}"),
        ]
    )
    model = os.getenv("FINNHUB_ROUTER_MODEL", os.getenv("ROUTER_MODEL", "gpt-4.1-mini"))
    llm = ChatOpenAI(model=model, temperature=0)
    return prompt | llm.with_structured_output(FinnhubToolRoute)


def _resolve_symbol_with_finnhub(company_or_query: str) -> str:
    client = finnhub_client()
    if client is None:
        return ""
    try:
        result = client.symbol_lookup(company_or_query)
    except Exception:
        return ""
    for item in result.get("result", []):
        symbol = (item.get("symbol") or "").upper()
        if symbol and "." not in symbol:
            return symbol
    return ""


def route_finnhub_tool(question: str, symbol: str) -> FinnhubToolRoute:
    default_route = FinnhubToolRoute(tool_name="stock_price", symbol=symbol or "")
    lower = question.lower()
    if symbol and any(term in lower for term in ("pe", "p/e", "pb", "p/b", "ps", "p/s", "eps", "valuation", "market cap", "市盈率", "市净率", "估值", "每股收益", "市值")):
        return FinnhubToolRoute(
            tool_name="basic_financials",
            symbol=symbol,
            lookback_days=7,
            limit=5,
            reason="valuation or market metric query",
            fallback_tools=["company_profile", "stock_price"],
        )
    if symbol and any(term in lower for term in ("price target", "target price", "analyst target", "目标价")):
        return FinnhubToolRoute(
            tool_name="price_target",
            symbol=symbol,
            lookback_days=30,
            limit=5,
            reason="analyst target price query",
            fallback_tools=["analyst_recommendations"],
        )
    if symbol and any(term in lower for term in ("recommendation", "rating", "analyst view", "analyst", "评级", "分析师", "买入", "卖出", "持有")):
        return FinnhubToolRoute(
            tool_name="analyst_recommendations",
            symbol=symbol,
            lookback_days=30,
            limit=5,
            reason="analyst recommendation query",
            fallback_tools=["price_target"],
        )
    if symbol and any(term in lower for term in ("news", "headline", "消息", "新闻", "消息面", "事件")):
        return FinnhubToolRoute(
            tool_name="company_news",
            symbol=symbol,
            lookback_days=14,
            limit=10,
            reason="company-specific news query",
            fallback_tools=["news_sentiment", "market_news"],
        )
    if symbol and any(term in lower for term in ("sentiment", "情绪", "舆情")):
        return FinnhubToolRoute(
            tool_name="news_sentiment",
            symbol=symbol,
            lookback_days=14,
            limit=5,
            reason="company news sentiment query",
            fallback_tools=["company_news"],
        )
    if symbol and any(term in lower for term in ("trend", "走势", "k线", "k-line", "chart", "历史价格", "recent performance")):
        return FinnhubToolRoute(
            tool_name="stock_candles",
            symbol=symbol,
            lookback_days=30,
            limit=10,
            reason="price trend or candle query",
            fallback_tools=["stock_price"],
        )
    if symbol and any(term in lower for term in ("rsi", "macd", "sma", "technical", "技术指标")):
        indicator = "macd" if "macd" in lower else "sma" if "sma" in lower else "rsi"
        return FinnhubToolRoute(
            tool_name="technical_indicator",
            symbol=symbol,
            indicator=indicator,
            lookback_days=30,
            limit=10,
            reason="technical indicator query",
            fallback_tools=["stock_candles"],
        )
    if symbol and any(term in lower for term in ("profile", "company intro", "industry", "公司介绍", "行业", "交易所")):
        return FinnhubToolRoute(
            tool_name="company_profile",
            symbol=symbol,
            lookback_days=7,
            limit=5,
            reason="company profile query",
            fallback_tools=["stock_price"],
        )
    try:
        route = build_finnhub_router_chain().invoke(
            {
                "skill_instructions": finnhub_tool_selection_instructions(),
                "question": question,
                "symbol": symbol or "",
            }
        )
    except Exception:
        return default_route

    if FINNHUB_TOOLS[route.tool_name]["need_symbol"] and not route.symbol and symbol:
        route.symbol = symbol
    route.limit = safe_limit(route.limit)
    route.lookback_days = safe_days(route.lookback_days)
    return route


def tool_result_to_text(value: Any) -> str:
    content = getattr(value, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False, default=str))
            else:
                text = getattr(item, "text", None)
                if text is not None:
                    parts.append(str(text))
                else:
                    parts.append(str(item))
        return "\n".join(parts)
    structured = getattr(value, "structuredContent", None)
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False, default=str)
    return json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value



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


def _coerce_payload_dict(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    text = tool_result_to_text(payload)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _payload_headline(route: FinnhubToolRoute, payload: Any) -> str:
    if route.tool_name != "basic_financials":
        return ""
    payload_dict = _coerce_payload_dict(payload)
    metrics = payload_dict.get("metric") or {}
    if not isinstance(metrics, dict):
        return ""
    lines = ["# Key Finnhub metrics"]
    for key in BASIC_FINANCIAL_KEYS:
        value = metrics.get(key)
        if value not in (None, "", [], {}):
            lines.append(f"{key}: {value}")
    return "\n".join(lines) if len(lines) > 1 else ""
def to_finnhub_document(
    route: FinnhubToolRoute,
    payload: Any,
    question: str,
    retrieval_source: str,
    source_prefix: str,
) -> Optional[Document]:
    if payload is None:
        return None

    tool_meta = FINNHUB_TOOLS[route.tool_name]
    body = payload[: route.limit] if isinstance(payload, list) else payload
    text = tool_result_to_text(body)
    headline = _payload_headline(route, payload)
    if headline:
        text = headline + "\n\n# Raw Finnhub payload\n" + text
    if not text or text.strip() in {"[]", "{}"}:
        return None

    return Document(
        page_content=(
            f"{retrieval_source} tool={route.tool_name} endpoint={tool_meta['endpoint']} "
            f"desc={tool_meta['desc']} question={question}\nresult={text}"
        ),
        metadata={
            "source": f"{source_prefix}_{route.tool_name}",
            "symbol": (route.symbol or "").upper(),
            "tool_name": route.tool_name,
            "endpoint": tool_meta["endpoint"],
            "timestamp": utc_now_iso(),
            "retrieval_source": retrieval_source,
            "mcp_provider": selected_mcp_provider(),
            "route_reason": route.reason,
            "fallback_tools": route.fallback_tools,
        },
    )


def _call_selected_provider(question: str, symbol: str) -> Optional[Document]:
    provider = selected_mcp_provider()
    errors = []
    if provider == "git":
        try:
            from nodes.retrieval.finnhub_git import call_git_finnhub

            return call_git_finnhub(question, symbol)
        except Exception as exc:
            errors.append(f"git provider failed: {type(exc).__name__}: {exc}")
    elif provider == "pipedream":
        try:
            from nodes.retrieval.finnhub_pipedream import call_pipedream_finnhub

            return call_pipedream_finnhub(question, symbol)
        except Exception as exc:
            errors.append(f"pipedream provider failed: {type(exc).__name__}: {exc}")

    try:
        from nodes.retrieval.finnhub_native import call_native_finnhub

        doc = call_native_finnhub(question, symbol)
        if doc is not None:
            if errors:
                doc.metadata["provider_fallback_reason"] = " | ".join(errors[-2:])
                doc.metadata["mcp_provider_used"] = "native"
            return doc
    except Exception as exc:
        errors.append(f"native provider failed: {type(exc).__name__}: {exc}")
    if errors:
        raise RuntimeError(" | ".join(errors[-3:]))
    return None


def finnhub_mcp_node(state):
    question = state.get("active_question") or state["question"]
    symbol = (state.get("symbol") or "").upper()
    if not symbol:
        symbol = _resolve_symbol_with_finnhub(question)

    retrieval_path = list(state.get("retrieval_path", []))
    retrieval_path.append("finnhub_mcp")

    failures = list(state.get("retrieval_failures", []))
    try:
        doc = _call_selected_provider(question=question, symbol=symbol)
    except Exception as exc:
        failures.append(f"finnhub_mcp({symbol or 'unknown'}): {type(exc).__name__}: {exc}")
        doc = None
    if doc is None:
        failures.append(f"finnhub_mcp({symbol or 'unknown'}): no document returned")

    docs = [doc] if doc else []
    success = bool(docs)
    evidence = [
        document_to_evidence(
            item,
            source_type="finnhub",
            source_name="Finnhub MCP",
            default_score=1.0,
        )
        for item in docs
    ]
    provider = selected_mcp_provider()
    source_label = {
        "git": "Git Finnhub MCP",
        "pipedream": "Pipedream Finnhub MCP",
    }.get(provider, "Finnhub MCP")
    return {
        "documents": docs,
        "evidence_candidates": extend_evidence(state, evidence),
        "symbol": symbol,
        "api_failed": not success,
        "web_search": "No" if success else "Yes",
        "active_question": question,
        "last_action": "finnhub_mcp",
        "status": "success" if success else "fallback",
        "retrieval_source": source_label if success else "",
        "retrieval_score": 1.0 if success else 0.0,
        "retrieval_path": retrieval_path,
        "retrieval_failures": failures,
        "retrieval": {
            "evidence_candidates": extend_evidence(state, evidence),
            "retrieval_source": source_label if success else "",
            "retrieval_score": 1.0 if success else 0.0,
            "retrieval_path": retrieval_path,
            "retrieval_failures": failures,
        },
    }
