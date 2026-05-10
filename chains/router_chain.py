import os
from typing import List, Literal

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    """Analyze the question and produce a first-pass retrieval plan."""

    intent: Literal["fact", "summary", "compare", "reasoning", "chat"] = Field(
        description="High-level user intent."
    )
    primary_source: Literal["source_api", "milvus", "web_search", "direct_chat"] = Field(
        description="Primary source to consult first."
    )
    secondary_sources: List[Literal["source_api", "milvus", "web_search"]] = Field(
        default_factory=list,
        description="Additional sources worth consulting if needed.",
    )
    symbol: str = Field(description="Ticker symbol like AAPL/NVDA or A-share code like 300750. Empty string if none.")
    company_name: str = Field(default="", description="Company name if clearly mentioned.")
    requires_freshness: bool = Field(
        description="True when the user likely needs current or recent information."
    )
    needs_query_expansion: bool = Field(
        description="True when retrieval should try a rewritten or expanded query."
    )
    needs_multi_source: bool = Field(
        description="True when one source is unlikely to be enough."
    )


SYSTEM_PROMPT = """
You are a financial query planner for a RAG system.

Decide the user intent and the best retrieval plan.

Rules:
1) Use primary_source=milvus for Chinese A-share filings, announcements, annual/quarterly reports, and document-grounded accounting metrics such as revenue, net profit, attributable net profit, balance sheet, income statement, or cash flow statement.
2) Use primary_source=source_api for external structured API data such as latest stock price, PE/PB valuation metrics, company profile, analyst ratings, or provider-specific market data.
3) Use primary_source=milvus for internal knowledge, research notes, filings chunks, historical semantic search, or document-grounded analysis.
4) Use primary_source=web_search for macro/industry/policy/breaking-news topics and open-web information.
5) Use primary_source=direct_chat only for greetings or casual conversation that needs no retrieval.
6) requires_freshness=true for questions that mention latest/current/recent/today/now or implicitly need up-to-date market data.
7) needs_multi_source=true when the user asks for explanation/comparison/analysis that may benefit from combining structured facts with documents or news.
8) needs_query_expansion=true when the user question is broad, underspecified, or likely benefits from retrieval keyword rewriting.
9) Recognize US/global ticker symbols when explicit. Do not infer a US ticker from a Chinese company name. For A-share six-digit codes, put the code in symbol; otherwise leave symbol empty.
10) secondary_sources should be short and practical; avoid duplicates and avoid direct_chat in secondary_sources.
""".strip()


planner_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", "{question}"),
    ]
)


def build_router_chain():
    llm = ChatOpenAI(model=os.getenv("ROUTER_MODEL", "gpt-4.1-mini"), temperature=0)
    return planner_prompt | llm.with_structured_output(QueryPlan)
