import os
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class RouteQuery(BaseModel):
    """Route user query to the best datasource and extract ticker symbol when possible."""

    datasource: Literal["vector_store", "web_search", "direct_chat"] = Field(
        description=(
            "Decision path: 'vector_store' for company-specific filings/news; "
            "'web_search' for macro/industry/policy/real-time topics; "
            "'direct_chat' for greeting/small talk."
        )
    )
    symbol: str = Field(description="Ticker symbol like AAPL/NVDA. Empty string if none.")


SYSTEM_PROMPT = """
You are a financial query router.

Rules:
1) For specific listed companies (earnings, filings, company news), set datasource=vector_store and extract ticker.
2) For macro/industry/policy topics (rates, inflation, GDP, regulation, sector-wide trends), set datasource=web_search.
3) For casual chat/greeting without data need, set datasource=direct_chat.
4) symbol must be uppercase ticker (e.g., AAPL) or empty string.
5) Never output values outside: vector_store | web_search | direct_chat.
""".strip()


router_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", "{question}"),
    ]
)


def build_router_chain():
    llm = ChatOpenAI(model=os.getenv("ROUTER_MODEL", "gpt-4.1-mini"), temperature=0)
    return router_prompt | llm.with_structured_output(RouteQuery)
