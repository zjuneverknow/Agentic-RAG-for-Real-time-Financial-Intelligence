from typing import List, Literal, TypedDict

from langchain_core.documents import Document


class GraphState(TypedDict, total=False):
    question: str
    symbol: str
    datasource: Literal["vector_store", "web_search", "direct_chat"]
    rewritten_question: str
    generation: str
    web_search: Literal["Yes", "No"]
    documents: List[Document]
    retry_count: int
