from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_trace_event(
    step: str,
    *,
    started_at: float,
    input_summary: Dict[str, Any] | None = None,
    output_summary: Dict[str, Any] | None = None,
    status: str = "success",
    failure_reason: str = "",
) -> Dict[str, Any]:
    return {
        "step": step,
        "input": input_summary or {},
        "output_summary": output_summary or {},
        "status": status,
        "latency_ms": int((time.perf_counter() - started_at) * 1000),
        "failure_reason": failure_reason,
        "timestamp": utc_now(),
    }


def append_trace(state: Dict[str, Any], event: Dict[str, Any]) -> List[Dict[str, Any]]:
    trace = list(state.get("trace_events", []))
    trace.append(event)
    return trace