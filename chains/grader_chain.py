import os
from typing import Any, Dict

from langchain_openai import ChatOpenAI


def build_retrieval_grader() -> ChatOpenAI:
    # Binary grader used by the retrieve->grade decision.
    return ChatOpenAI(
        model=os.getenv("GRADER_MODEL", "gpt-4.1-mini"),
        temperature=0,
    )


def retrieval_grader_prompt(question: str, document: str) -> str:
    return f"""
You are a strict retrieval relevance grader for a financial intelligence RAG system.

Task:
Given a user question and one retrieved document chunk, output ONLY one token:
- yes: if the chunk contains information that can directly or indirectly help answer the question.
- no: if the chunk is irrelevant, too generic, or does not provide useful evidence.

Rules:
1) Prefer recall over precision. If uncertain but potentially useful, output yes.
2) Judge relevance, not factual correctness.
3) Do not explain your answer.

Question:
{question}

Document:
{document}
""".strip()


def parse_yes_no(text: str) -> str:
    value = text.strip().lower()
    return "yes" if value.startswith("y") else "no"


def grade_document(grader: ChatOpenAI, question: str, document: str) -> str:
    response = grader.invoke(retrieval_grader_prompt(question, document))
    content = response.content if isinstance(response.content, str) else str(response.content)
    return parse_yes_no(content)
