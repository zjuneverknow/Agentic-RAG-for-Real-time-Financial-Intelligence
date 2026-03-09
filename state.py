from typing import List, Literal, TypedDict

from langchain_core.documents import Document


class GraphState(TypedDict, total=False):
    question: str
    # 用于路由/检索/打分的“当前问题”（可能被 rewrite 更新）
    active_question: str
    symbol: str
    datasource: Literal["vector_store", "web_search", "direct_chat"]
    rewritten_question: str
    generation: str
    web_search: Literal["Yes", "No"]
    api_failed: bool
    documents: List[Document]
    retry_count: int
    rewrite_count: int
