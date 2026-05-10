from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from nodes.evidence.evidence_utils import document_to_evidence, selected_evidence_to_documents
from observability.trace import append_trace, make_trace_event

NUMBER_PATTERN = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")

METRIC_ALIASES = {
    "\u8425\u4e1a\u6536\u5165": ("\u8425\u4e1a\u6536\u5165", "revenue"),
    "\u51c0\u5229\u6da6": ("\u51c0\u5229\u6da6", "net profit", "net income"),
    "\u5f52\u6bcd\u51c0\u5229\u6da6": (
        "\u5f52\u5c5e\u4e8e\u4e0a\u5e02\u516c\u53f8\u80a1\u4e1c\u7684\u51c0\u5229\u6da6",
        "\u5f52\u6bcd\u51c0\u5229\u6da6",
        "\u5f52\u6bcd",
        "attributable net profit",
    ),
}

NEGATIVE_ROW_HINTS = (
    "\u6263\u9664",  # 鎵ｉ櫎
    "\u6263\u975e",  # 鎵ｉ潪
    "\u975e\u7ecf\u5e38\u6027",  # 闈炵粡甯告€?    "\u5c11\u6570\u80a1\u4e1c",  # 灏戞暟鑲′笢
)


def _score(item: Dict[str, Any], metrics: List[str]) -> float:
    scores = item.get("scores") or {}
    metadata = item.get("metadata") or {}
    content = item.get("content") or ""
    score = float(scores.get("hybrid") or scores.get("final") or scores.get("dense") or 0.0)
    metric_terms = str(metadata.get("metric_terms") or "") + " " + content[:800]
    for metric in metrics:
        aliases = METRIC_ALIASES.get(metric, (metric,))
        if any(alias and alias in metric_terms for alias in aliases):
            score += 0.25
    if metadata.get("statement_type"):
        score += 0.05
    if metadata.get("source_type") == "cninfo" or metadata.get("authority_score") == 1.0:
        score += 0.05
    return score


