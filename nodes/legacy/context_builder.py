import os
from typing import Dict, List

from nodes.evidence.evidence_utils import selected_evidence_to_documents


def _dedupe_evidence(items: List[Dict]) -> List[Dict]:
    seen = set()
    deduped = []
    for item in items:
        key = (item.get("citation"), item.get("content", "")[:300])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def context_builder_node(state):
    selected_evidence = list(state.get("selected_evidence", []))
    selected_evidence = _dedupe_evidence(selected_evidence)

    token_budget = int(os.getenv("CONTEXT_TOKEN_BUDGET", "4000"))
    char_budget = max(token_budget * 4, 2000)
    dropped_items = []
    context_parts = []
    used_chars = 0

    for index, item in enumerate(selected_evidence, start=1):
        citation = item.get("citation") or item.get("source_name") or f"source_{index}"
        content = (item.get("content") or "").strip()
        if not content:
            continue

        block = f"[{index}] {citation}\n{content}"
        remaining = char_budget - used_chars
        if remaining <= 0:
            dropped_items.append({"chunk_id": citation, "reason": "budget"})
            continue

        if len(block) > remaining:
            trimmed = block[:remaining].rstrip()
            if trimmed:
                context_parts.append(trimmed)
                used_chars += len(trimmed)
            dropped_items.append({"chunk_id": citation, "reason": "compressed"})
            break

        context_parts.append(block)
        used_chars += len(block)

    context_text = "\n\n".join(context_parts)
    citations = [item.get("citation") or item.get("source_name", "") for item in selected_evidence]
    context_documents = selected_evidence_to_documents(selected_evidence)
    token_estimate = max(used_chars // 4, 0)

    return {
        "context_text": context_text,
        "context_documents": context_documents,
        "documents": context_documents,
        "citations": citations,
        "token_budget": token_budget,
        "token_estimate": token_estimate,
        "dropped_items": dropped_items,
        "context": {
            "context_text": context_text,
            "context_documents": context_documents,
            "token_budget": token_budget,
            "token_estimate": token_estimate,
            "dropped_items": dropped_items,
        },
        "answer": {
            **(state.get("answer") or {}),
            "citations": citations,
        },
        "control": {
            **(state.get("control") or {}),
            "last_action": "context_builder",
        },
        "last_action": "context_builder",
    }
