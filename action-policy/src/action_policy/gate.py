"""A small, fail-closed interface over embodied tool-action policy."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionClass(str, Enum):
    """Side-effect class used by the host gate."""

    READ_ONLY = "read_only"
    LOCAL_BOOKKEEPING = "local_bookkeeping"
    LOCAL_EPHEMERAL = "local_ephemeral"
    SENSITIVE_OBSERVATION = "sensitive_observation"
    PHYSICAL_MOTION = "physical_motion"
    EXTERNAL_SPEECH = "external_speech"
    PERSISTENT_WRITE = "persistent_write"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


class GateVerdict(str, Enum):
    """Host decision understood by Claude Code PreToolUse hooks."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class GateDecision:
    """Complete decision for one exact tool invocation."""

    verdict: GateVerdict
    action_class: ActionClass
    reason: str
    input_sha256: str


def _names(server: str, leaves: set[str], action_class: ActionClass) -> dict[str, ActionClass]:
    return {f"mcp__{server}__{leaf}": action_class for leaf in leaves}


_TOOL_ACTION_CLASSES: dict[str, ActionClass] = {
    **_names(
        "wifi-cam",
        {"camera_info", "camera_presets", "get_eye_positions"},
        ActionClass.READ_ONLY,
    ),
    **_names(
        "wifi-cam",
        {"see", "listen", "see_right", "see_both"},
        ActionClass.SENSITIVE_OBSERVATION,
    ),
    **_names(
        "wifi-cam",
        {
            "look_left",
            "look_right",
            "look_up",
            "look_down",
            "look_around",
            "camera_go_to_preset",
            "right_eye_look_left",
            "right_eye_look_right",
            "right_eye_look_up",
            "right_eye_look_down",
            "both_eyes_look_left",
            "both_eyes_look_right",
            "both_eyes_look_up",
            "both_eyes_look_down",
            "align_eyes",
            "reset_eye_positions",
        },
        ActionClass.PHYSICAL_MOTION,
    ),
    **_names("usb-webcam", {"list_cameras"}, ActionClass.READ_ONLY),
    **_names("usb-webcam", {"see"}, ActionClass.SENSITIVE_OBSERVATION),
    **_names(
        "memory",
        {
            "list_recent_memories",
            "get_memory_stats",
            "get_association_diagnostics",
            "get_memory_chain",
            "search_episodes",
            "get_episode_memories",
            "recall_by_camera_position",
            "get_working_memory",
            "get_causal_chain",
        },
        ActionClass.READ_ONLY,
    ),
    **_names(
        "memory",
        {
            "search_memories",
            "recall",
            "recall_with_associations",
            "recall_divergent",
            "tom",
        },
        ActionClass.LOCAL_BOOKKEEPING,
    ),
    **_names(
        "memory",
        {"prepare_forget", "refresh_working_memory"},
        ActionClass.LOCAL_EPHEMERAL,
    ),
    **_names(
        "memory",
        {
            "remember",
            "consolidate_memories",
            "create_episode",
            "save_visual_memory",
            "save_audio_memory",
            "link_memories",
        },
        ActionClass.PERSISTENT_WRITE,
    ),
    **_names("memory", {"forget"}, ActionClass.DESTRUCTIVE),
    **_names(
        "system-temperature",
        {"get_system_temperature", "get_current_time"},
        ActionClass.READ_ONLY,
    ),
    **_names(
        "local-inference",
        {"get_local_inference_status"},
        ActionClass.READ_ONLY,
    ),
    **_names(
        "local-inference",
        {"ask_local_model"},
        ActionClass.LOCAL_BOOKKEEPING,
    ),
    **_names("elevenlabs-t2s", {"say"}, ActionClass.EXTERNAL_SPEECH),
}

_NON_OUTWARD_CLASSES = frozenset(
    {
        ActionClass.READ_ONLY,
        ActionClass.LOCAL_BOOKKEEPING,
        ActionClass.LOCAL_EPHEMERAL,
    }
)
_VALID_MODES = frozenset({"interactive", "autonomous"})


