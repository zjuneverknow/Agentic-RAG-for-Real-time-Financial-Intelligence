import os

from langchain_openai import ChatOpenAI

from chains.hallucination import (
    build_reflection_model,
    parse_yes_no,
    support_check_prompt,
    useful_check_prompt,
)


def _context_text(state) -> str:
    return "\n\n".join(d.page_content for d in state.get("documents", []))[:12000]


def generate_node(state):
    question = state["question"]
    context = _context_text(state)
    datasource = state.get("datasource", "vector_store")

    llm = ChatOpenAI(model=os.getenv("GEN_MODEL", "gpt-4.1"), temperature=0.1)

    if datasource == "direct_chat":
        prompt = f"""
You are a polite and concise financial assistant.
The user is chatting and does not require external retrieval.
Respond naturally and briefly.

User message:
{question}
""".strip()
    else:
        prompt = f"""
You are a financial intelligence assistant.
Answer with concise, evidence-grounded statements using the provided context.
If data is insufficient, clearly state what is missing.

Question:
{question}

Context:
{context}
""".strip()

    response = llm.invoke(prompt)
    content = response.content if isinstance(response.content, str) else str(response.content)
    return {"generation": content}


def self_reflect_node(state):
    if state.get("datasource") == "direct_chat":
        return {"retry_count": state.get("retry_count", 0), "web_search": "No"}

    question = state["question"]
    answer = state.get("generation", "")
    context = _context_text(state)

    model = build_reflection_model()
    support = model.invoke(support_check_prompt(question, answer, context))
    useful = model.invoke(useful_check_prompt(question, answer))

    support_ok = parse_yes_no(support.content if isinstance(support.content, str) else str(support.content)) == "yes"
    useful_ok = parse_yes_no(useful.content if isinstance(useful.content, str) else str(useful.content)) == "yes"

    retry_count = state.get("retry_count", 0)
    if support_ok and useful_ok:
        return {"retry_count": retry_count, "web_search": "No"}

    return {"retry_count": retry_count + 1, "web_search": "Yes"}
