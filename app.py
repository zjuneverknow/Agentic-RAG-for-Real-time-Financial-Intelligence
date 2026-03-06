from langgraph.graph import END, StateGraph

from nodes.generate import generate_node, self_reflect_node
from nodes.grade_docs import grade_documents_node
from nodes.retrieve import retrieve_node
from nodes.router import router_node
from nodes.web_search import rewrite_query_node, web_search_node
from state import GraphState


MAX_RETRY = 2


def route_from_router(state: GraphState) -> str:
    datasource = state.get("datasource", "web_search")
    if datasource in {"vector_store", "web_search", "direct_chat"}:
        return datasource
    return "web_search"


def route_after_grading(state: GraphState) -> str:
    if state.get("web_search") == "Yes":
        return "rewrite_query"
    return "generate"


def route_after_reflection(state: GraphState) -> str:
    retries = state.get("retry_count", 0)
    if state.get("web_search") == "Yes" and retries < MAX_RETRY:
        return "rewrite_query"
    return END


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

    workflow.add_edge("retrieve", "grade_docs")

    workflow.add_conditional_edges(
        "grade_docs",
        route_after_grading,
        {
            "rewrite_query": "rewrite_query",
            "generate": "generate",
        },
    )

    workflow.add_edge("rewrite_query", "web_search")
    workflow.add_edge("web_search", "generate")
    workflow.add_edge("generate", "self_reflect")

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
    app = build_graph()
    question = "苹果公司最近一年营收增长如何？"
    result = app.invoke({"question": question, "retry_count": 0})
    print(result.get("generation", ""))
