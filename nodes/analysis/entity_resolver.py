from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional

A_SHARE_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")
EXPLICIT_TICKER_PATTERNS = (
    re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)(?![A-Z])"),
    re.compile(r"\(([A-Z]{1,5}(?:\.[A-Z])?)\)"),
    re.compile(r"\b(?:ticker|symbol)\s*[:=]?\s*([A-Z]{1,5}(?:\.[A-Z])?)\b", re.IGNORECASE),
)
US_TICKER_PATTERN = re.compile(r"\b[A-Z]{1,5}(?:\.[A-Z])?\b")

TICKER_STOPWORDS = {
    "A", "AN", "AND", "ARE", "AS", "AT", "BY", "FOR", "FROM", "IN", "IS", "IT", "OF", "ON", "OR", "THE", "TO", "VS",
    "PE", "PB", "PS", "PEG", "EPS", "ROE", "ROA", "DCF", "FCF", "EBIT", "EBITDA", "GDP", "CPI", "IPO", "ETF", "ADR", "API",
    "CEO", "CFO", "Q1", "Q2", "Q3", "Q4", "FY", "TTM", "LTM", "US", "CN", "HK",
}

SECURITY_MASTER: List[Dict[str, Any]] = [
    {
        "entity_type": "company",
        "company": "Apple Inc.",
        "display_name": "\u82f9\u679c\u516c\u53f8",
        "aliases": ["apple", "apple inc", "aapl", "\u82f9\u679c", "\u82f9\u679c\u516c\u53f8"],
        "identifiers": {"symbol": "AAPL", "code": "", "exchange": "NASDAQ", "market": "US", "cn_code": "", "isin": "", "sec_cik": "0000320193", "asset_type": "stock"},
    },
    {
        "entity_type": "company",
        "company": "Microsoft Corporation",
        "display_name": "\u5fae\u8f6f",
        "aliases": ["microsoft", "microsoft corporation", "msft", "\u5fae\u8f6f", "\u5fae\u8f6f\u516c\u53f8"],
        "identifiers": {"symbol": "MSFT", "code": "", "exchange": "NASDAQ", "market": "US", "cn_code": "", "isin": "", "sec_cik": "0000789019", "asset_type": "stock"},
    },
    {
        "entity_type": "company",
        "company": "NVIDIA Corporation",
        "display_name": "\u82f1\u4f1f\u8fbe",
        "aliases": ["nvidia", "nvda", "\u82f1\u4f1f\u8fbe", "\u82f1\u4f1f\u8fbe\u516c\u53f8"],
        "identifiers": {"symbol": "NVDA", "code": "", "exchange": "NASDAQ", "market": "US", "cn_code": "", "isin": "", "sec_cik": "0001045810", "asset_type": "stock"},
    },
    {
        "entity_type": "company",
        "company": "Tesla, Inc.",
        "display_name": "\u7279\u65af\u62c9",
        "aliases": ["tesla", "tsla", "\u7279\u65af\u62c9", "\u7279\u65af\u62c9\u516c\u53f8"],
        "identifiers": {"symbol": "TSLA", "code": "", "exchange": "NASDAQ", "market": "US", "cn_code": "", "isin": "", "sec_cik": "0001318605", "asset_type": "stock"},
    },
    {
        "entity_type": "company",
        "company": "Amazon.com, Inc.",
        "display_name": "\u4e9a\u9a6c\u900a",
        "aliases": ["amazon", "amazon.com", "amzn", "\u4e9a\u9a6c\u900a"],
        "identifiers": {"symbol": "AMZN", "code": "", "exchange": "NASDAQ", "market": "US", "cn_code": "", "isin": "", "sec_cik": "0001018724", "asset_type": "stock"},
    },
    {
        "entity_type": "company",
        "company": "Alphabet Inc.",
        "display_name": "\u8c37\u6b4c",
        "aliases": ["alphabet", "google", "googl", "goog", "\u8c37\u6b4c", "\u5b57\u6bcd\u8868"],
        "identifiers": {"symbol": "GOOGL", "code": "", "exchange": "NASDAQ", "market": "US", "cn_code": "", "isin": "", "sec_cik": "0001652044", "asset_type": "stock"},
    },
    {
        "entity_type": "company",
        "company": "Meta Platforms, Inc.",
        "display_name": "Meta",
        "aliases": ["meta", "facebook", "meta platforms", "\u8138\u4e66"],
        "identifiers": {"symbol": "META", "code": "", "exchange": "NASDAQ", "market": "US", "cn_code": "", "isin": "", "sec_cik": "0001326801", "asset_type": "stock"},
    },
    {
        "entity_type": "company",
        "company": "\u5b81\u5fb7\u65f6\u4ee3\u65b0\u80fd\u6e90\u79d1\u6280\u80a1\u4efd\u6709\u9650\u516c\u53f8",
        "display_name": "\u5b81\u5fb7\u65f6\u4ee3",
        "aliases": ["\u5b81\u5fb7\u65f6\u4ee3", "\u5b81\u5fb7\u65f6\u4ee3\u65b0\u80fd\u6e90", "catl"],
        "identifiers": {"symbol": "", "code": "300750", "exchange": "SZSE", "market": "CN", "cn_code": "300750", "isin": "", "sec_cik": "", "asset_type": "stock"},
    },
    {
        "entity_type": "company",
        "company": "\u6bd4\u4e9a\u8fea\u80a1\u4efd\u6709\u9650\u516c\u53f8",
        "display_name": "\u6bd4\u4e9a\u8fea",
        "aliases": ["\u6bd4\u4e9a\u8fea", "byd", "byd company"],
        "identifiers": {"symbol": "", "code": "002594", "exchange": "SZSE", "market": "CN", "cn_code": "002594", "isin": "", "sec_cik": "", "asset_type": "stock"},
    },
    {
        "entity_type": "company",
        "company": "\u8d35\u5dde\u8305\u53f0\u9152\u80a1\u4efd\u6709\u9650\u516c\u53f8",
        "display_name": "\u8d35\u5dde\u8305\u53f0",
        "aliases": ["\u8d35\u5dde\u8305\u53f0", "\u8305\u53f0", "kweichow moutai"],
        "identifiers": {"symbol": "", "code": "600519", "exchange": "SSE", "market": "CN", "cn_code": "600519", "isin": "", "sec_cik": "", "asset_type": "stock"},
    },
    {
        "entity_type": "market_index",
        "company": "Nasdaq Composite",
        "display_name": "\u7eb3\u65af\u8fbe\u514b\u7efc\u5408\u6307\u6570",
        "aliases": ["nasdaq", "nasdaq composite", "ixic", "^ixic", "\u7eb3\u65af\u8fbe\u514b", "\u7eb3\u6307", "\u7eb3\u65af\u8fbe\u514b\u6307\u6570", "\u7eb3\u65af\u8fbe\u514b\u7efc\u5408\u6307\u6570"],
        "identifiers": {"symbol": "^IXIC", "code": "", "exchange": "NASDAQ", "market": "US", "cn_code": "", "isin": "", "sec_cik": "", "asset_type": "index"},
    },
    {
        "entity_type": "market_index",
        "company": "Nasdaq 100",
        "display_name": "\u7eb3\u65af\u8fbe\u514b100\u6307\u6570",
        "aliases": ["nasdaq 100", "ndx", "^ndx", "\u7eb3\u65af\u8fbe\u514b100", "\u7eb3\u6307100", "\u7eb3\u65af\u8fbe\u514b100\u6307\u6570"],
        "identifiers": {"symbol": "^NDX", "code": "", "exchange": "NASDAQ", "market": "US", "cn_code": "", "isin": "", "sec_cik": "", "asset_type": "index"},
    },
    {
        "entity_type": "market_index",
        "company": "S&P 500",
        "display_name": "\u6807\u666e500\u6307\u6570",
        "aliases": ["s&p 500", "sp500", "snp 500", "^gspc", "\u6807\u666e500", "\u6807\u666e500\u6307\u6570"],
        "identifiers": {"symbol": "^GSPC", "code": "", "exchange": "NYSE", "market": "US", "cn_code": "", "isin": "", "sec_cik": "", "asset_type": "index"},
    },
    {
        "entity_type": "market_index",
        "company": "Dow Jones Industrial Average",
        "display_name": "\u9053\u743c\u65af\u5de5\u4e1a\u6307\u6570",
        "aliases": ["dow jones", "djia", "^dji", "\u9053\u743c\u65af", "\u9053\u6307", "\u9053\u743c\u65af\u6307\u6570"],
        "identifiers": {"symbol": "^DJI", "code": "", "exchange": "NYSE", "market": "US", "cn_code": "", "isin": "", "sec_cik": "", "asset_type": "index"},
    },
    {
        "entity_type": "etf",
        "company": "Invesco QQQ Trust",
        "display_name": "QQQ ETF",
        "aliases": ["qqq", "nasdaq etf", "\u7eb3\u6307etf", "\u7eb3\u65af\u8fbe\u514betf"],
        "identifiers": {"symbol": "QQQ", "code": "", "exchange": "NASDAQ", "market": "US", "cn_code": "", "isin": "", "sec_cik": "", "asset_type": "etf"},
    },
]


