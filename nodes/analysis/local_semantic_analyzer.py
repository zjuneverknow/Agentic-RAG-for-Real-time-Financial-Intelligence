from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, Field


class SemanticAnalysis(BaseModel):
    intent: str = Field(default="", description="fact, summary, compare, reasoning, chat, or a richer financial intent")
    entity_mentions: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    market_metrics: list[str] = Field(default_factory=list)
    sub_questions: list[dict[str, Any]] = Field(default_factory=list)
    source_requirements: dict[str, bool] = Field(default_factory=dict)
    confidence: float = 0.0
    ambiguities: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """
You are a query analysis component for a financial RAG system. Return strict JSON only.
Analyze the user's question for intent, entity mentions, sub-questions, metrics, market metrics, and source requirements.
Use the provided skill document as domain guidance.
Do not invent securities identifiers such as ticker, CIK, exchange, or ISIN. Only identify entity mentions and semantic needs.
Allowed base intent values are fact, summary, compare, reasoning, chat. Richer intents are allowed only if they map clearly to one of those base intents later.
""".strip()


@lru_cache(maxsize=1)
def _load_skill_text() -> str:
    configured = (os.getenv("QUERY_UNDERSTANDING_SKILL_PATH") or "").strip()
    if configured:
        path = Path(configured)
    else:
        path = Path(__file__).resolve().parents[1] / "skills" / "financial_query_understanding_skill.md"
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _enabled() -> bool:
    mode = (os.getenv("QUERY_ANALYZER_MODE") or "hybrid").strip().lower()
    if mode not in {"hybrid", "local_llm"}:
        return False
    return bool((os.getenv("LOCAL_ANALYZER_BASE_URL") or "").strip() and (os.getenv("LOCAL_ANALYZER_MODEL") or "").strip())


def _empty(enabled: bool = False, error: str = "") -> Dict[str, Any]:
    return {
        "enabled": enabled,
        "intent": "",
        "entity_mentions": [],
        "metrics": [],
        "market_metrics": [],
        "sub_questions": [],
        "source_requirements": {},
        "confidence": 0.0,
        "ambiguities": [],
        "error": error,
        "skill_loaded": bool(_load_skill_text()),
    }


def _parse_json(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    parsed = json.loads(raw)
    model = SemanticAnalysis.model_validate(parsed)
    result = model.model_dump()
    result["enabled"] = True
    result["error"] = ""
    result["skill_loaded"] = bool(_load_skill_text())
    return result


def analyze_semantics(question: str, lexical: Dict[str, Any]) -> Dict[str, Any]:
    if not _enabled():
        return _empty(False)
    try:
        from langchain_openai import ChatOpenAI
    except Exception as exc:
        return _empty(True, f"langchain_openai unavailable: {exc}")

    base_url = (os.getenv("LOCAL_ANALYZER_BASE_URL") or "").strip()
    model = (os.getenv("LOCAL_ANALYZER_MODEL") or "").strip()
    api_key = (os.getenv("LOCAL_ANALYZER_API_KEY") or os.getenv("OPENAI_API_KEY") or "not-needed").strip()
    timeout = float(os.getenv("LOCAL_ANALYZER_TIMEOUT", "20"))
    skill_text = _load_skill_text()
    try:
        llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0, timeout=timeout)
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"# Skill Document\n{skill_text}\n\n"
            f"# User Question\n{question}\n\n"
            f"# Lexical Hints\n{json.dumps(lexical, ensure_ascii=False)}\n\n"
            "Return JSON only."
        )
        response = llm.invoke(prompt)
        content = response.content if isinstance(response.content, str) else str(response.content)
        return _parse_json(content)
    except Exception as exc:
        return _empty(True, f"local semantic analyzer failed: {type(exc).__name__}: {exc}")