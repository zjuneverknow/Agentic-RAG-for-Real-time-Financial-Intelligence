from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


SCRIPT_DIR = Path(__file__).resolve().parent
ALLOWED_SCRIPTS = {
    "symbols.py",
    "stock_market.py",
    "fundamentals.py",
    "news.py",
    "analyst.py",
    "technical.py",
}


def _emit(data: Dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _arg_name(key: str) -> str:
    return "--" + key.replace("_", "-")


def build_command(tool_call: Dict[str, Any]) -> List[str]:
    script = str(tool_call.get("script") or "")
    operation = str(tool_call.get("operation") or "")
    args = tool_call.get("args") or {}
    if script not in ALLOWED_SCRIPTS:
        raise ValueError(f"Unsupported script: {script}")
    if not operation:
        raise ValueError("Missing operation")
    if not isinstance(args, dict):
        raise ValueError("args must be an object")

    command = [sys.executable, str(SCRIPT_DIR / script), operation]
    for key, value in args.items():
        if value is None or value is False:
            continue
        command.append(_arg_name(str(key)))
        if value is not True:
            command.append(str(value))
    return command


def execute(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    command = build_command(tool_call)
    completed = subprocess.run(command, cwd=SCRIPT_DIR.parents[3], text=True, capture_output=True)
    try:
        payload = json.loads(completed.stdout) if completed.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"ok": False, "raw_stdout": completed.stdout}
    return {
        "ok": completed.returncode == 0 and bool(payload.get("ok", completed.returncode == 0)),
        "tool_call": tool_call,
        "command": command,
        "returncode": completed.returncode,
        "result": payload,
        "stderr": completed.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute an LLM-selected Finnhub skill tool call.")
    parser.add_argument("--tool-call-json", default="", help="JSON object matching assets/finnhub-tool-call.schema.json.")
    parser.add_argument("--tool-call-file", default="", help="Path to a JSON file matching assets/finnhub-tool-call.schema.json.")
    args = parser.parse_args()
    try:
        if args.tool_call_file:
            tool_call = json.loads(Path(args.tool_call_file).read_text(encoding="utf-8"))
        elif args.tool_call_json:
            tool_call = json.loads(args.tool_call_json)
        else:
            tool_call = json.loads(sys.stdin.read())
        result = execute(tool_call)
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    _emit(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
