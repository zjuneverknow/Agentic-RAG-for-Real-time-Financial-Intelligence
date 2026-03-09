import json
import os
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional, Tuple

import finnhub
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pydantic import BaseModel, Field


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
    indicator: str = Field(default="rsi", description="For technical indicator tool, like rsi/sma/macd.")
    market: str = Field(default="US", description="For stock_symbols tool.")
    category: str = Field(default="general", description="For market_news tool.")
    lookback_days: int = Field(default=7, description="Lookback days for date-range APIs.")
    limit: int = Field(default=5, description="Top-N rows to keep in document.")


FINNHUB_ROUTER_PROMPT = """
You are a Finnhub tool router.
Pick exactly one tool_name from the allowed list and fill minimal parameters.

Allowed tool_name values:
stock_price, stock_candles, company_profile, company_peers, basic_financials,
financial_statements, earnings_history, earnings_calendar, stock_dividends,
analyst_recommendations, price_target, upgrade_downgrade, insider_transactions,
institutional_ownership, company_news, market_news, news_sentiment,
technical_indicator, stock_symbols, stock_search.

Rules:
1) Current/latest stock price -> stock_price.
2) Trend/K-line/history chart -> stock_candles.
3) Company intro/industry -> company_profile.
4) Competitors -> company_peers.
5) PE/PB/valuation metrics -> basic_financials.
6) Financial report details -> financial_statements.
7) EPS/earnings history -> earnings_history.
8) Upcoming earnings calendar -> earnings_calendar.
9) Dividends -> stock_dividends.
10) Analyst view/rating -> analyst_recommendations.
11) Price target -> price_target.
12) Upgrade/downgrade events -> upgrade_downgrade.
13) Insider buy/sell -> insider_transactions.
14) Institutional holders/funds -> institutional_ownership.
15) Company latest news -> company_news.
16) Broad market headlines -> market_news.
17) Sentiment of company news -> news_sentiment.
18) RSI/MACD/SMA -> technical_indicator.
19) Ask stock list by market -> stock_symbols.
20) Ask which ticker for a company -> stock_search.
""".strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pinecone_store() -> PineconeVectorStore:
    return PineconeVectorStore(
        index_name=os.getenv("PINECONE_INDEX_NAME", "financial-rag"),
        embedding=OpenAIEmbeddings(model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")),
    )


def _pinecone_search(question: str, symbol: str) -> Tuple[List[Document], float]:
    store = _pinecone_store()
    k = int(os.getenv("TOP_K", "6"))
    threshold = float(os.getenv("PINECONE_RELEVANCE_THRESHOLD", "0.65"))
    filter_kwargs = {"symbol": symbol} if symbol else None
    results = store.similarity_search_with_relevance_scores(question, k=k, filter=filter_kwargs)
    strong_docs = [doc for doc, score in results if score >= threshold]
    max_score = max([score for _, score in results], default=0.0)
    return strong_docs, max_score


def _upsert_to_pinecone(docs: List[Document]) -> None:
    if not docs:
        return
    _pinecone_store().add_documents(docs)


def _finnhub_client() -> Optional[finnhub.Client]:
    api_key = os.getenv("FINN_HUB_API")
    if not api_key:
        return None
    return finnhub.Client(api_key=api_key)


@lru_cache(maxsize=1)
def _build_finnhub_router_chain():
    prompt = ChatPromptTemplate.from_messages(
        [("system", FINNHUB_ROUTER_PROMPT), ("human", "Question: {question}\nSymbol: {symbol}")]
    )
    model = os.getenv("FINNHUB_ROUTER_MODEL", os.getenv("ROUTER_MODEL", "gpt-4.1-mini"))
    llm = ChatOpenAI(model=model, temperature=0)
    return prompt | llm.with_structured_output(FinnhubToolRoute)


def _resolve_symbol_with_finnhub(company_or_query: str) -> str:
    client = _finnhub_client()
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


def _safe_limit(limit: int, default: int = 5, max_limit: int = 20) -> int:
    if limit <= 0:
        return default
    return min(limit, max_limit)


def _safe_days(days: int, default: int = 7, max_days: int = 365) -> int:
    if days <= 0:
        return default
    return min(days, max_days)


def _route_finnhub_tool(question: str, symbol: str) -> FinnhubToolRoute:
    default_route = FinnhubToolRoute(tool_name="stock_price", symbol=symbol or "")
    try:
        route = _build_finnhub_router_chain().invoke({"question": question, "symbol": symbol or ""})
    except Exception:
        return default_route

    if FINNHUB_TOOLS[route.tool_name]["need_symbol"] and not route.symbol and symbol:
        route.symbol = symbol
    route.limit = _safe_limit(route.limit)
    route.lookback_days = _safe_days(route.lookback_days)
    return route


def _call_finnhub_tool(client: finnhub.Client, route: FinnhubToolRoute, question: str) -> Any:
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


def _to_finnhub_document(route: FinnhubToolRoute, payload: Any, question: str) -> Optional[Document]:
    if payload is None:
        return None
    tool_meta = FINNHUB_TOOLS[route.tool_name]
    body = payload
    if isinstance(payload, list):
        body = payload[: route.limit]
    text = json.dumps(body, ensure_ascii=False, default=str)
    if not text or text in {"[]", "{}"}:
        return None
    return Document(
        page_content=(
            f"Finnhub tool={route.tool_name} endpoint={tool_meta['endpoint']} "
            f"desc={tool_meta['desc']} question={question}\nresult={text}"
        ),
        metadata={
            "source": f"finnhub_{route.tool_name}",
            "symbol": (route.symbol or "").upper(),
            "tool_name": route.tool_name,
            "endpoint": tool_meta["endpoint"],
            "timestamp": _utc_now_iso(),
        },
    )


def _finnhub_realtime_docs(symbol: str, question: str) -> Tuple[List[Document], bool]:
    client = _finnhub_client()
    if client is None:
        return [], True

    route = _route_finnhub_tool(question=question, symbol=symbol)
    if FINNHUB_TOOLS[route.tool_name]["need_symbol"] and not route.symbol:
        return [], True

    debug_flag = (os.getenv("DEBUG_ROUTING") or "").strip().lower()
    if debug_flag in {"1", "true", "yes", "on"}:
        print(f"[finnhub_router] tool={route.tool_name} symbol={route.symbol!r} question={question!r}", flush=True)

    try:
        payload = _call_finnhub_tool(client, route, question)
        doc = _to_finnhub_document(route, payload, question)
        if doc is None:
            return [], False
        return [doc], False
    except Exception:
        return [], True


def retrieve_node(state):
    question = state.get("active_question") or state["question"]
    symbol = (state.get("symbol") or "").upper()
    datasource = state.get("datasource", "vector_store")

    if datasource != "vector_store":
        return {"documents": state.get("documents", []), "symbol": symbol, "api_failed": False}

    if not symbol:
        symbol = _resolve_symbol_with_finnhub(question)

    docs: List[Document] = []
    api_failed = False
    try:
        docs, top_score = _pinecone_search(question, symbol)
    except Exception:
        docs = []
        top_score = 0.0

    min_docs = int(os.getenv("MIN_RELEVANT_DOCS", "2"))
    quality_threshold = float(os.getenv("RELIABILITY_THRESHOLD", "0.75"))
    needs_api_fallback = (len(docs) < min_docs) or (top_score < quality_threshold)
    if needs_api_fallback:
        finnhub_docs, api_failed = _finnhub_realtime_docs(symbol=symbol, question=question)
        if finnhub_docs:
            _upsert_to_pinecone(finnhub_docs)
            docs.extend(finnhub_docs)

    web_search = "Yes" if api_failed else "No"
    return {
        "documents": docs,
        "symbol": symbol,
        "api_failed": api_failed,
        "web_search": web_search,
        "active_question": question,
    }
