import os
import warnings
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

from nodes.generate import generate_node, self_reflect_node
from nodes.grade_docs import grade_documents_node
from nodes.retrieve import retrieve_node
from nodes.router import router_node
from nodes.web_search import rewrite_query_node, web_search_node
from state import GraphState

load_dotenv()

MAX_RETRY = 1
MAX_REWRITE_BEFORE_WEB = 1


def _debug_routing(label: str, choice, state: GraphState) -> None:
    flag = (os.getenv("DEBUG_ROUTING") or "").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return

    docs = state.get("documents") or []
    brief = {
        "datasource": state.get("datasource"),
        "symbol": state.get("symbol"),
        "web_search": state.get("web_search"),
        "api_failed": state.get("api_failed"),
        "retry_count": state.get("retry_count"),
        "n_docs": len(docs),
    }
    print(f"[route] {label} -> {choice} | state={brief}", flush=True)


def _allow_web_search(state: GraphState) -> bool:
    return state.get("datasource") == "web_search" or bool(state.get("api_failed"))


def route_from_router(state: GraphState) -> str:
    datasource = state.get("datasource", "web_search")
    if datasource in {"vector_store", "web_search", "direct_chat"}:
        choice = datasource
    else:
        choice = "web_search"
    _debug_routing("after_router", choice, state)
    return choice


def route_after_retrieve(state: GraphState) -> str:
    if state.get("api_failed"):
        choice = "web_search"
    else:
        choice = "grade_docs"
    _debug_routing("after_retrieve", choice, state)
    return choice


def route_after_grading(state: GraphState) -> str:
    if state.get("web_search") == "Yes":
        choice = "rewrite_query"
    else:
        choice = "generate"
    _debug_routing("after_grade_docs", choice, state)
    return choice


def route_after_reflection(state: GraphState) -> str:
    retries = state.get("retry_count", 0)
    if state.get("web_search") == "Yes" and retries < MAX_RETRY:
        choice = "rewrite_query"
    else:
        choice = END
    _debug_routing("after_self_reflect", choice, state)
    return choice


def route_after_rewrite(state: GraphState) -> str:
    rewrite_count = int(state.get("rewrite_count") or 0)
    if rewrite_count < MAX_REWRITE_BEFORE_WEB:
        choice = "router"
    else:
        choice = "web_search"
    _debug_routing("after_rewrite_query", choice, state)
    return choice


def build_graph():
    workflow = StateGraph(GraphState)

    workflow.add_node("router", router_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("grade_docs", grade_documents_node)
    workflow.add_node("rewrite_query", rewrite_query_node)
    workflow.add_node("web_search", web_search_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("self_reflect", self_reflect_node)

    workflow.set_entry_point("router")

    workflow.add_conditional_edges(
        "router",
        route_from_router,
        {
            "vector_store": "retrieve",
            "web_search": "web_search",
            "direct_chat": "generate",
        },
    )

    workflow.add_conditional_edges(
        "retrieve",
        route_after_retrieve,
        {
            "grade_docs": "grade_docs",
            "web_search": "web_search",
        },
    )

    workflow.add_conditional_edges(
        "grade_docs",
        route_after_grading,
        {
            "rewrite_query": "rewrite_query",
            "generate": "generate",
        },
    )

    workflow.add_edge("web_search", "generate")
    workflow.add_edge("generate", "self_reflect")

    workflow.add_conditional_edges(
        "rewrite_query",
        route_after_rewrite,
        {
            "router": "router",
            "web_search": "web_search",
        },
    )

    workflow.add_conditional_edges(
        "self_reflect",
        route_after_reflection,
        {
            "rewrite_query": "rewrite_query",
            END: END,
        },
    )

    return workflow.compile()


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    app = build_graph()
    question = "苹果公司最近一年营收增长如何？"
    result = app.invoke({"question": question, "retry_count": 0})
    print(result.get("generation", ""))
