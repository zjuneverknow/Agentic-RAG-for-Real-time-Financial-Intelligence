import os

from langchain_openai import ChatOpenAI

from chains.hallucination import (
    build_reflection_model,
    parse_yes_no,
    support_check_prompt,
    useful_check_prompt,
)


def _context_text(state) -> str:
    if state.get("context_text"):
        return state["context_text"]
    if state.get("context", {}).get("context_text"):
        return state["context"]["context_text"]
    return "\n\n".join(d.page_content for d in state.get("documents", []))[:12000]


def _source_label(state) -> str:
    if state.get("datasource") == "direct_chat" or state.get("primary_source") == "direct_chat":
        return "Direct Chat"

    source = state.get("retrieval_source")
    if source:
        return source

    path = state.get("retrieval_path") or []
    if not path:
        return "Unknown"

    labels = {
        "source_api": "Source API",
        "milvus": "Milvus Hybrid",
        "web_search": "Web Search",
    }
    return " -> ".join(labels.get(step, step) for step in path)


def generate_answer_node(state):
    question = state.get("original_question") or state["question"]
    context = _context_text(state)
    datasource = state.get("datasource", state.get("primary_source", "milvus"))
    source_label = _source_label(state)

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
At the end, add a short source line in Chinese using this exact format: 来源：{source_label}

Question:
{question}

Context:
{context}
""".strip()

    response = llm.invoke(prompt)
    content = response.content if isinstance(response.content, str) else str(response.content)
    return {
        "draft_answer": content,
        "generation": content,
        "answer": {
            **(state.get("answer") or {}),
            "draft_answer": content,
            "final_answer": content,
            "citations": state.get("citations", []),
        },
        "control": {
            **(state.get("control") or {}),
            "last_action": "generate",
        },
        "last_action": "generate",
    }


def verify_answer_node(state):
    if state.get("datasource") == "direct_chat" or state.get("primary_source") == "direct_chat":
        verification = {
            "grounded": True,
            "helpful": True,
            "failure_reason": "",
            "next_action": "end",
        }
        return {
            "retry_count": state.get("retry_count", 0),
            "web_search": "No",
            "verification": verification,
            "answer": {
                **(state.get("answer") or {}),
                "verification": verification,
            },
            "control": {
                **(state.get("control") or {}),
                "last_action": "verify_answer",
            },
            "last_action": "verify_answer",
        }

    question = state.get("original_question") or state["question"]
    answer = state.get("draft_answer") or state.get("generation", "")
    context = _context_text(state)

    model = build_reflection_model()
    support = model.invoke(support_check_prompt(question, answer, context))
    useful = model.invoke(useful_check_prompt(question, answer))

    support_ok = parse_yes_no(support.content if isinstance(support.content, str) else str(support.content)) == "yes"
    useful_ok = parse_yes_no(useful.content if isinstance(useful.content, str) else str(useful.content)) == "yes"

    retry_count = state.get("retry_count", 0)
    failure_reason = ""
    next_action = "end"

    if not support_ok:
        failure_reason = "missing_context"
        next_action = "rewrite_query"
    elif not useful_ok:
        failure_reason = "insufficient_answer"
        next_action = "rewrite_query"

    verification = {
        "grounded": support_ok,
        "helpful": useful_ok,
        "failure_reason": failure_reason,
        "next_action": next_action,
    }

    if support_ok and useful_ok:
        return {
            "retry_count": retry_count,
            "web_search": "No",
            "verification": verification,
            "answer": {
                **(state.get("answer") or {}),
                "verification": verification,
                "final_answer": answer,
            },
            "control": {
                **(state.get("control") or {}),
                "last_action": "verify_answer",
            },
            "last_action": "verify_answer",
        }

    return {
        "retry_count": retry_count + 1,
        "web_search": "Yes",
        "failure_reason": failure_reason,
        "verification": verification,
        "answer": {
            **(state.get("answer") or {}),
            "verification": verification,
        },
        "control": {
            **(state.get("control") or {}),
            "last_action": "verify_answer",
        },
        "last_action": "verify_answer",
    }


def generate_node(state):
    return generate_answer_node(state)


def self_reflect_node(state):
    return verify_answer_node(state)
