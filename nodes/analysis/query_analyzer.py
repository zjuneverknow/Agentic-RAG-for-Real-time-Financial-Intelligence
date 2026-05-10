from __future__ import annotations

import re
import time
from typing import Any, Dict, List

from nodes.analysis.entity_resolver import extract_explicit_symbol, resolve_entities, resolve_entity
from nodes.analysis.local_semantic_analyzer import analyze_semantics
from nodes.analysis.query_analyzer_validator import build_evidence_needs, build_source_requirements, build_sub_questions, dedupe, merge_intent, validate_entity
from observability.run_store import new_run_id
from observability.trace import append_trace, make_trace_event

A_SHARE_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")

TERMS = {
    "q1": ("\u4e00\u5b63\u5ea6", "Q1", "1Q", "first quarter"),
    "half_year": ("\u534a\u5e74\u5ea6", "H1", "half year"),
    "q3": ("\u4e09\u5b63\u5ea6", "Q3", "3Q", "third quarter"),
    "annual": ("\u5e74\u62a5", "annual", "10-K", "annual report"),
    "revenue": ("\u8425\u4e1a\u6536\u5165", "revenue", "sales"),
    "net_profit": ("\u51c0\u5229\u6da6", "net profit", "net income"),
    "attributable_net_profit": ("\u5f52\u6bcd", "\u5f52\u5c5e\u4e8e\u4e0a\u5e02\u516c\u53f8\u80a1\u4e1c\u7684\u51c0\u5229\u6da6", "attributable net profit"),
}

METRIC_NAMES = {
    "revenue": "\u8425\u4e1a\u6536\u5165",
    "net_profit": "\u51c0\u5229\u6da6",
    "attributable_net_profit": "\u5f52\u6bcd\u51c0\u5229\u6da6",
}

MARKET_METRIC_ALIASES = {
    "pe": ("pe", "p/e", "\u5e02\u76c8\u7387"),
    "pb": ("pb", "p/b", "\u5e02\u51c0\u7387"),
    "ps": ("ps", "p/s", "\u5e02\u9500\u7387"),
    "eps": ("eps", "\u6bcf\u80a1\u6536\u76ca"),
    "price": ("price", "\u80a1\u4ef7", "\u4ef7\u683c"),
    "market_cap": ("market cap", "\u5e02\u503c"),
    "valuation": ("valuation", "\u4f30\u503c", "\u8d35\u4e0d\u8d35", "\u9ad8\u4f30", "\u4f4e\u4f30"),
    "trend": ("trend", "chart", "technical", "k-line", "kline", "\u8d70\u52bf", "\u8d8b\u52bf", "\u6280\u672f\u6307\u6807", "k\u7ebf"),
}

FRESH_HINTS = ("latest", "current", "today", "now", "recent", "\u6700\u65b0", "\u5f53\u524d", "\u4eca\u5929", "\u8fd1\u671f", "\u73b0\u5728")


def _contains_any(text: str, terms) -> bool:
    lower = text.lower()
    return any(str(term).lower() in lower for term in terms)


def _extract_metrics(question: str) -> List[str]:
    metrics: List[str] = []
    for key, terms in TERMS.items():
        if key in METRIC_NAMES and _contains_any(question, terms):
            metrics.append(METRIC_NAMES[key])
    metrics = dedupe(metrics)
    if "\u5f52\u6bcd\u51c0\u5229\u6da6" in metrics and "\u51c0\u5229\u6da6" in metrics and "\u5f52\u6bcd" in question:
        metrics = [metric for metric in metrics if metric != "\u51c0\u5229\u6da6"]
    return metrics


def _extract_market_metrics(question: str) -> List[str]:
    found: List[str] = []
    for key, aliases in MARKET_METRIC_ALIASES.items():
        if _contains_any(question, aliases):
            found.append(key)
    return dedupe(found)


def _extract_year(question: str) -> str:
    match = re.search(r"(?<!\d)(20\d{2})(?!\d)", question)
    return match.group(1) if match else ""


def _extract_period(question: str) -> str:
    for key in ("q1", "half_year", "q3", "annual"):
        if _contains_any(question, TERMS[key]):
            return key
    return ""


def _lexical_analyze(question: str) -> Dict[str, Any]:
    code_match = A_SHARE_CODE_PATTERN.search(question)
    return {
        "code": code_match.group(1) if code_match else "",
        "symbol": extract_explicit_symbol(question),
        "year": _extract_year(question),
        "period": _extract_period(question),
        "metrics": _extract_metrics(question),
        "market_metrics": _extract_market_metrics(question),
        "requires_freshness": _contains_any(question, FRESH_HINTS),
    }


