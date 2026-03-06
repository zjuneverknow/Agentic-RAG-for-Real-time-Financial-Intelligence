import os

from langchain_openai import ChatOpenAI


def build_reflection_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("REFLECTION_MODEL", "gpt-4.1-mini"),
        temperature=0,
    )


def support_check_prompt(question: str, answer: str, context: str) -> str:
    return f"""
You are a hallucination checker.
Return ONLY yes or no.

Question: {question}
Answer: {answer}
Context: {context}

Output yes if every key factual claim in the answer is supported by the context.
Otherwise output no.
""".strip()


def useful_check_prompt(question: str, answer: str) -> str:
    return f"""
You are an answer usefulness checker.
Return ONLY yes or no.

Question: {question}
Answer: {answer}

Output yes if the answer clearly addresses the user's request.
Otherwise output no.
""".strip()


def parse_yes_no(text: str) -> str:
    value = text.strip().lower()
    return "yes" if value.startswith("y") else "no"
