from __future__ import annotations

import os
import time
from typing import Any, Dict, List

from langchain_openai import ChatOpenAI

from observability.trace import append_trace, make_trace_event


def _source_label(item: Dict[str, Any], index: int) -> str:
    metadata = item.get("metadata") or {}
    source_type = item.get("source_type") or ""
    source_name = item.get("source_name") or metadata.get("retrieval_source") or "Source"
    citation = item.get("citation") or metadata.get("source") or metadata.get("url") or ""
    as_of = item.get("as_of_date") or metadata.get("timestamp") or metadata.get("publish_date") or metadata.get("created_at") or ""

    details: List[str] = []
    if source_type == "finnhub" or str(metadata.get("source", "")).startswith(("finnhub", "git_finnhub")):
        if metadata.get("symbol"):
            details.append(f"symbol={metadata.get('symbol')}")
        if metadata.get("tool_name"):
            details.append(f"tool={metadata.get('tool_name')}")
        if metadata.get("endpoint"):
            details.append(f"endpoint={metadata.get('endpoint')}")
    elif source_type == "milvus" or metadata.get("chunk_id"):
        if metadata.get("company") or metadata.get("code"):
            details.append(f"entity={metadata.get('company','') or metadata.get('code','')}")
        if metadata.get("chunk_id"):
            details.append(f"chunk={metadata.get('chunk_id')}")
        page_start = metadata.get("page_start") or ""
        page_end = metadata.get("page_end") or ""
        if page_start or page_end:
            details.append(f"page={page_start}-{page_end}")
        if metadata.get("title"):
            details.append(f"title={metadata.get('title')}")
    else:
        if metadata.get("url") or citation.startswith("http"):
            details.append(str(metadata.get("url") or citation))

    if as_of:
        details.append(f"as_of={as_of}")
    detail_text = "; ".join(str(item) for item in details if item)
    if detail_text:
        return f"{index}. {source_name}: {citation} ({detail_text})"
    return f"{index}. {source_name}: {citation}"


def _sources_section(state: Dict[str, Any]) -> str:
    selected = list(state.get("selected_evidence") or [])
    if not selected:
        citations = [str(item) for item in state.get("citations", []) if item]
        if not citations:
            return ""
        lines = ["\n\n资料来源："]
        for idx, citation in enumerate(citations[:8], start=1):
            lines.append(f"{idx}. {citation}")
        return "\n".join(lines)

    lines = ["\n\n资料来源："]
    seen = set()
    count = 0
    for item in selected:
        label = _source_label(item, count + 1)
        key = label.split(": ", 1)[-1]
        if key in seen:
            continue
        seen.add(key)
        count += 1
        lines.append(label)
        if count >= 8:
            break
    return "\n".join(lines) if count else ""


def _with_sources(answer: str, state: Dict[str, Any]) -> str:
    if (os.getenv("SHOW_ANSWER_SOURCES") or "1").strip().lower() in {"0", "false", "no", "off"}:
        return answer
    if "资料来源" in answer or "Sources" in answer:
        return answer
    return answer.rstrip() + _sources_section(state)


def answer_generator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    question = state.get("original_question") or state.get("question", "")
    context = state.get("context_text") or (state.get("context") or {}).get("context_text") or ""
    datasource = state.get("primary_source") or state.get("datasource", "milvus")
    llm = ChatOpenAI(model=os.getenv("GEN_MODEL", "gpt-4.1"), temperature=0.1)

    if datasource == "direct_chat":
        prompt = f"""
You are a concise financial assistant. Respond naturally in the user's language.

User message:
{question}
""".strip()
    else:
        prompt = f"""
You are a financial evidence assistant.
Answer in the user's language, using only the provided evidence packet.
Rules:
- Preserve numeric values exactly as shown in Answer Facts when available.
- Include units and reporting period when available.
- Cite sources using chunk/page/source information from the evidence packet.
- If required evidence is missing, state what is missing instead of guessing.
- Do not provide investment advice as certainty.

Question:
{question}

Evidence packet:
{context}
""".strip()

    response = llm.invoke(prompt)
    content = response.content if isinstance(response.content, str) else str(response.content)
    final_content = _with_sources(content, state)
    event = make_trace_event(
        "answer_generator",
        started_at=started,
        input_summary={"question": question, "context_chars": len(context)},
        output_summary={"answer_chars": len(final_content), "source_count": len(state.get("selected_evidence") or [])},
    )
    return {
        "draft_answer": final_content,
        "final_answer": final_content,
        "generation": final_content,
        "answer": {
            **(state.get("answer") or {}),
            "draft_answer": final_content,
            "final_answer": final_content,
            "citations": state.get("citations", []),
        },
        "trace_events": append_trace(state, event),
        "control": {**(state.get("control") or {}), "last_action": "answer_generator"},
        "last_action": "answer_generator",
    }