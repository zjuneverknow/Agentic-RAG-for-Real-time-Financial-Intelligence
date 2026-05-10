from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SourceSpec:
    name: str
    tool: str
    source: str
    purpose: str
    capabilities: tuple[str, ...]
    authority: float
    freshness: str
    coverage: Dict[str, tuple[str, ...]]
    enabled: bool = True
    optional_by_default: bool = False


SOURCE_REGISTRY: Dict[str, SourceSpec] = {
    "milvus_filings": SourceSpec(
        name="milvus_filings",
        tool="milvus_financial_search",
        source="milvus",
        purpose="document-grounded filing, announcement, report, transcript, and internal evidence",
        capabilities=("filing_evidence", "document_evidence", "internal_docs", "historical_context"),
        authority=1.0,
        freshness="filing",
        coverage={"markets": ("CN",), "asset_types": ("stock",), "identifier_types": ("code", "cn_code")},
    ),
    "finnhub_market": SourceSpec(
        name="finnhub_market",
        tool="source_api",
        source="source_api",
        purpose="fresh structured market data and valuation metrics",
        capabilities=("fresh_market_data", "structured_metrics", "valuation", "profile", "market_index_data", "price_trend", "technical_indicator", "news", "fresh_public_context"),
        authority=0.85,
        freshness="realtime",
        coverage={"markets": ("US", "HK", "GLOBAL"), "asset_types": ("stock", "etf", "index", "crypto", "forex"), "identifier_types": ("symbol",)},
    ),
    "web_search": SourceSpec(
        name="web_search",
        tool="web_search",
        source="web_search",
        purpose="breaking news, policy, macro, and public corroboration",
        capabilities=("news", "policy", "macro", "fresh_public_context"),
        authority=0.6,
        freshness="realtime",
        coverage={"markets": ("*",), "asset_types": ("*",), "identifier_types": ("symbol", "code", "cn_code", "none")},
        optional_by_default=True,
    ),
    # Future slots. Disabled now, but planner can target these capabilities later.
    "sec_companyfacts": SourceSpec(
        name="sec_companyfacts",
        tool="sec_companyfacts",
        source="milvus",
        purpose="SEC structured company facts",
        capabilities=("structured_metrics", "filing_evidence", "us_sec"),
        authority=0.95,
        freshness="filing",
        coverage={"markets": ("US",), "asset_types": ("stock",), "identifier_types": ("symbol", "sec_cik")},
        enabled=False,
    ),
    "news_cache": SourceSpec(
        name="news_cache",
        tool="news_cache_search",
        source="milvus",
        purpose="indexed news cache",
        capabilities=("news", "fresh_public_context"),
        authority=0.7,
        freshness="near_realtime",
        coverage={"markets": ("*",), "asset_types": ("*",), "identifier_types": ("symbol", "code", "cn_code", "none")},
        enabled=False,
    ),
    "internal_research": SourceSpec(
        name="internal_research",
        tool="internal_research_search",
        source="milvus",
        purpose="internal research notes and watchlists",
        capabilities=("internal_docs", "document_evidence"),
        authority=0.75,
        freshness="internal",
        coverage={"markets": ("*",), "asset_types": ("*",), "identifier_types": ("symbol", "code", "cn_code", "none")},
        enabled=False,
    ),
}


NEED_TYPE_TO_CAPABILITY = {
    "filing_fact": "filing_evidence",
    "document_evidence": "document_evidence",
    "live_market_data": "fresh_market_data",
    "valuation_metric": "valuation",
    "structured_metric": "structured_metrics",
    "company_profile": "profile",
    "price_trend": "price_trend",
    "technical_indicator": "technical_indicator",
    "market_index_data": "market_index_data",
    "news_event": "news",
    "policy_context": "policy",
    "macro_context": "macro",
    "internal_docs": "internal_docs",
}


REQUIREMENT_TO_CAPABILITY = {
    "needs_filing_evidence": "filing_evidence",
    "needs_document_evidence": "document_evidence",
    "needs_fresh_market_data": "fresh_market_data",
    "needs_structured_metrics": "structured_metrics",
    "needs_news": "news",
    "needs_policy_context": "policy",
    "needs_macro_context": "macro",
    "needs_internal_docs": "internal_docs",
    "needs_market_index_data": "market_index_data",
    "needs_price_trend": "price_trend",
    "needs_technical_indicator": "technical_indicator",
}