def _merge_metrics(lexical: Dict[str, Any], semantic: Dict[str, Any]) -> List[str]:
    semantic_metrics = [str(item) for item in (semantic.get("metrics") or [])]
    allowed = set(METRIC_NAMES.values())
    return dedupe(list(lexical.get("metrics") or []) + [item for item in semantic_metrics if item in allowed])


def _merge_market_metrics(lexical: Dict[str, Any], semantic: Dict[str, Any]) -> List[str]:
    semantic_metrics = [str(item).lower() for item in (semantic.get("market_metrics") or [])]
    return dedupe(list(lexical.get("market_metrics") or []) + semantic_metrics)


def query_analyzer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    question = state.get("active_question") or state.get("original_question") or state.get("question", "")
    lexical = _lexical_analyze(question)
    semantic = analyze_semantics(question, lexical)
    entity_list = [validate_entity(item) for item in resolve_entities(question, lexical, semantic)]
    entity = entity_list[0] if entity_list else validate_entity(resolve_entity(question, lexical, semantic))
    identifiers = entity.get("identifiers") or {}
    symbols = [
        str((item.get("identifiers") or {}).get("symbol") or "").upper()
        for item in entity_list
        if (item.get("identifiers") or {}).get("symbol")
    ]
    codes = [
        str((item.get("identifiers") or {}).get("code") or (item.get("identifiers") or {}).get("cn_code") or "")
        for item in entity_list
        if (item.get("identifiers") or {}).get("code") or (item.get("identifiers") or {}).get("cn_code")
    ]

    metrics = _merge_metrics(lexical, semantic)
    market_metrics = _merge_market_metrics(lexical, semantic)
    provisional_sub_questions = build_sub_questions(question, metrics + market_metrics, semantic, str(semantic.get("intent") or "fact"))
    intent = merge_intent(question, lexical, semantic, provisional_sub_questions)
    sub_questions = build_sub_questions(question, metrics + market_metrics, semantic, intent)
    evidence_needs = build_evidence_needs(question, metrics, market_metrics, entity_list, semantic)
    source_requirements = build_source_requirements(question, metrics, market_metrics, entity, semantic, entity_list, evidence_needs)

    code = str(identifiers.get("code") or identifiers.get("cn_code") or lexical.get("code") or "")
    symbol = str(identifiers.get("symbol") or lexical.get("symbol") or "")
    company = str(entity.get("display_name") or entity.get("company") or "")
    year = str(lexical.get("year") or "")
    period = str(lexical.get("period") or "")
    requires_freshness = bool(lexical.get("requires_freshness") or source_requirements.get("needs_fresh_market_data") or source_requirements.get("needs_news"))

    entities = {
        "company": company,
        "code": code,
        "symbol": symbol,
        "symbols": symbols,
        "codes": codes,
        "entity_list": entity_list,
        "year": year,
        "period": period,
        "metrics": metrics,
        "market_metrics": market_metrics,
        "entity": entity,
        "identifiers": identifiers,
        "entity_type": entity.get("entity_type", ""),
    }
    run_id = state.get("run_id") or new_run_id()
    query = {
        "original_question": state.get("original_question") or state.get("question", question),
        "active_question": question,
        "sub_questions": sub_questions,
        "intent": intent,
        "entities": entities,
        "entity": entity,
        "source_requirements": source_requirements,
        "evidence_needs": evidence_needs,
        "symbol": symbol or code,
        "symbols": symbols or ([symbol] if symbol else []),
        "codes": codes or ([code] if code else []),
        "code": code,
        "company": company,
        "metrics": metrics,
        "market_metrics": market_metrics,
        "time_range": {"year": year, "period": period},
        "requires_freshness": requires_freshness,
        "analysis": {"lexical": lexical, "semantic": semantic, "entity_resolution": entity},
    }
    event = make_trace_event(
        "query_analyzer",
        started_at=started,
        input_summary={"question": question},
        output_summary={
            "intent": intent,
            "sub_questions": len(sub_questions),
            "requirements": source_requirements,
            "evidence_needs": evidence_needs,
            "entities": entities,
            "semantic_enabled": bool(semantic.get("enabled")),
            "semantic_error": semantic.get("error", ""),
            "skill_loaded": bool(semantic.get("skill_loaded")),
        },
    )
    return {
        "run_id": run_id,
        "query": query,
        "original_question": query["original_question"],
        "active_question": question,
        "sub_questions": sub_questions,
        "intent": intent,
        "entities": entities,
        "entity": entity,
        "source_requirements": source_requirements,
        "evidence_needs": evidence_needs,
        "symbol": query["symbol"],
        "code": code,
        "company": company,
        "metrics": metrics,
        "market_metrics": market_metrics,
        "time_range": query["time_range"],
        "requires_freshness": requires_freshness,
        "trace_events": append_trace(state, event),
        "control": {**(state.get("control") or {}), "run_id": run_id, "last_action": "query_analyzer"},
        "last_action": "query_analyzer",
    }
