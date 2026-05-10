from __future__ import annotations

from typing import Any, Dict, List

SUMMARY_HINTS = ("\u603b\u7ed3", "\u5f52\u7eb3", "\u6982\u62ec", "\u68b3\u7406", "\u7efc\u8ff0", "\u6574\u7406", "summary", "summarize", "recap", "overview")
COMPARE_HINTS = ("compare", "vs", "versus", "\u5bf9\u6bd4", "\u6bd4\u8f83", "\u76f8\u6bd4")
REASON_HINTS = ("why", "reason", "impact", "risk", "\u600e\u4e48\u770b", "\u4e3a\u4ec0\u4e48", "\u539f\u56e0", "\u5f71\u54cd", "\u98ce\u9669", "\u8d35\u4e0d\u8d35", "\u9ad8\u4f30", "\u4f4e\u4f30", "\u672a\u6765")
NEWS_HINTS = ("news", "headline", "policy", "macro", "recent", "\u6d88\u606f\u9762", "\u65b0\u95fb", "\u653f\u7b56", "\u5b8f\u89c2", "\u8fd1\u671f", "\u8206\u60c5", "\u60c5\u7eea")
FRESH_HINTS = ("latest", "current", "today", "now", "recent", "\u6700\u65b0", "\u5f53\u524d", "\u4eca\u5929", "\u8fd1\u671f", "\u73b0\u5728")
API_HINTS = ("api", "\u5b9e\u65f6", "\u7f8e\u80a1", "\u884c\u60c5", "\u80a1\u4ef7", "\u5173\u952e\u6570\u636e")
DOCUMENT_HINTS = ("\u8d22\u62a5", "\u5e74\u62a5", "\u5b63\u62a5", "\u516c\u544a", "\u62a5\u544a", "10-k", "10-q", "8-k", "filing", "annual report", "quarterly report", "transcript", "\u5229\u6da6\u8868", "\u8d44\u4ea7\u8d1f\u503a\u8868", "\u73b0\u91d1\u6d41\u91cf\u8868")
STRUCTURED_MARKET_HINTS = ("pe", "p/e", "pb", "p/b", "valuation", "market cap", "eps", "price", "trend", "technical", "chart", "\u4f30\u503c", "\u5e02\u76c8\u7387", "\u80a1\u4ef7", "\u8d70\u52bf", "\u8d8b\u52bf", "\u6280\u672f\u6307\u6807", "\u8d35\u4e0d\u8d35", "\u9ad8\u4f30", "\u4f4e\u4f30")
TREND_HINTS = ("trend", "technical", "chart", "k-line", "kline", "\u8d70\u52bf", "\u8d8b\u52bf", "\u6280\u672f\u6307\u6807", "k\u7ebf")

VALID_INTENTS = {"fact", "summary", "compare", "reasoning", "chat"}
RICH_INTENT_MAP = {
    "trend_analysis": "summary",
    "valuation_analysis": "reasoning",
    "risk_analysis": "reasoning",
    "news_monitoring": "summary",
}


def contains_any(text: str, terms) -> bool:
    lower = text.lower()
    return any(str(term).lower() in lower for term in terms)


def dedupe(values: List[str]) -> List[str]:
    return [item for item in dict.fromkeys(values) if item]


def merge_intent(question: str, lexical: Dict[str, Any], semantic: Dict[str, Any], sub_questions: List[Dict[str, Any]]) -> str:
    proposed = str((semantic or {}).get("intent") or "").lower().strip()
    if proposed in VALID_INTENTS and float((semantic or {}).get("confidence") or 0.0) >= 0.5:
        intent = proposed
    elif proposed in RICH_INTENT_MAP and float((semantic or {}).get("confidence") or 0.0) >= 0.5:
        intent = RICH_INTENT_MAP[proposed]
    else:
        intent = "fact"
    if not question.strip():
        return "chat"
    if contains_any(question, COMPARE_HINTS):
        return "compare"
    if contains_any(question, SUMMARY_HINTS):
        return "summary"
    if contains_any(question, REASON_HINTS):
        return "reasoning"
    return intent


