from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from langchain_core.documents import Document

from nodes.evidence.evidence_utils import document_to_evidence, extend_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FINNHUB_SKILL_SCRIPTS = PROJECT_ROOT / "skills" / "api-skills" / "finnhub-skill" / "scripts"
if str(FINNHUB_SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(FINNHUB_SKILL_SCRIPTS))

from finnhub_api import call as call_finnhub_api  # noqa: E402
from finnhub_api import resolve_symbol  # noqa: E402
from skill_executor import execute as execute_finnhub_skill_call  # noqa: E402


FINNHUB_SKILL_ROOT = PROJECT_ROOT / "skills" / "api-skills" / "finnhub-skill"


def _read_skill_context() -> str:
    parts = []
    for rel in (
        "SKILL.md",
        "references/tool-selection-playbook.md",
        "assets/finnhub-tool-call.schema.json",
    ):
        path = FINNHUB_SKILL_ROOT / rel
        try:
            parts.append(f"# {rel}\n{path.read_text(encoding='utf-8')}")
        except Exception:
            continue
    return "\n\n".join(parts)


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM did not return a JSON object")
    return json.loads(raw[start : end + 1])


def _skill_llm_enabled() -> bool:
    mode = (os.getenv("SOURCE_API_SKILL_MODE") or "auto").strip().lower()
    if mode in {"off", "compat", "compatibility", "fallback"}:
        return False
    base_url = (os.getenv("SOURCE_API_SKILL_BASE_URL") or os.getenv("LOCAL_ANALYZER_BASE_URL") or "").strip()
    model = (os.getenv("SOURCE_API_SKILL_MODEL") or os.getenv("LOCAL_ANALYZER_MODEL") or "").strip()
    return bool(base_url and model)


def _skill_mode() -> str:
    return (os.getenv("SOURCE_API_SKILL_MODE") or "auto").strip().lower()


def _select_finnhub_tool_call(question: str, symbol: str, state: Dict[str, Any]) -> Dict[str, Any]:
    from langchain_openai import ChatOpenAI

    base_url = (os.getenv("SOURCE_API_SKILL_BASE_URL") or os.getenv("LOCAL_ANALYZER_BASE_URL") or "").strip()
    model = (os.getenv("SOURCE_API_SKILL_MODEL") or os.getenv("LOCAL_ANALYZER_MODEL") or "").strip()
    api_key = (os.getenv("SOURCE_API_SKILL_API_KEY") or os.getenv("LOCAL_ANALYZER_API_KEY") or os.getenv("OPENAI_API_KEY") or "not-needed").strip()
    timeout = float(os.getenv("SOURCE_API_SKILL_TIMEOUT", os.getenv("LOCAL_ANALYZER_TIMEOUT", "30")))
    skill_context = _read_skill_context()
    query = state.get("query") or {}
    entities = state.get("entities") or query.get("entities") or {}
    prompt = (
        "You are a tool-selection component inside a financial RAG agent.\n"
        "Read the Finnhub skill manual and return exactly one JSON object matching the schema.\n"
        "Do not answer the user. Do not call endpoints directly. Select the local script and operation only.\n"
        "If the symbol is missing or ambiguous, select symbols.py search.\n\n"
        f"# Finnhub Skill Context\n{skill_context}\n\n"
        f"# User Question\n{question}\n\n"
        f"# Known Symbol\n{symbol}\n\n"
        f"# Query Analyzer Entities\n{json.dumps(entities, ensure_ascii=False, default=str)}\n\n"
        "Return JSON only."
    )
    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0, timeout=timeout)
    response = llm.invoke(prompt)
    content = response.content if isinstance(response.content, str) else str(response.content)
    return _extract_json_object(content)


def source_api_node(state: Dict[str, Any]) -> Dict[str, Any]:
    tool_args = state.get("current_tool_args") or {}
    question = tool_args.get("question") or state.get("active_question") or state.get("question") or ""
    symbol = (tool_args.get("symbol") or state.get("symbol") or "").upper()
    if not symbol:
        symbol = resolve_symbol(question)

    retrieval_path = list(state.get("retrieval_path", []))
    retrieval_path.append("source_api")
    failures = list(state.get("retrieval_failures", []))

    provider = str(tool_args.get("provider") or state.get("source_api_provider") or "finnhub")
    skill_execution = None
    if provider != "finnhub":
        result = {"ok": False, "route": {}, "evidence": None, "errors": [f"Unsupported source_api provider: {provider}"]}
    else:
        if _skill_llm_enabled():
            try:
                tool_call = _select_finnhub_tool_call(question, symbol, state)
                skill_execution = execute_finnhub_skill_call(tool_call)
                result = skill_execution.get("result") or {}
                if not result:
                    result = {"ok": False, "route": {}, "evidence": None, "errors": [f"empty skill execution result: {skill_execution}"]}
            except Exception as exc:
                error = f"skill llm selection failed: {type(exc).__name__}: {exc}"
                if _skill_mode() in {"required", "strict", "llm"}:
                    result = {"ok": False, "route": {}, "evidence": None, "errors": [error]}
                    skill_execution = {"mode": "skill_llm_failed", "error": error}
                else:
                    result = call_finnhub_api(question=question, symbol=symbol)
                    skill_execution = {"mode": "compatibility_after_skill_llm_error", "error": error}
        else:
            result = call_finnhub_api(question=question, symbol=symbol)
            skill_execution = {"mode": "compatibility_fallback", "reason": "SOURCE_API_SKILL_MODE is off or no local skill LLM is configured."}
    evidence_payload = result.get("evidence") if result.get("ok") else None
    docs = []
    if evidence_payload:
        docs.append(
            Document(
                page_content=str(evidence_payload.get("content") or ""),
                metadata=dict(evidence_payload.get("metadata") or {}),
            )
        )
    else:
        failures.extend([f"source_api/{provider}({symbol or 'unknown'}): {item}" for item in result.get("errors", [])])
        if not failures:
            failures.append(f"source_api/{provider}({symbol or 'unknown'}): no evidence returned")

    evidence = [
        document_to_evidence(
            item,
            source_type="finnhub",
            source_name="Finnhub API",
            default_score=1.0,
        )
        for item in docs
    ]
    success = bool(docs)
    return {
        "documents": docs,
        "evidence_candidates": extend_evidence(state, evidence),
        "symbol": symbol,
        "api_failed": not success,
        "web_search": "No" if success else "Yes",
        "active_question": question,
        "last_action": "source_api",
        "status": "success" if success else "fallback",
        "retrieval_source": "Finnhub API" if success else "",
        "retrieval_score": 1.0 if success else 0.0,
        "retrieval_path": retrieval_path,
        "retrieval_failures": failures,
        "finnhub_route": result.get("route") or {},
        "finnhub_skill_execution": skill_execution,
        "retrieval": {
            "evidence_candidates": extend_evidence(state, evidence),
            "retrieval_source": "Finnhub API" if success else "",
            "retrieval_score": 1.0 if success else 0.0,
            "retrieval_path": retrieval_path,
            "retrieval_failures": failures,
            "finnhub_route": result.get("route") or {},
            "finnhub_skill_execution": skill_execution,
        },
    }
