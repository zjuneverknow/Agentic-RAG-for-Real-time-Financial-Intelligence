from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _json_default(value: Any) -> Any:
    if hasattr(value, "page_content") and hasattr(value, "metadata"):
        return {"page_content": value.page_content, "metadata": value.metadata}
    return str(value)


def save_run_artifacts(state: Dict[str, Any]) -> str:
    if (os.getenv("SAVE_RAG_RUNS") or "1").strip().lower() in {"0", "false", "no", "off"}:
        return ""
    run_id = state.get("run_id") or (state.get("control") or {}).get("run_id") or new_run_id()
    root = Path(os.getenv("RAG_RUN_DIR", "runs")) / run_id
    root.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "query.json": state.get("query") or {},
        "plan.json": state.get("plan") or {},
        "selected_evidence.json": state.get("selected_evidence") or [],
        "evidence_facts.json": state.get("evidence_facts") or [],
        "verification.json": state.get("verification") or {},
        "trace.json": state.get("trace_events") or [],
    }
    for name, payload in artifacts.items():
        (root / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    if state.get("context_text"):
        (root / "context.md").write_text(state["context_text"], encoding="utf-8")
    if state.get("generation"):
        (root / "answer.md").write_text(state["generation"], encoding="utf-8")
    return str(root)