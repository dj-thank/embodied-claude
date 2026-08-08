"""Claude Code PreToolUse adapter tests."""

from action_policy import GateVerdict
from action_policy.hook import evaluate_hook_payload


def test_hook_returns_ask_for_interactive_sensor_capture() -> None:
    result = evaluate_hook_payload(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__wifi-cam__see",
            "tool_input": {},
        },
        env={},
    )

    output = result["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == GateVerdict.ASK.value


def test_hook_autonomous_allowlist_is_loaded_from_environment() -> None:
    result = evaluate_hook_payload(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__wifi-cam__see",
            "tool_input": {},
        },
        env={
            "EMBODIED_ACTION_MODE": "autonomous",
            "EMBODIED_AUTONOMOUS_ALLOW": "mcp__wifi-cam__see,mcp__memory__remember",
        },
    )

    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_hook_malformed_payload_fails_closed_without_echoing_input() -> None:
    secret = "private-camera-password"
    result = evaluate_hook_payload(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__wifi-cam__look_left",
            "tool_input": secret,
        },
        env={},
    )

    output = result["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert secret not in output["permissionDecisionReason"]


def test_hook_rejects_wrong_event() -> None:
    result = evaluate_hook_payload(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "mcp__memory__recall",
            "tool_input": {},
        },
        env={},
    )

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