def _blank_entity() -> Dict[str, Any]:
    return {
        "entity_type": "unknown",
        "company": "",
        "display_name": "",
        "identifiers": {"symbol": "", "code": "", "exchange": "", "market": "", "cn_code": "", "isin": "", "sec_cik": "", "asset_type": ""},
        "mentions": [],
        "confidence": 0.0,
        "resolution_source": "none",
    }


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _match_alias(question: str, aliases: Iterable[str]) -> Optional[str]:
    lower = _norm(question)
    compact = re.sub(r"\s+", "", question.lower())
    for alias in aliases:
        alias_norm = _norm(alias)
        if not alias_norm:
            continue
        if re.search(rf"\b{re.escape(alias_norm)}\b", lower):
            return alias
        if any("\u4e00" <= ch <= "\u9fff" for ch in alias_norm) and alias_norm in compact:
            return alias
    return None


def _entity_from_master(record: Dict[str, Any], mention: str, source: str, confidence: float) -> Dict[str, Any]:
    return {
        "entity_type": record.get("entity_type", "company"),
        "company": record.get("company", ""),
        "display_name": record.get("display_name", ""),
        "identifiers": dict(record.get("identifiers") or {}),
        "mentions": [{"text": mention, "type": record.get("entity_type", "company"), "source": source, "confidence": confidence}],
        "confidence": confidence,
        "resolution_source": source,
    }


