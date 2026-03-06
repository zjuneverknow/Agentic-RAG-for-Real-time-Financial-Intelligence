import os
from datetime import date, timedelta
from typing import Optional

import finnhub
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings


def _vector_search(question: str, symbol: str = ""):
    persist_dir = os.getenv("VECTOR_DB_DIR", "./chroma_db")
    embeddings = OpenAIEmbeddings(model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"))
    store = Chroma(persist_directory=persist_dir, embedding_function=embeddings)

    k = int(os.getenv("TOP_K", "6"))
    if symbol:
        return store.similarity_search(question, k=k, filter={"symbol": symbol})
    return store.similarity_search(question, k=k)


def _finnhub_client() -> Optional[finnhub.Client]:
    api_key = os.getenv("FINN_HUB_API") or os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return None
    return finnhub.Client(api_key=api_key)


def _resolve_symbol_with_finnhub(company_or_query: str) -> str:
    client = _finnhub_client()
    if client is None:
        return ""

    try:
        result = client.symbol_lookup(company_or_query)
    except Exception:
        return ""

    for item in result.get("result", []):
        symbol = (item.get("symbol") or "").upper()
        if symbol and "." not in symbol:
            return symbol
    return ""


def _finnhub_fallback_docs(symbol: str):
    client = _finnhub_client()
    if client is None or not symbol:
        return []

    end_dt = date.today()
    start_dt = end_dt - timedelta(days=10)

    docs = []

    try:
        profile = client.company_profile2(symbol=symbol)
        if profile:
            docs.append(
                Document(
                    page_content=(
                        f"Company profile for {symbol}: name={profile.get('name', '')}, "
                        f"industry={profile.get('finnhubIndustry', '')}, "
                        f"marketCap={profile.get('marketCapitalization', '')}."
                    ),
                    metadata={"source": "finnhub_company_profile", "symbol": symbol},
                )
            )
    except Exception:
        pass

    try:
        news = client.company_news(symbol, _from=start_dt.isoformat(), to=end_dt.isoformat())
        for item in news[:8]:
            headline = item.get("headline", "")
            summary = item.get("summary", "")
            url = item.get("url", "")
            content = f"{headline}. {summary}".strip()
            if content:
                docs.append(
                    Document(
                        page_content=content,
                        metadata={"source": url or "finnhub_news", "symbol": symbol},
                    )
                )
    except Exception:
        pass

    return docs


def retrieve_node(state):
    question = state["question"]
    symbol = (state.get("symbol") or "").upper()

    if state.get("datasource") == "vector_store" and not symbol:
        symbol = _resolve_symbol_with_finnhub(question)

    docs = _vector_search(question, symbol=symbol)

    # Vector store has priority. If empty, fallback to Finnhub.
    if not docs and symbol:
        docs = _finnhub_fallback_docs(symbol)

    return {"documents": docs, "symbol": symbol}