def select_sources(requirements: Dict[str, Any]) -> List[SourceSpec]:
    needed = [cap for key, cap in REQUIREMENT_TO_CAPABILITY.items() if requirements.get(key)]
    selected: List[SourceSpec] = []
    for cap in needed:
        for spec in SOURCE_REGISTRY.values():
            if not spec.enabled:
                continue
            if cap in spec.capabilities and spec not in selected:
                selected.append(spec)
                break
    if not selected and requirements.get("needs_answer"):
        selected.append(SOURCE_REGISTRY["web_search"])
    return selected


def _matches_one(value: str, accepted: tuple[str, ...]) -> bool:
    normalized = (value or "").upper()
    return "*" in accepted or not accepted or normalized in {item.upper() for item in accepted}


def _identifier_types(identifiers: Dict[str, Any]) -> List[str]:
    found = [key for key in ("symbol", "code", "cn_code", "sec_cik", "isin") if identifiers.get(key)]
    return found or ["none"]


def source_supports_need(spec: SourceSpec, need: Dict[str, Any]) -> bool:
    if not spec.enabled:
        return False
    capability = NEED_TYPE_TO_CAPABILITY.get(str(need.get("need_type") or ""), str(need.get("need_type") or ""))
    if capability not in spec.capabilities:
        return False

    entity = need.get("entity") or {}
    identifiers = need.get("identifiers") or (entity.get("identifiers") or {})
    market = str(identifiers.get("market") or need.get("market") or "").upper()
    asset_type = str(identifiers.get("asset_type") or need.get("asset_type") or "").lower()
    coverage = spec.coverage or {}

    if not _matches_one(market, coverage.get("markets", ())):
        return False
    if not _matches_one(asset_type, coverage.get("asset_types", ())):
        return False
    accepted_ids = coverage.get("identifier_types", ())
    return any(identifier_type in accepted_ids or "*" in accepted_ids for identifier_type in _identifier_types(identifiers))


def select_source_for_need(need: Dict[str, Any]) -> Optional[SourceSpec]:
    candidates = [spec for spec in SOURCE_REGISTRY.values() if source_supports_need(spec, need)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda spec: (spec.optional_by_default, -spec.authority))[0]


def _args_for_need(base_args: Dict[str, Any], need: Dict[str, Any]) -> Dict[str, Any]:
    entity = need.get("entity") or {}
    identifiers = need.get("identifiers") or (entity.get("identifiers") or {})
    symbol = str(identifiers.get("symbol") or "").upper()
    code = str(identifiers.get("code") or identifiers.get("cn_code") or "")
    company = str(entity.get("display_name") or entity.get("company") or need.get("entity_name") or "")
    question = str(need.get("query") or base_args.get("query") or "")
    args = dict(base_args)
    args.update(
        {
            "active_question": question,
            "entity": entity,
            "identifiers": identifiers,
            "company": company,
            "symbol": symbol,
            "code": code,
            "evidence_need": need,
            "current_tool_args": {
                "entity": entity,
                "identifiers": identifiers,
                "company": company,
                "symbol": symbol,
                "code": code,
                "question": question,
                "need_type": need.get("need_type", ""),
                "fields": need.get("fields", []),
            },
        }
    )
    return args


def build_tool_plan(requirements: Dict[str, Any], args: Dict[str, Any], evidence_needs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    plan = []
    if evidence_needs:
        for need in evidence_needs:
            spec = select_source_for_need(need)
            if spec is None:
                continue
            plan.append({
                "tool": spec.tool,
                "source": spec.source,
                "purpose": spec.purpose,
                "args": _args_for_need(args, need),
                "optional": spec.optional_by_default,
                "source_name": spec.name,
                "authority": spec.authority,
                "freshness": spec.freshness,
                "evidence_need": need,
            })
        if plan:
            return plan

    for spec in select_sources(requirements):
        plan.append({
            "tool": spec.tool,
            "source": spec.source,
            "purpose": spec.purpose,
            "args": dict(args),
            "optional": spec.optional_by_default,
            "source_name": spec.name,
            "authority": spec.authority,
            "freshness": spec.freshness,
        })
    return plan
