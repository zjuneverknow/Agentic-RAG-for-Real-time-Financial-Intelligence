from chains.router_chain import build_router_chain


def router_node(state):
    question = state["question"]
    chain = build_router_chain()
    result = chain.invoke({"question": question})

    symbol = (result.symbol or "").strip().upper()
    return {
        "datasource": result.datasource,
        "symbol": symbol,
    }
