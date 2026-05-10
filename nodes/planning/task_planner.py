from __future__ import annotations

import time
from typing import Any, Dict, List

from observability.trace import append_trace, make_trace_event
from tools.registry import build_tool_plan


def _display_name(entity: Dict[str, Any]) -> str:
    return str(entity.get("display_name") or entity.get("company") or "")


def _focused_question(base_query: str, source: str, entity: Dict[str, Any]) -> str:
    name = _display_name(entity)
    if not name:
        return base_query
    if source == "milvus":
        return f"{name} filing report key financial facts revenue net profit {base_query}"
    if source == "source_api":
        return f"{name} live market quote price key data {base_query}"
    return f"{name} {base_query}"


def _reasoning_mode(intent: str, query: Dict[str, Any]) -> str:
    sub_questions = query.get("sub_questions") or []
    entities = query.get("entities") or {}
    if intent == "compare":
        return "hoprag"
    if intent == "reasoning":
        return "trace"
    if len(sub_questions) > 2 or len(entities.get("metrics") or []) > 2:
        return "cot_rag"
    return "rag_plus"


def _planner_args(query: Dict[str, Any]) -> Dict[str, Any]:
    entities = query.get("entities") or {}
    time_range = query.get("time_range") or {}
    entity_list = list(entities.get("entity_list") or [])
    return {
        "query": query.get("active_question") or query.get("original_question") or "",
        "sub_questions": query.get("sub_questions") or [],
        "code": entities.get("code", ""),
        "symbol": entities.get("symbol", "") or query.get("symbol", ""),
        "codes": entities.get("codes", []) or query.get("codes", []),
        "symbols": entities.get("symbols", []) or query.get("symbols", []),
        "entity_list": entity_list,
        "company": entities.get("company", ""),
        "entity": entities.get("entity") or query.get("entity") or {},
        "identifiers": entities.get("identifiers", {}),
        "year": entities.get("year", "") or time_range.get("year", ""),
        "period": entities.get("period", "") or time_range.get("period", ""),
        "metrics": entities.get("metrics", []),
        "market_metrics": entities.get("market_metrics", []) or query.get("market_metrics", []),
    }


def _expand_multi_entity_tool_plan(tool_plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    expanded: List[Dict[str, Any]] = []
    for item in tool_plan:
        args = dict(item.get("args") or {})
        entity_list = [entity for entity in args.get("entity_list") or [] if isinstance(entity, dict)]
        source = item.get("source")
        if item.get("evidence_need") or source not in {"source_api", "milvus"} or len(entity_list) <= 1:
            expanded.append(item)
            continue
        for index, entity in enumerate(entity_list):
            identifiers = entity.get("identifiers") or {}
            symbol = str(identifiers.get("symbol") or "").upper()
            code = str(identifiers.get("code") or identifiers.get("cn_code") or "")
            if source == "source_api" and not symbol:
                continue
            if source == "milvus" and not code:
                continue
            focused_question = _focused_question(str(args.get("query") or ""), str(source), entity)
            sub_args = dict(args)
            sub_args.update(
                {
                    "active_question": focused_question,
                    "entity": entity,
                    "company": _display_name(entity),
                    "symbol": symbol,
                    "code": code,
                    "current_tool_args": {
                        "entity": entity,
                        "company": _display_name(entity),
                        "symbol": symbol,
                        "code": code,
                        "question": focused_question,
                        "entity_index": index,
                    },
                }
            )
            expanded.append({**item, "args": sub_args, "fanout_entity": _display_name(entity), "fanout_index": index})
    return expanded


def task_planner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    query = state.get("query") or {}
    intent = query.get("intent") or state.get("intent", "fact")
    requirements = query.get("source_requirements") or state.get("source_requirements") or {"needs_answer": True}
    evidence_needs = list(query.get("evidence_needs") or state.get("evidence_needs") or [])
    tool_plan = _expand_multi_entity_tool_plan(build_tool_plan(requirements, _planner_args(query), evidence_needs))
    sources = [item["source"] for item in tool_plan]
    primary = sources[0] if sources else "direct_chat"
    secondary = list(dict.fromkeys(sources[1:]))
    reasoning_mode = _reasoning_mode(intent, query)
    query_entities = query.get("entities") or {}
    metrics = list(query_entities.get("metrics") or [])
    required_entities = [
        {
            "company": _display_name(item),
            "symbol": (item.get("identifiers") or {}).get("symbol", ""),
            "code": (item.get("identifiers") or {}).get("code", "") or (item.get("identifiers") or {}).get("cn_code", ""),
        }
        for item in query_entities.get("entity_list") or []
    ]
    answer_contract = {
        "must_answer": metrics,
        "required_entities": required_entities,
        "must_include": ["period", "unit", "source"] if metrics else ["source"] if primary != "direct_chat" else [],
        "citation_required": primary != "direct_chat",
        "freshness_required": bool(query.get("requires_freshness")),
        "numeric_check_required": bool(metrics),
    }
    plan = {
        "primary_source": primary,
        "secondary_sources": secondary,
        "tool_plan": tool_plan,
        "evidence_needs": evidence_needs,
        "reasoning_mode": reasoning_mode,
        "answer_contract": answer_contract,
        "source_requirements": requirements,
        "needs_query_expansion": intent in {"summary", "reasoning", "compare"} or len(query.get("sub_questions") or []) > 1,
        "needs_multi_source": len(tool_plan) > 1,
        "next_action": "generate" if primary == "direct_chat" else "retrieval_orchestrator",
    }
    event = make_trace_event(
        "task_planner",
        started_at=started,
        input_summary={"intent": intent, "requirements": requirements, "evidence_needs": evidence_needs},
        output_summary={"primary_source": primary, "reasoning_mode": reasoning_mode, "tools": [t["tool"] for t in tool_plan]},
    )
    return {
        "plan": plan,
        "primary_source": primary,
        "secondary_sources": secondary,
        "tool_plan": tool_plan,
        "evidence_needs": evidence_needs,
        "reasoning_mode": reasoning_mode,
        "answer_contract": answer_contract,
        "datasource": primary,
        "next_step": plan["next_action"],
        "needs_query_expansion": plan["needs_query_expansion"],
        "needs_multi_source": plan["needs_multi_source"],
        "trace_events": append_trace(state, event),
        "control": {**(state.get("control") or {}), "last_action": "task_planner"},
        "last_action": "task_planner",
    }
