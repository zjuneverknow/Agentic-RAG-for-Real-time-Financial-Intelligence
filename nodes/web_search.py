import os

from langchain_community.tools.tavily_search import TavilySearchResults


def rewrite_query_node(state):
    question = state["question"]
    rewritten = f"{question} financial report revenue growth YoY latest filing"
    return {"rewritten_question": rewritten}


def web_search_node(state):
    query = state.get("rewritten_question") or state["question"]
    k = int(os.getenv("WEB_TOP_K", "5"))
    tool = TavilySearchResults(max_results=k)
    results = tool.invoke({"query": query})

    docs = state.get("documents", [])
    for item in results:
        content = item.get("content") or item.get("snippet") or ""
        url = item.get("url", "")
        if content:
            from langchain_core.documents import Document
            docs.append(Document(page_content=content, metadata={"source": url}))

    return {"documents": docs, "web_search": "No"}
