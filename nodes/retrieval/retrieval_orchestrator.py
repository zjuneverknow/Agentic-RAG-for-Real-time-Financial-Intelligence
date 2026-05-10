from __future__ import annotations

import os
import time
from typing import Any, Dict

from nodes.retrieval.source_api import source_api_node
from nodes.retrieval.retrieve import milvus_node
from nodes.retrieval.web_search import web_search_node
from observability.trace import append_trace, make_trace_event
from rag_retrieval.multistage import multistage_retrieve

SOURCE_NODE = {
    "milvus": milvus_node,
    "source_api": source_api_node,
    "web_search": web_search_node,
}


def _merge_state(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    merged.update(update)
    return merged


def _append_or_take_accumulated(existing: list, returned: list) -> list:
    if returned[: len(existing)] == existing:
        return returned
    return existing + returned


def _merge_retrieval_result(working: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    merged = _merge_state(working, result)
    for key in ("documents", "evidence_candidates", "retrieval_failures", "retrieval_path"):
        merged[key] = _append_or_take_accumulated(list(working.get(key, [])), list(result.get(key, [])))
    retrieval = dict(working.get("retrieval") or {})
    result_retrieval = dict(result.get("retrieval") or {})
    for key in ("evidence_candidates", "retrieval_failures", "retrieval_path"):
        retrieval[key] = _append_or_take_accumulated(
            list((working.get("retrieval") or {}).get(key, working.get(key, []))),
            list(result_retrieval.get(key, result.get(key, []))),
        )
    retrieval["retrieval_score"] = max(float((working.get("retrieval") or {}).get("retrieval_score") or working.get("retrieval_score") or 0.0), float(result_retrieval.get("retrieval_score") or result.get("retrieval_score") or 0.0))
    merged["retrieval"] = {**result_retrieval, **retrieval}
    merged["retrieval_score"] = max(float(working.get("retrieval_score") or 0.0), float(result.get("retrieval_score") or 0.0))
    return merged


def _should_use_multistage(state: Dict[str, Any], item: Dict[str, Any]) -> bool:
    if item.get("source") != "milvus":
        return False
    if (os.getenv("DISABLE_MULTISTAGE_RETRIEVAL") or "0").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    query = state.get("query") or {}
    requirements = query.get("source_requirements") or {}
    return bool(requirements.get("needs_document_evidence") or requirements.get("needs_filing_evidence"))


def _run_multistage(working: Dict[str, Any]) -> Dict[str, Any]:
    result = multistage_retrieve(working)
    evidence_candidates = list(working.get("evidence_candidates", []))
    evidence_candidates.extend(result.evidence)
    documents = list(working.get("documents", []))
    documents.extend(result.documents)
    retrieval_path = list(working.get("retrieval_path", []))
    retrieval_path.append("multistage_milvus")
    top_score = 0.0
    for doc in result.documents:
        top_score = max(top_score, float(doc.metadata.get("hybrid_score") or 0.0))
    return {
        "documents": documents,
        "evidence_candidates": evidence_candidates,
        "retrieval_path": retrieval_path,
        "retrieval_score": max(float(working.get("retrieval_score") or 0.0), top_score),
        "retrieval_source": "MultiStage Retrieval",
        "multistage_trace": result.trace,
        "status": "success" if result.documents else "fallback",
        "web_search": "No" if result.documents else "Yes",
    }


def retrieval_orchestrator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    tool_plan = list(state.get("tool_plan") or (state.get("plan") or {}).get("tool_plan") or [])
    if not tool_plan:
        event = make_trace_event(
            "retrieval_orchestrator",
            started_at=started,
            input_summary={"tools": []},
            output_summary={"evidence_count": 0},
            status="success",
        )
        return {"trace_events": append_trace(state, event), "last_action": "retrieval_orchestrator"}

    working = dict(state)
    failures = list(state.get("retrieval_failures", []))
    source_labels = []

    for item in tool_plan:
        source = item.get("source")
        args = item.get("args") or {}
        call_state = working
        if args:
            call_state = {**working, **{key: value for key, value in args.items() if value not in (None, "")}}
        before_docs = len(working.get("documents", []))
        before_evidence = len(working.get("evidence_candidates", []))
        try:
            if _should_use_multistage(call_state, item):
                result = _run_multistage(call_state)
                # Dense hybrid remains a fallback when the document-first path is empty.
                if not result.get("documents"):
                    node = SOURCE_NODE[source]
                    result = node(call_state)
            else:
                node = SOURCE_NODE.get(source)
                if node is None:
                    failures.append(f"unknown source: {source}")
                    continue
                result = node(call_state)
        except Exception as exc:
            failures.append(f"{source}: {exc}")
            if not item.get("optional"):
                working["status"] = "fallback"
            continue

        working = _merge_retrieval_result(working, result)
        if len(working.get("documents", [])) > before_docs or len(working.get("evidence_candidates", [])) > before_evidence:
            source_labels.append(str(result.get("retrieval_source") or source))

    evidence_candidates = list(working.get("evidence_candidates", []))
    documents = list(working.get("documents", []))
    retrieval_path = list(working.get("retrieval_path", []))
    failures = list(working.get("retrieval_failures", failures))
    success = bool(evidence_candidates or documents)
    event = make_trace_event(
        "retrieval_orchestrator",
        started_at=started,
        input_summary={"tools": [item.get("tool") for item in tool_plan]},
        output_summary={
            "evidence_count": len(evidence_candidates),
            "document_count": len(documents),
            "sources": source_labels,
            "multistage": working.get("multistage_trace", {}),
        },
        status="success" if success else "fallback",
        failure_reason="; ".join(failures[-3:]) if failures and not success else "",
    )
    return {
        "documents": documents,
        "evidence_candidates": evidence_candidates,
        "retrieval_path": retrieval_path,
        "retrieval_failures": failures,
        "retrieval_source": " + ".join(source_labels) if source_labels else working.get("retrieval_source", ""),
        "retrieval_score": float(working.get("retrieval_score") or 0.0),
        "status": "success" if success else "fallback",
        "web_search": "No" if success else "Yes",
        "retrieval": {
            **(working.get("retrieval") or {}),
            "evidence_candidates": evidence_candidates,
            "retrieval_path": retrieval_path,
            "retrieval_failures": failures,
            "retrieval_score": float(working.get("retrieval_score") or 0.0),
        },
        "trace_events": append_trace(state, event),
        "control": {**(state.get("control") or {}), "last_action": "retrieval_orchestrator", "status": "success" if success else "fallback"},
        "last_action": "retrieval_orchestrator",
    }
