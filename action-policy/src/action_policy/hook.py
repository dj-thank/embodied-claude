"""Claude Code PreToolUse adapter for :mod:`action_policy`."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any

from .gate import ActionGate, GateVerdict


def _hook_result(verdict: GateVerdict, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": verdict.value,
            "permissionDecisionReason": reason,
        }
    }


def evaluate_hook_payload(
    payload: object,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Translate one hook payload to a fail-closed Claude Code decision."""
    try:
        if not isinstance(payload, dict):
            return _hook_result(GateVerdict.DENY, "invalid hook payload; denied")
        if payload.get("hook_event_name") != "PreToolUse":
            return _hook_result(GateVerdict.DENY, "unexpected hook event; denied")

        tool_name = payload.get("tool_name")
        tool_input = payload.get("tool_input")
        if not isinstance(tool_name, str) or not tool_name:
            return _hook_result(GateVerdict.DENY, "invalid tool name; denied")
        if not isinstance(tool_input, dict):
            return _hook_result(GateVerdict.DENY, "invalid tool input; denied")

        decision = ActionGate.from_env(env).evaluate(tool_name, tool_input)
        return _hook_result(decision.verdict, decision.reason)
    except Exception:
        return _hook_result(GateVerdict.DENY, "action gate failed closed")


def main() -> int:
    """Read one hook event from stdin and emit one valid decision."""
    try:
        raw_input = sys.stdin.buffer.read()
        encoding = "utf-16" if raw_input.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        payload = json.loads(raw_input.decode(encoding))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError, TypeError):
        payload = None
    result = evaluate_hook_payload(payload)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
