import os
from typing import Any

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    content = getattr(value, "content", None)
    if isinstance(content, str):
        return content.strip()
    return str(value).strip()


def rewrite_query_node(state):
    question = _as_text(state.get("active_question") or state["question"])
    model = os.getenv("FINNHUB_ROUTER_MODEL", os.getenv("ROUTER_MODEL", "gpt-4.1-mini"))
    llm = ChatOpenAI(model=model, temperature=0)
    prompt = (
        "Rewrite the user question into concise financial retrieval keywords for filings and reports.\n"
        f"Question: {question}"
    )
    rewritten = _as_text(llm.invoke(prompt))
    if not rewritten:
        rewritten = question

    return {
        "rewritten_question": rewritten,
        "active_question": rewritten,
        "rewrite_count": int(state.get("rewrite_count") or 0) + 1,
    }


def web_search_node(state):
    query = _as_text(state.get("rewritten_question") or state.get("active_question") or state["question"])
    if not query:
        query = _as_text(state["question"])

    k = int(os.getenv("WEB_TOP_K", "5"))
    tool = TavilySearchResults(max_results=k)
    results = tool.invoke({"query": query})

    docs = list(state.get("documents", []))
    for item in results:
        content = item.get("content") or item.get("snippet") or ""
        url = item.get("url", "")
        if content:
            docs.append(Document(page_content=content, metadata={"source": url}))

    return {"documents": docs, "web_search": "No", "active_question": query}
