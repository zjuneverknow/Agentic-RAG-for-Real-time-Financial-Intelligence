from __future__ import annotations

import os
import time
from typing import Any, Dict, List

from nodes.evidence.evidence_utils import selected_evidence_to_documents
from observability.trace import append_trace, make_trace_event


def _trim(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[truncated]"


def context_composer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    facts = list(state.get("evidence_facts") or [])
    selected = list(state.get("selected_evidence") or [])
    query = state.get("query") or {}
    plan = state.get("plan") or {}
    token_budget = int(os.getenv("CONTEXT_TOKEN_BUDGET", "5000"))
    char_budget = max(token_budget * 4, 3000)
    snippet_budget = int(os.getenv("EVIDENCE_SNIPPET_CHARS", "900"))

    parts: List[str] = []
    parts.append("# Query")
    parts.append(str(query.get("original_question") or state.get("question") or ""))
    parts.append("\n# Answer Contract")
    parts.append(str(plan.get("answer_contract") or state.get("answer_contract") or {}))
    parts.append("\n# Reasoning Mode")
    parts.append(str(state.get("reasoning_mode") or plan.get("reasoning_mode") or "rag_plus"))

    parts.append("\n# Answer Facts")
    if facts:
        for idx, fact in enumerate(facts, start=1):
            parts.append(
                f"{idx}. metric={fact.get('metric','')} value={fact.get('value','')} "
                f"unit={fact.get('unit','')} period={fact.get('period','')} "
                f"chunk={fact.get('chunk_id','')} citation={fact.get('citation','')}"
            )
    else:
        parts.append("No structured facts extracted. Use evidence snippets carefully and say what is missing.")

    parts.append("\n# Evidence Snippets")
    used = len("\n".join(parts))
    dropped = []
    for idx, item in enumerate(selected, start=1):
        metadata = item.get("metadata") or {}
        citation = item.get("citation") or metadata.get("source") or f"source_{idx}"
        if item.get("source_type") == "finnhub" or str(metadata.get("source", "")).startswith(("finnhub", "git_finnhub")):
            header = (
                f"[{idx}] source={item.get('source_name','')} citation={citation} "
                f"symbol={metadata.get('symbol','')} tool={metadata.get('tool_name','')} "
                f"as_of={item.get('as_of_date','') or metadata.get('timestamp','')} score={item.get('confidence','')}"
            )
        else:
            header = (
                f"[{idx}] source={item.get('source_name','')} citation={citation} "
                f"chunk={metadata.get('chunk_id','')} page={metadata.get('page_start','')}-{metadata.get('page_end','')} "
                f"score={item.get('confidence','')}"
            )
        block = header + "\n" + _trim(item.get("content", ""), snippet_budget)
        if used + len(block) > char_budget:
            dropped.append({"citation": citation, "reason": "budget"})
            continue
        parts.append(block)
        used += len(block)

    context_text = "\n\n".join(parts)
    docs = selected_evidence_to_documents(selected)
    event = make_trace_event(
        "context_composer",
        started_at=started,
        input_summary={"fact_count": len(facts), "selected_count": len(selected)},
        output_summary={"chars": len(context_text), "dropped": len(dropped)},
    )
    return {
        "context_text": context_text,
        "context_documents": docs,
        "documents": docs,
        "token_budget": token_budget,
        "token_estimate": len(context_text) // 4,
        "dropped_items": dropped,
        "context": {
            "context_text": context_text,
            "context_documents": docs,
            "token_budget": token_budget,
            "token_estimate": len(context_text) // 4,
            "dropped_items": dropped,
        },
        "trace_events": append_trace(state, event),
        "control": {**(state.get("control") or {}), "last_action": "context_composer"},
        "last_action": "context_composer",
    }
