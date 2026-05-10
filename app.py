from __future__ import annotations

import argparse
import os
import warnings

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

from nodes.analysis.query_analyzer import query_analyzer_node
from nodes.evidence.context_composer import context_composer_node
from nodes.evidence.evidence_ledger import evidence_ledger_node
from nodes.generation.answer_generator import answer_generator_node
from nodes.planning.reasoning_router import reasoning_router_node
from nodes.planning.task_planner import task_planner_node
from nodes.retrieval.retrieval_orchestrator import retrieval_orchestrator_node
from nodes.retrieval.web_search import rewrite_query_node
from nodes.validation.contract_verifier import contract_verifier_node
from state import GraphState

load_dotenv()

MAX_RETRY = int(os.getenv("MAX_RAG_RETRY", "1"))


def _debug_routing(label: str, choice: str, state: GraphState) -> None:
    flag = (os.getenv("DEBUG_ROUTING") or "").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return
    brief = {
        "intent": state.get("intent"),
        "primary_source": state.get("primary_source"),
        "reasoning_mode": state.get("reasoning_mode"),
        "status": state.get("status") or (state.get("control") or {}).get("status"),
        "retry_count": state.get("retry_count", 0),
        "evidence": len(state.get("selected_evidence") or []),
        "facts": len(state.get("evidence_facts") or []),
    }
    print(f"[route] {label} -> {choice} | state={brief}", flush=True)


def route_after_planner(state: GraphState) -> str:
    choice = "answer_generator" if state.get("primary_source") == "direct_chat" else "retrieval_orchestrator"
    _debug_routing("after_task_planner", choice, state)
    return choice


def route_after_verifier(state: GraphState) -> str:
    verification = state.get("verification") or {}
    retry_count = int(state.get("retry_count") or 0)
    if verification.get("next_action") == "retrieve_more" and retry_count < MAX_RETRY:
        choice = "rewrite_query"
    else:
        choice = END
    _debug_routing("after_contract_verifier", choice, state)
    return choice


def bump_retry_after_rewrite(state: GraphState) -> dict:
    result = rewrite_query_node(state)
    return {
        **result,
        "retry_count": int(state.get("retry_count") or 0) + 1,
        "active_question": result.get("active_question") or state.get("active_question") or state.get("question", ""),
    }


def build_graph():
    workflow = StateGraph(GraphState)

    workflow.add_node("query_analyzer", query_analyzer_node)
    workflow.add_node("task_planner", task_planner_node)
    workflow.add_node("retrieval_orchestrator", retrieval_orchestrator_node)
    workflow.add_node("evidence_ledger", evidence_ledger_node)
    workflow.add_node("reasoning_router", reasoning_router_node)
    workflow.add_node("context_composer", context_composer_node)
    workflow.add_node("answer_generator", answer_generator_node)
    workflow.add_node("contract_verifier", contract_verifier_node)
    workflow.add_node("rewrite_query", bump_retry_after_rewrite)

    workflow.set_entry_point("query_analyzer")
    workflow.add_edge("query_analyzer", "task_planner")
    workflow.add_conditional_edges(
        "task_planner",
        route_after_planner,
        {
            "retrieval_orchestrator": "retrieval_orchestrator",
            "answer_generator": "answer_generator",
        },
    )
    workflow.add_edge("retrieval_orchestrator", "evidence_ledger")
    workflow.add_edge("evidence_ledger", "reasoning_router")
    workflow.add_edge("reasoning_router", "context_composer")
    workflow.add_edge("context_composer", "answer_generator")
    workflow.add_edge("answer_generator", "contract_verifier")
    workflow.add_conditional_edges(
        "contract_verifier",
        route_after_verifier,
        {
            "rewrite_query": "rewrite_query",
            END: END,
        },
    )
    workflow.add_edge("rewrite_query", "task_planner")

    return workflow.compile()


def main() -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description="Run the financial Agentic RAG graph.")
    parser.add_argument("question", nargs="*", help="Question to ask the graph.")
    args = parser.parse_args()
    question = " ".join(args.question).strip() or "苹果、微软、宁德时代分别最近有什么关键数据？美股用实时 API，宁德时代用财报检索。"
    app = build_graph()
    result = app.invoke({"question": question, "retry_count": 0})
    print(result.get("generation") or result.get("final_answer") or "")
    run_path = result.get("run_path")
    if run_path:
        print(f"\n[run] {run_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