def _resolve_by_code(question: str) -> Optional[Dict[str, Any]]:
    match = A_SHARE_CODE_PATTERN.search(question)
    if not match:
        return None
    code = match.group(1)
    for record in SECURITY_MASTER:
        identifiers = record.get("identifiers") or {}
        if identifiers.get("code") == code or identifiers.get("cn_code") == code:
            return _entity_from_master(record, code, "local_security_master", 0.98)
    entity = _blank_entity()
    entity.update({"entity_type": "company", "company": code, "display_name": code, "confidence": 0.95, "resolution_source": "regex_code"})
    entity["identifiers"].update({"code": code, "cn_code": code, "market": "CN", "asset_type": "stock"})
    entity["mentions"] = [{"text": code, "type": "code", "source": "regex", "confidence": 0.95}]
    return entity


def extract_explicit_symbol(question: str) -> str:
    for pattern in EXPLICIT_TICKER_PATTERNS:
        match = pattern.search(question)
        if match:
            candidate = match.group(1).upper()
            if candidate not in TICKER_STOPWORDS:
                return candidate
    for match in US_TICKER_PATTERN.finditer(question):
        candidate = match.group(0).upper()
        if candidate not in TICKER_STOPWORDS:
            return candidate
    return ""


def _resolve_by_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    if not symbol:
        return None
    symbol = symbol.upper()
    for record in SECURITY_MASTER:
        identifiers = record.get("identifiers") or {}
        aliases = [str(item).upper() for item in record.get("aliases") or []]
        if identifiers.get("symbol") == symbol or symbol in aliases:
            return _entity_from_master(record, symbol, "local_security_master", 0.97)
    entity = _blank_entity()
    entity.update({"entity_type": "company", "company": symbol, "display_name": symbol, "confidence": 0.9, "resolution_source": "regex_symbol"})
    entity["identifiers"].update({"symbol": symbol, "market": "US", "asset_type": "stock"})
    entity["mentions"] = [{"text": symbol, "type": "symbol", "source": "regex", "confidence": 0.9}]
    return entity


def _resolve_by_alias(question: str) -> Optional[Dict[str, Any]]:
    for record in SECURITY_MASTER:
        mention = _match_alias(question, record.get("aliases") or [])
        if mention:
            return _entity_from_master(record, mention, "local_security_master", 0.92)
    return None


