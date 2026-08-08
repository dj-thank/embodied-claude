"""Host integration contracts for the action gate."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from action_policy import ActionGate

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
def test_cli_accepts_windows_safe_bom_encodings_and_emits_one_decision(
    encoding: str,
) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__wifi-cam__see",
            "tool_input": {},
        }
    ).encode(encoding)
    env = {**os.environ, "EMBODIED_ACTION_MODE": "interactive"}

    completed = subprocess.run(
        [sys.executable, "-m", "action_policy.hook"],
        input=payload,
        capture_output=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0
    result = json.loads(completed.stdout.decode("utf-8"))
    assert result["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert completed.stderr == b""


def test_cli_invalid_bytes_emit_a_valid_deny_decision() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "action_policy.hook"],
        input=b"\xffinvalid-json",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    result = json.loads(completed.stdout.decode("utf-8"))
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert completed.stderr == b""


def test_project_settings_route_all_mcp_calls_through_action_gate() -> None:
    settings = json.loads(
        (REPO_ROOT / ".claude/settings.json").read_text(encoding="utf-8")
    )

    pre_tool_hooks = settings["hooks"]["PreToolUse"]
    matching = [entry for entry in pre_tool_hooks if entry.get("matcher") == "mcp__.*"]
    assert len(matching) == 1
    hook = matching[0]["hooks"][0]
    assert hook["command"] == "${CLAUDE_PROJECT_DIR}/.claude/hooks/action-gate.sh"
    assert hook["args"] == []
    assert hook["timeout"] >= 10


def test_hook_wrapper_converts_gate_startup_failure_to_blocking_exit() -> None:
    wrapper = (REPO_ROOT / ".claude/hooks/action-gate.sh").read_text(
        encoding="utf-8"
    )

    assert "uv run --locked --no-sync" in wrapper
    assert "${1:-}" in wrapper
    assert "exit 2" in wrapper

    powershell_wrapper = (REPO_ROOT / ".claude/hooks/action-gate.ps1").read_text(
        encoding="utf-8"
    )
    assert "ActionPolicyDirectory" in powershell_wrapper
    assert "uv" in powershell_wrapper
    assert "exit 2" in powershell_wrapper


@pytest.mark.skipif(os.name != "nt", reason="PowerShell wrapper is Windows-only")
def test_powershell_wrapper_preserves_utf8_tool_input() -> None:
    tool_input = {"content": "日本語の記憶", "tags": ["会話"]}
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__memory__remember",
            "tool_input": tool_input,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    expected_hash = ActionGate().evaluate(
        "mcp__memory__remember", tool_input
    ).input_sha256[:12]
    env = {**os.environ, "EMBODIED_ACTION_MODE": "interactive"}

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / ".claude/hooks/action-gate.ps1"),
            "-ActionPolicyDirectory",
            str(REPO_ROOT / "action-policy"),
        ],
        input=payload,
        capture_output=True,
        check=False,
        env=env,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    result = json.loads(completed.stdout.decode("utf-8"))
    reason = result["hookSpecificOutput"]["permissionDecisionReason"]
    assert f"input sha256={expected_hash}" in reason


def test_autonomous_script_selects_noninteractive_policy_before_claude() -> None:
    script = (REPO_ROOT / "autonomous-action.sh").read_text(encoding="utf-8")

    mode_offset = script.index("export EMBODIED_ACTION_MODE=autonomous")
    invocation_offset = script.index('"$CLAUDE_BIN" -p')
    assert mode_offset < invocation_offset
    assert 'cd "$SCRIPT_DIR"' in script


def test_autonomous_script_pins_one_explicit_mcp_config() -> None:
    script = (REPO_ROOT / "autonomous-action.sh").read_text(encoding="utf-8")

    assert (
        'MCP_CONFIG="${AUTONOMOUS_MCP_CONFIG:-$SCRIPT_DIR/autonomous-mcp.json}"'
        in script
    )
    assert '[[ ! -r "$MCP_CONFIG" ]]' in script

    invocation = script[script.index('"$CLAUDE_BIN" -p') :]
    assert "--strict-mcp-config" in invocation
    assert '--mcp-config "$MCP_CONFIG"' in invocation


def test_autonomous_script_does_not_preapprove_outward_tools() -> None:
    script = (REPO_ROOT / "autonomous-action.sh").read_text(encoding="utf-8")

    invocation = script[script.index('"$CLAUDE_BIN" -p') :]
    assert "--setting-sources project" in invocation
    assert "--allowedTools" not in invocation


def test_shell_scripts_are_kept_lf_for_linux_and_wsl_execution() -> None:
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "*.sh text eol=lf" in attributes.splitlines()