def _dedupe(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        metadata = item.get("metadata") or {}
        if metadata.get("source_type") == "finnhub" or item.get("source_type") == "finnhub":
            key = (
                "finnhub",
                metadata.get("symbol") or item.get("symbol") or "",
                metadata.get("endpoint") or "",
                metadata.get("tool_name") or "",
                item.get("citation") or "",
            )
        else:
            key = metadata.get("chunk_id") or item.get("citation") or (item.get("content") or "")[:200]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _unit(content: str) -> str:
    if "\u5343\u5143" in content:
        return "\u5343\u5143"
    if "\u4e07\u5143" in content:
        return "\u4e07\u5143"
    if "%" in content:
        return "%"
    return ""


def _rows(content: str) -> List[str]:
    rows = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            rows.append(line)
        else:
            rows.extend(part.strip() for part in re.split(r"\s{2,}", line) if part.strip())
    if not rows and "|" in content:
        rows = [part.strip() for part in content.split("|") if part.strip()]
    return rows


def _row_cells(row: str) -> List[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|") if cell.strip()]


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _has_alias(row: str, aliases) -> bool:
    compact_row = _compact(row).lower()
    return any(_compact(alias).lower() in compact_row for alias in aliases if alias)


def _has_hint(row: str, hints) -> bool:
    compact_row = _compact(row)
    return any(_compact(hint) in compact_row for hint in hints if hint)


def _is_metric_row(row: str, metric: str) -> bool:
    aliases = METRIC_ALIASES.get(metric, (metric,))
    if not _has_alias(row, aliases):
        return False
    compact_row = _compact(row)
    if metric == "\u8425\u4e1a\u6536\u5165":
        return "\u8425\u4e1a\u6536\u5165" in compact_row or "revenue" in row.lower()
    if metric == "\u5f52\u6bcd\u51c0\u5229\u6da6":
        return not _has_hint(row, ("\u6263\u9664", "\u6263\u975e")) and ("\u5f52" in compact_row or "attributable" in row.lower())
    if metric == "\u51c0\u5229\u6da6":
        if _has_hint(row, NEGATIVE_ROW_HINTS):
            return False
        return "\u51c0\u5229\u6da6" in compact_row and "\u5f52" not in compact_row
    return True


def _extract_number_from_row(row: str) -> str:
    cells = _row_cells(row)
    data_cells = cells[1:] if len(cells) > 1 else cells
    for cell in data_cells:
        numbers = NUMBER_PATTERN.findall(cell)
        if numbers:
            return numbers[0]
    numbers = NUMBER_PATTERN.findall(row)
    return numbers[0] if numbers else ""


def _extract_metric_value(content: str, metric: str) -> str:
    candidate_rows = [row for row in _rows(content) if _is_metric_row(row, metric)]
    for row in candidate_rows:
        value = _extract_number_from_row(row)
        if value:
            return value
    aliases = METRIC_ALIASES.get(metric, (metric,))
    compact_content = _compact(content)
    for alias in aliases:
        compact_alias = _compact(alias)
        if not compact_alias or compact_alias not in compact_content:
            continue
        pos = compact_content.find(compact_alias)
        window = compact_content[pos : pos + 220]
        if not any(_compact(hint) in window[:100] for hint in NEGATIVE_ROW_HINTS):
            numbers = NUMBER_PATTERN.findall(window)
            if numbers:
                return numbers[0]
    return ""


def _extract_facts(items: List[Dict[str, Any]], metrics: List[str], period: str) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    seen_metrics = set()
    for item in items:
        content = item.get("content") or ""
        metadata = item.get("metadata") or {}
        for metric in metrics:
            if metric in seen_metrics:
                continue
            value = _extract_metric_value(content, metric)
            if not value:
                continue
            seen_metrics.add(metric)
            facts.append({
                "metric": metric,
                "value": value,
                "unit": _unit(content),
                "period": period or str(metadata.get("report_type") or metadata.get("period") or ""),
                "citation": item.get("citation") or metadata.get("source") or "",
                "source_url": item.get("source_url") or metadata.get("url") or metadata.get("source_url") or "",
                "chunk_id": metadata.get("chunk_id") or "",
                "confidence": round(float(item.get("confidence") or 0.85), 3),
            })
    return facts


def evidence_ledger_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    metrics = list(state.get("metrics") or ((state.get("query") or {}).get("metrics") or []))
    period = ((state.get("query") or {}).get("time_range") or {}).get("period", "")
    candidates = list(state.get("evidence_candidates") or [])
    if not candidates:
        candidates = [
            document_to_evidence(doc, source_type="milvus", source_name=doc.metadata.get("retrieval_source", "Retrieved Document"))
            for doc in state.get("documents", [])
        ]

    now = datetime.now(timezone.utc).isoformat()
    enriched = []
    for item in candidates:
        metadata = dict(item.get("metadata") or {})
        enriched_item = dict(item)
        enriched_item.setdefault("retrieved_at", now)
        enriched_item.setdefault("source_url", metadata.get("url") or metadata.get("source_url") or "")
        enriched_item.setdefault("company", metadata.get("company") or state.get("company", ""))
        enriched_item.setdefault("code", metadata.get("code") or state.get("code", ""))
        enriched_item.setdefault("symbol", metadata.get("symbol") or metadata.get("code") or state.get("symbol", ""))
        enriched_item.setdefault("statement_type", metadata.get("statement_type") or "")
        enriched_item["confidence"] = round(_score(enriched_item, metrics), 4)
        enriched_item.setdefault("authority_score", 1.0 if metadata.get("source_type") == "cninfo" else 0.7)
        enriched_item.setdefault("freshness_score", 0.5)
        enriched.append(enriched_item)

    ranked = sorted(_dedupe(enriched), key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
    selected = ranked[:8]
    facts = _extract_facts(selected, metrics, period)
    docs = selected_evidence_to_documents(selected)
    event = make_trace_event(
        "evidence_ledger",
        started_at=started,
        input_summary={"candidate_count": len(candidates), "metrics": metrics},
        output_summary={"selected_count": len(selected), "fact_count": len(facts)},
    )
    return {
        "evidence_candidates": ranked,
        "selected_evidence": selected,
        "evidence_facts": facts,
        "documents": docs,
        "citations": [item.get("citation", "") for item in selected if item.get("citation")],
        "retrieval": {
            **(state.get("retrieval") or {}),
            "evidence_candidates": ranked,
            "selected_evidence": selected,
            "evidence_facts": facts,
        },
        "trace_events": append_trace(state, event),
        "control": {**(state.get("control") or {}), "last_action": "evidence_ledger"},
        "last_action": "evidence_ledger",
    }