def _hash_tool_input(tool_input: dict[str, Any]) -> str:
    canonical = json.dumps(
        tool_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_valid_mcp_tool_name(tool_name: object) -> bool:
    if not isinstance(tool_name, str) or any(char.isspace() for char in tool_name):
        return False
    if not tool_name.startswith("mcp__"):
        return False
    server_name, separator, leaf_name = tool_name.removeprefix("mcp__").partition("__")
    return bool(server_name and separator and leaf_name)


@dataclass(frozen=True)
class ActionGate:
    """Evaluate exact embodied tool calls at the host seam.

    Interactive calls ask the host UI before outward actions. Autonomous calls
    deny outward actions unless the exact known tool name is operator-allowlisted;
    destructive actions remain denied in autonomous mode.
    """

    mode: str = "interactive"
    autonomous_allow: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ActionGate:
        source = os.environ if env is None else env
        mode = source.get("EMBODIED_ACTION_MODE", "interactive").strip().lower()
        allow = frozenset(
            name.strip()
            for name in source.get("EMBODIED_AUTONOMOUS_ALLOW", "").split(",")
            if name.strip()
        )
        return cls(mode=mode, autonomous_allow=allow)

    def evaluate(self, tool_name: str, tool_input: dict[str, Any]) -> GateDecision:
        valid_tool_name = _is_valid_mcp_tool_name(tool_name)
        action_class = (
            _TOOL_ACTION_CLASSES.get(tool_name, ActionClass.UNKNOWN)
            if valid_tool_name
            else ActionClass.UNKNOWN
        )
        try:
            if not isinstance(tool_input, dict):
                raise TypeError("tool_input must be an object")
            input_sha256 = _hash_tool_input(tool_input)
        except (TypeError, ValueError, OverflowError):
            return GateDecision(
                verdict=GateVerdict.DENY,
                action_class=action_class,
                reason="tool input is not canonical JSON; action gate failed closed",
                input_sha256="",
            )

        if not valid_tool_name:
            return GateDecision(
                verdict=GateVerdict.DENY,
                action_class=ActionClass.UNKNOWN,
                reason="invalid tool name; action gate failed closed",
                input_sha256=input_sha256,
            )

        mode = self.mode.strip().lower() if isinstance(self.mode, str) else ""
        if mode not in _VALID_MODES:
            return GateDecision(
                verdict=GateVerdict.DENY,
                action_class=action_class,
                reason="unknown action mode; action gate failed closed",
                input_sha256=input_sha256,
            )

        hash_hint = input_sha256[:12]
        if action_class in _NON_OUTWARD_CLASSES:
            return GateDecision(
                verdict=GateVerdict.ALLOW,
                action_class=action_class,
                reason=(
                    f"{action_class.value} tool is non-outward "
                    f"(input sha256={hash_hint})"
                ),
                input_sha256=input_sha256,
            )

        if mode == "interactive":
            return GateDecision(
                verdict=GateVerdict.ASK,
                action_class=action_class,
                reason=(
                    f"{action_class.value} action requires explicit user confirmation "
                    f"for this exact call (input sha256={hash_hint})"
                ),
                input_sha256=input_sha256,
            )

        if action_class is ActionClass.DESTRUCTIVE:
            return GateDecision(
                verdict=GateVerdict.DENY,
                action_class=action_class,
                reason="destructive actions are never pre-authorized in autonomous mode",
                input_sha256=input_sha256,
            )
        if action_class is ActionClass.UNKNOWN:
            return GateDecision(
                verdict=GateVerdict.DENY,
                action_class=action_class,
                reason="unknown MCP tools are not eligible for autonomous authorization",
                input_sha256=input_sha256,
            )
        if tool_name in self.autonomous_allow:
            return GateDecision(
                verdict=GateVerdict.ALLOW,
                action_class=action_class,
                reason=(
                    f"exact tool is operator-allowlisted for autonomous mode "
                    f"(input sha256={hash_hint})"
                ),
                input_sha256=input_sha256,
            )
        return GateDecision(
            verdict=GateVerdict.DENY,
            action_class=action_class,
            reason=(
                f"{action_class.value} action is not exact-tool allowlisted "
                "for autonomous mode"
            ),
            input_sha256=input_sha256,
        )