def build_sub_questions(question: str, metrics: List[str], semantic: Dict[str, Any], intent: str) -> List[Dict[str, Any]]:
    semantic_items = [item for item in (semantic or {}).get("sub_questions") or [] if isinstance(item, dict) and item.get("question")]
    if semantic_items:
        return semantic_items
    items: List[Dict[str, Any]] = []
    if len(metrics) > 1:
        items.extend({"question": f"{question} -- {metric}", "focus": metric, "type": "metric_lookup"} for metric in metrics)
    if contains_any(question, TREND_HINTS):
        items.append({"question": f"{question} -- price trend", "focus": "price_trend", "type": "trend_analysis"})
    elif contains_any(question, STRUCTURED_MARKET_HINTS):
        items.append({"question": f"{question} -- valuation metrics", "focus": "valuation", "type": "metric_lookup"})
    if contains_any(question, NEWS_HINTS):
        items.append({"question": f"{question} -- news and sentiment", "focus": "news", "type": "news_summary"})
    if intent == "compare" and not items:
        items.append({"question": question, "focus": "comparison", "type": "comparison"})
    return items or [{"question": question, "focus": "main", "type": "single"}]


def _identifiers(entity: Dict[str, Any]) -> Dict[str, Any]:
    return dict(entity.get("identifiers") or {})


def _entity_name(entity: Dict[str, Any]) -> str:
    return str(entity.get("display_name") or entity.get("company") or "")


def build_evidence_needs(
    question: str,
    metrics: List[str],
    market_metrics: List[str],
    entity_list: List[Dict[str, Any]],
    semantic: Dict[str, Any],
) -> List[Dict[str, Any]]:
    semantic_needs = [item for item in (semantic or {}).get("evidence_needs") or [] if isinstance(item, dict)]
    if semantic_needs:
        return semantic_needs

    needs: List[Dict[str, Any]] = []
    wants_document = bool(metrics or contains_any(question, DOCUMENT_HINTS))
    wants_market = bool(market_metrics or contains_any(question, STRUCTURED_MARKET_HINTS) or contains_any(question, API_HINTS) or contains_any(question, FRESH_HINTS))
    wants_news = contains_any(question, NEWS_HINTS)
    wants_technical = contains_any(question, ("technical", "\u6280\u672f\u6307\u6807", "k-line", "kline", "k\u7ebf")) or "technical_indicator" in market_metrics
    wants_trend = contains_any(question, TREND_HINTS) or "trend" in market_metrics

    for entity in entity_list or []:
        identifiers = _identifiers(entity)
        name = _entity_name(entity)
        base = {
            "entity": entity,
            "entity_name": name,
            "identifiers": identifiers,
            "market": identifiers.get("market", ""),
            "asset_type": identifiers.get("asset_type", ""),
        }
        if wants_document or identifiers.get("code") or identifiers.get("cn_code"):
            needs.append({
                **base,
                "need_type": "filing_fact",
                "fields": metrics or ["key_filing_data"],
                "freshness": "latest_filing",
                "query": f"{name} filing report facts {question}".strip(),
            })
        if wants_market and (identifiers.get("symbol") or identifiers.get("code") or identifiers.get("cn_code")):
            need_type = "price_trend" if wants_trend else "technical_indicator" if wants_technical else "valuation_metric" if market_metrics else "live_market_data"
            needs.append({
                **base,
                "need_type": need_type,
                "fields": market_metrics or ["price", "change_percent"],
                "freshness": "realtime",
                "query": f"{name} live market data {question}".strip(),
            })
        if wants_news:
            needs.append({
                **base,
                "need_type": "news_event",
                "fields": ["news"],
                "freshness": "realtime",
                "query": f"{name} news {question}".strip(),
            })

    if not needs:
        if wants_news:
            needs.append({"need_type": "news_event", "fields": ["news"], "freshness": "realtime", "query": question, "entity": {}, "identifiers": {}})
        elif contains_any(question, ("policy", "\u653f\u7b56")):
            needs.append({"need_type": "policy_context", "fields": ["policy"], "freshness": "realtime", "query": question, "entity": {}, "identifiers": {}})
        elif contains_any(question, ("macro", "\u5b8f\u89c2")):
            needs.append({"need_type": "macro_context", "fields": ["macro"], "freshness": "realtime", "query": question, "entity": {}, "identifiers": {}})
    return needs


