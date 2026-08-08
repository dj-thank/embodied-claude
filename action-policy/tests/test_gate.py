"""Interface tests for the embodied action gate."""

import ast
from pathlib import Path

import pytest

from action_policy import ActionClass, ActionGate, GateVerdict


@pytest.mark.parametrize(
    "tool_name",
    [
        "mcp__system-temperature__get_system_temperature",
        "mcp__wifi-cam__camera_info",
        "mcp__memory__recall",
        "mcp__memory__prepare_forget",
    ],
)
def test_interactive_mode_allows_non_outward_tools(tool_name: str) -> None:
    decision = ActionGate(mode="interactive").evaluate(tool_name, {})

    assert decision.verdict is GateVerdict.ALLOW


@pytest.mark.parametrize(
    "tool_name",
    [
        "mcp__memory__search_memories",
        "mcp__memory__recall",
        "mcp__memory__recall_with_associations",
        "mcp__memory__recall_divergent",
        "mcp__memory__tom",
    ],
)
def test_memory_retrieval_with_metadata_updates_is_local_bookkeeping(
    tool_name: str,
) -> None:
    decision = ActionGate(mode="interactive").evaluate(tool_name, {})

    assert decision.action_class is ActionClass.LOCAL_BOOKKEEPING
    assert decision.verdict is GateVerdict.ALLOW


@pytest.mark.parametrize(
    ("tool_name", "expected_class"),
    [
        ("mcp__wifi-cam__see", ActionClass.SENSITIVE_OBSERVATION),
        ("mcp__wifi-cam__look_left", ActionClass.PHYSICAL_MOTION),
        ("mcp__elevenlabs-t2s__say", ActionClass.EXTERNAL_SPEECH),
        ("mcp__memory__remember", ActionClass.PERSISTENT_WRITE),
        ("mcp__memory__forget", ActionClass.DESTRUCTIVE),
    ],
)
def test_interactive_mode_asks_for_each_outward_action_class(
    tool_name: str,
    expected_class: ActionClass,
) -> None:
    decision = ActionGate(mode="interactive").evaluate(tool_name, {})

    assert decision.verdict is GateVerdict.ASK
    assert decision.action_class is expected_class


def test_input_hash_is_canonical_and_does_not_expose_payload() -> None:
    gate = ActionGate(mode="interactive")
    first = gate.evaluate(
        "mcp__elevenlabs-t2s__say",
        {"text": "private speech", "options": {"b": 2, "a": 1}},
    )
    second = gate.evaluate(
        "mcp__elevenlabs-t2s__say",
        {"options": {"a": 1, "b": 2}, "text": "private speech"},
    )

    assert first.input_sha256 == second.input_sha256
    assert len(first.input_sha256) == 64
    assert "private speech" not in first.reason


def test_autonomous_mode_denies_outward_actions_without_exact_allowlist() -> None:
    decision = ActionGate(mode="autonomous").evaluate("mcp__wifi-cam__see", {})

    assert decision.verdict is GateVerdict.DENY


def test_autonomous_allowlist_is_exact_and_never_enables_destructive_action() -> None:
    gate = ActionGate(
        mode="autonomous",
        autonomous_allow=frozenset(
            {
                "mcp__wifi-cam__see",
                "mcp__memory__forget",
            }
        ),
    )

    allowed = gate.evaluate("mcp__wifi-cam__see", {})
    different_tool = gate.evaluate("mcp__usb-webcam__see", {})
    destructive = gate.evaluate(
        "mcp__memory__forget",
        {"memory_id": "memory-1", "confirmation_token": "secret"},
    )

    assert allowed.verdict is GateVerdict.ALLOW
    assert different_tool.verdict is GateVerdict.DENY
    assert destructive.verdict is GateVerdict.DENY
    assert "secret" not in destructive.reason


def test_unknown_tool_requires_human_confirmation_or_is_denied() -> None:
    interactive = ActionGate(mode="interactive").evaluate("mcp__future__act", {})
    autonomous = ActionGate(
        mode="autonomous",
        autonomous_allow=frozenset({"mcp__future__act"}),
    ).evaluate("mcp__future__act", {})

    assert interactive.action_class is ActionClass.UNKNOWN
    assert interactive.verdict is GateVerdict.ASK
    assert autonomous.verdict is GateVerdict.DENY


def test_invalid_mode_and_non_json_input_fail_closed() -> None:
    invalid_mode = ActionGate(mode="surprise").evaluate("mcp__memory__recall", {})
    invalid_input = ActionGate(mode="interactive").evaluate(
        "mcp__memory__remember",
        {"importance": float("nan")},
    )

    assert invalid_mode.verdict is GateVerdict.DENY
    assert invalid_input.verdict is GateVerdict.DENY


@pytest.mark.parametrize(
    "tool_name",
    ["", "   ", "memory.recall", "mcp__memory__recall\n"],
)
def test_invalid_tool_name_fails_closed(tool_name: str) -> None:
    decision = ActionGate(mode="interactive").evaluate(tool_name, {})

    assert decision.action_class is ActionClass.UNKNOWN
    assert decision.verdict is GateVerdict.DENY


def test_every_embodied_mcp_tool_has_an_explicit_classification() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    servers = {
        "wifi-cam": repo_root / "wifi-cam-mcp/src/wifi_cam_mcp/server.py",
        "usb-webcam": repo_root / "usb-webcam-mcp/src/usb_webcam_mcp/server.py",
        "memory": repo_root / "memory-mcp/src/memory_mcp/server.py",
        "system-temperature": (
            repo_root / "system-temperature-mcp/src/system_temperature_mcp/server.py"
        ),
        "elevenlabs-t2s": (
            repo_root / "elevenlabs-t2s-mcp/src/elevenlabs_t2s_mcp/server.py"
        ),
    }
    discovered: set[str] = set()
    for server_name, path in servers.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "Tool":
                continue
            name_keyword = next(
                (keyword for keyword in node.keywords if keyword.arg == "name"),
                None,
            )
            if name_keyword and isinstance(name_keyword.value, ast.Constant):
                discovered.add(f"mcp__{server_name}__{name_keyword.value.value}")

    assert len(discovered) == 51
    unclassified = {
        tool_name
        for tool_name in discovered
        if ActionGate(mode="interactive").evaluate(tool_name, {}).action_class
        is ActionClass.UNKNOWN
    }
    assert unclassified == set()
