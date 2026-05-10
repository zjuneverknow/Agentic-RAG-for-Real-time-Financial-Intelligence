from __future__ import annotations

import re
import time
from typing import Any, Dict, List

from observability.run_store import save_run_artifacts
from observability.trace import append_trace, make_trace_event


def _norm_number(value: str) -> str:
    return re.sub(r"[^0-9.-]", "", str(value or ""))


def _answer_has_value(answer: str, value: str) -> bool:
    compact_answer = _norm_number(answer)
    compact_value = _norm_number(value)
    return bool(compact_value and compact_value in compact_answer)


def contract_verifier_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    answer = state.get("draft_answer") or state.get("generation", "")
    contract = state.get("answer_contract") or (state.get("plan") or {}).get("answer_contract") or {}
    facts = list(state.get("evidence_facts") or [])
    citations = list(state.get("citations") or [])
    missing_fields: List[str] = []
    conflicts: List[str] = []

    required_metrics = list(contract.get("must_answer") or [])
    for metric in required_metrics:
        matching = [fact for fact in facts if fact.get("metric") == metric]
        if not matching:
            missing_fields.append(metric)
            continue
        if contract.get("numeric_check_required"):
            if not any(_answer_has_value(answer, fact.get("value", "")) for fact in matching):
                conflicts.append(f"numeric value missing or changed for {metric}")

    has_citation = True
    if contract.get("citation_required"):
        has_citation = bool(citations or facts)
        if not has_citation:
            missing_fields.append("citation")

    numeric_consistency = not conflicts
    answer_contract_satisfied = not missing_fields and numeric_consistency
    next_action = "end" if answer_contract_satisfied else "retrieve_more"
    verification = {
        "grounded": bool(facts or state.get("selected_evidence") or state.get("primary_source") == "direct_chat"),
        "has_citation": has_citation,
        "numeric_consistency": numeric_consistency,
        "fresh_enough": True,
        "answer_contract_satisfied": answer_contract_satisfied,
        "missing_fields": missing_fields,
        "conflicts": conflicts,
        "next_action": next_action,
    }
    event = make_trace_event(
        "contract_verifier",
        started_at=started,
        input_summary={"fact_count": len(facts), "contract": contract},
        output_summary=verification,
        status="success" if answer_contract_satisfied else "fallback",
        failure_reason="; ".join(missing_fields + conflicts),
    )
    trace = append_trace(state, event)
    output = {
        "verification": verification,
        "web_search": "No" if answer_contract_satisfied else "Yes",
        "failure_reason": "; ".join(missing_fields + conflicts),
        "answer": {
            **(state.get("answer") or {}),
            "verification": verification,
            "final_answer": answer,
        },
        "trace_events": trace,
        "control": {**(state.get("control") or {}), "last_action": "contract_verifier", "status": "success" if answer_contract_satisfied else "fallback"},
        "last_action": "contract_verifier",
    }
    merged = dict(state)
    merged.update(output)
    run_path = save_run_artifacts(merged)
    if run_path:
        output["run_path"] = run_path
    return output