def resolve_entities(question: str, lexical: Optional[Dict[str, Any]] = None, semantic: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    lexical = lexical or {}
    semantic = semantic or {}
    resolved: List[Dict[str, Any]] = []
    seen = set()

    code_entity = _resolve_by_code(question)
    if code_entity:
        key = (code_entity.get("identifiers") or {}).get("code") or code_entity.get("company")
        if key:
            resolved.append(code_entity)
            seen.add(str(key).upper())

    explicit_symbol = str(lexical.get("symbol") or extract_explicit_symbol(question) or "")
    symbol_entity = _resolve_by_symbol(explicit_symbol)
    if symbol_entity:
        identifiers = symbol_entity.get("identifiers") or {}
        key = identifiers.get("symbol") or identifiers.get("code") or symbol_entity.get("company")
        if key and str(key).upper() not in seen:
            resolved.append(symbol_entity)
            seen.add(str(key).upper())

    for record in SECURITY_MASTER:
        mention = _match_alias(question, record.get("aliases") or [])
        if not mention:
            continue
        entity = _entity_from_master(record, mention, "local_security_master", 0.92)
        identifiers = entity.get("identifiers") or {}
        key = identifiers.get("symbol") or identifiers.get("code") or entity.get("company")
        if key and str(key).upper() not in seen:
            resolved.append(entity)
            seen.add(str(key).upper())

    for mention in (semantic or {}).get("entity_mentions") or []:
        if not isinstance(mention, dict):
            continue
        text = str(mention.get("normalized_name_candidate") or mention.get("text") or "")
        entity = _resolve_by_semantic_candidate(text) or _resolve_by_alias(text) or _resolve_by_symbol(text.upper())
        if not entity:
            continue
        identifiers = entity.get("identifiers") or {}
        key = identifiers.get("symbol") or identifiers.get("code") or entity.get("company")
        if key and str(key).upper() not in seen:
            resolved.append(entity)
            seen.add(str(key).upper())

    return [_merge_semantic_mentions(question, item, semantic) for item in resolved]


def _resolve_by_semantic_candidate(candidate: str) -> Optional[Dict[str, Any]]:
    normalized = _norm(candidate)
    if not normalized:
        return None
    for record in SECURITY_MASTER:
        names = [
            str(record.get("company") or ""),
            str(record.get("display_name") or ""),
            *[str(alias) for alias in record.get("aliases") or []],
        ]
        if any(_norm(name) == normalized for name in names):
            return _entity_from_master(record, candidate, "semantic_candidate_exact", 0.96)
    return None


def _merge_semantic_mentions(question: str, entity: Dict[str, Any], semantic: Dict[str, Any]) -> Dict[str, Any]:
    mentions = list((semantic or {}).get("entity_mentions") or [])
    if not mentions:
        return entity
    for mention in mentions:
        text = str(mention.get("text") or mention.get("normalized_name_candidate") or "")
        candidate = str(mention.get("normalized_name_candidate") or "")
        confidence = float(mention.get("confidence") or 0.0)
        if not text:
            continue
        resolved = _resolve_by_semantic_candidate(candidate) or _resolve_by_alias(text) or _resolve_by_symbol(text.upper())
        if resolved:
            current_type = entity.get("entity_type") or ""
            resolved_type = resolved.get("entity_type") or ""
            current_symbol = (entity.get("identifiers") or {}).get("symbol") or ""
            resolved_symbol = (resolved.get("identifiers") or {}).get("symbol") or ""
            should_override = (
                confidence >= 0.7
                and (
                    not current_symbol
                    or resolved_symbol != current_symbol
                    or (mention.get("type") and mention.get("type") != current_type)
                    or (candidate and candidate.lower() not in {str(entity.get("company", "")).lower(), str(entity.get("display_name", "")).lower()})
                )
            )
            if not should_override and entity.get("confidence", 0.0) >= resolved.get("confidence", 0.0):
                continue
            resolved["mentions"].extend(entity.get("mentions") or [])
            if mention.get("ambiguity_candidates"):
                resolved["ambiguity_candidates"] = mention.get("ambiguity_candidates")
            resolved["semantic_confidence"] = confidence
            return resolved
    return entity


def resolve_entity(question: str, lexical: Optional[Dict[str, Any]] = None, semantic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lexical = lexical or {}
    semantic = semantic or {}
    entity = _resolve_by_code(question)
    if entity is None:
        entity = _resolve_by_alias(question)
    if entity is None:
        entity = _resolve_by_symbol(str(lexical.get("symbol") or extract_explicit_symbol(question)))
    if entity is None:
        entity = _blank_entity()
    return _merge_semantic_mentions(question, entity, semantic)


def maybe_lookup_with_finnhub(query: str) -> Dict[str, Any]:
    if (os.getenv("ENTITY_RESOLVER_ENABLE_FINNHUB_LOOKUP") or "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return _blank_entity()
    try:
        from nodes.retrieval.source_api import resolve_symbol
    except Exception:
        return _blank_entity()
    try:
        symbol = resolve_symbol(query)
    except Exception:
        return _blank_entity()
    if not symbol:
        return _blank_entity()
    description = query
    entity = _blank_entity()
    entity.update({"entity_type": "company", "company": description, "display_name": description, "confidence": 0.7, "resolution_source": "finnhub_symbol_lookup"})
    entity["identifiers"].update({"symbol": symbol, "market": "US" if symbol else "", "asset_type": "stock"})
    entity["mentions"] = [{"text": query, "type": "company", "source": "finnhub_symbol_lookup", "confidence": 0.7}]
    return entity
