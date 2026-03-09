import os

from chains.router_chain import build_router_chain


def router_node(state):
    question = state.get("active_question") or state["question"]
    chain = build_router_chain()
    result = chain.invoke({"question": question})

    symbol = (result.symbol or "").strip().upper()
    flag = (os.getenv("DEBUG_ROUTING") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        print(
            f"[router] datasource={result.datasource} symbol={symbol!r} question={question!r}",
            flush=True,
        )
    return {
        "datasource": result.datasource,
        "symbol": symbol,
        "active_question": question,
    }
