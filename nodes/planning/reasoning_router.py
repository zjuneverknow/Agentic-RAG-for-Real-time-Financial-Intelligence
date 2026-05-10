from __future__ import annotations

import time
from typing import Any, Dict

from observability.trace import append_trace, make_trace_event


def reasoning_router_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    mode = state.get("reasoning_mode") or (state.get("plan") or {}).get("reasoning_mode") or "rag_plus"
    selected_count = len(state.get("selected_evidence") or [])
    fact_count = len(state.get("evidence_facts") or [])
    notes = []
    if mode == "rag_plus":
        notes.append("single-hop evidence refinement")
    elif mode == "cot_rag":
        notes.append("summarize facts before generation")
    elif mode == "hoprag":
        notes.append("multi-hop comparison requires grouped evidence")
    elif mode == "trace":
        notes.append("build event/entity evidence chain")
    elif mode == "rare":
        notes.append("decompose and verify claims")
    event = make_trace_event(
        "reasoning_router",
        started_at=started,
        input_summary={"mode": mode, "selected_count": selected_count, "fact_count": fact_count},
        output_summary={"notes": notes},
    )
    return {
        "reasoning_mode": mode,
        "reasoning_notes": notes,
        "trace_events": append_trace(state, event),
        "control": {**(state.get("control") or {}), "last_action": "reasoning_router"},
        "last_action": "reasoning_router",
    }