def build_source_requirements(
    question: str,
    metrics: List[str],
    market_metrics: List[str],
    entity: Dict[str, Any],
    semantic: Dict[str, Any],
    entity_list: List[Dict[str, Any]] | None = None,
    evidence_needs: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    identifiers = entity.get("identifiers") or {}
    symbol = identifiers.get("symbol") or ""
    semantic_req = dict((semantic or {}).get("source_requirements") or {})
    entity_type = entity.get("entity_type") or ""
    asset_type = identifiers.get("asset_type") or ""
    need_types = {str(item.get("need_type") or "") for item in (evidence_needs or [])}

    needs_document = "filing_fact" in need_types or "document_evidence" in need_types or bool(metrics or contains_any(question, DOCUMENT_HINTS))
    needs_structured_market = bool(need_types & {"live_market_data", "valuation_metric", "structured_metric", "price_trend", "technical_indicator", "market_index_data"})
    needs_market_index = entity_type == "market_index" or asset_type == "index"
    needs_price_trend = "price_trend" in need_types or contains_any(question, TREND_HINTS) or "trend" in market_metrics
    needs_technical_indicator = "technical_indicator" in need_types or contains_any(question, ("technical", "\u6280\u672f\u6307\u6807", "k-line", "kline", "k\u7ebf")) or "technical_indicator" in market_metrics
    needs_news = "news_event" in need_types or contains_any(question, NEWS_HINTS)

    requirements = {
        "needs_answer": True,
        "needs_filing_evidence": needs_document,
        "needs_document_evidence": needs_document,
        "needs_fresh_market_data": needs_structured_market or needs_market_index or needs_price_trend,
        "needs_structured_metrics": needs_structured_market or needs_market_index or needs_price_trend,
        "needs_news": needs_news,
        "needs_policy_context": "policy" in question.lower() or "\u653f\u7b56" in question,
        "needs_macro_context": "macro" in question.lower() or "\u5b8f\u89c2" in question,
        "needs_internal_docs": "memo" in question.lower() or "research note" in question.lower() or "\u7814\u62a5" in question,
        "needs_market_index_data": needs_market_index,
        "needs_price_trend": needs_price_trend,
        "needs_technical_indicator": needs_technical_indicator,
    }
    for key, value in semantic_req.items():
        if key in requirements and isinstance(value, bool):
            requirements[key] = requirements[key] or value
    if contains_any(question, SUMMARY_HINTS) and not (requirements["needs_document_evidence"] or requirements["needs_fresh_market_data"]):
        requirements["needs_news"] = requirements["needs_news"] or bool(symbol)
    if contains_any(question, REASON_HINTS) and (symbol or needs_structured_market):
        requirements["needs_structured_metrics"] = True
        requirements["needs_fresh_market_data"] = True
        requirements["needs_news"] = requirements["needs_news"] or contains_any(question, ("\u6d88\u606f", "\u65b0\u95fb", "\u5e02\u573a", "\u60c5\u7eea", "recent", "news"))
    return requirements


def validate_entity(entity: Dict[str, Any]) -> Dict[str, Any]:
    identifiers = dict(entity.get("identifiers") or {})
    symbol = str(identifiers.get("symbol") or "").upper()
    if symbol in {"PE", "PB", "PS", "EPS", "ROE", "ROA", "Q1", "Q2", "Q3", "Q4"}:
        identifiers["symbol"] = ""
    entity = dict(entity)
    entity["identifiers"] = identifiers
    return entity
