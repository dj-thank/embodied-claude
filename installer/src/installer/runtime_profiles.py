"""Runtime profiles and MCP configuration for Sanpoloid.

This module is the installer's source of truth for which MCP components exist,
how expensive presets compose them, and how each component is launched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping


class RuntimeProfile(StrEnum):
    """Named installation presets ordered from lightest to richest."""

    LITE = "lite"
    CORE = "core"
    FULL = "full"
    CUSTOM = "custom"


@dataclass(frozen=True)
class MCPComponent:
    """Everything the installer needs to launch one MCP server."""

    server_id: str
    selection_flag: str
    project_directory: str
    executable: str
    default_environment: Mapping[str, str] = field(default_factory=dict)
    host_dependencies: tuple[str, ...] = ()


COMPONENTS = (
    MCPComponent(
        server_id="wifi-cam",
        selection_flag="wifi_camera_enabled",
        project_directory="wifi-cam-mcp",
        executable="wifi-cam-mcp",
        host_dependencies=("ffmpeg",),
    ),
    MCPComponent(
        server_id="usb-webcam",
        selection_flag="usb_camera_enabled",
        project_directory="usb-webcam-mcp",
        executable="usb-webcam-mcp",
    ),
    MCPComponent(
        server_id="memory",
        selection_flag="memory_enabled",
        project_directory="memory-mcp",
        executable="memory-mcp",
    ),
    MCPComponent(
        server_id="system-temperature",
        selection_flag="system_temperature_enabled",
        project_directory="system-temperature-mcp",
        executable="system-temperature-mcp",
    ),
    MCPComponent(
        server_id="elevenlabs-t2s",
        selection_flag="elevenlabs_enabled",
        project_directory="elevenlabs-t2s-mcp",
        executable="elevenlabs-t2s",
        default_environment={
            "GO2RTC_URL": "http://127.0.0.1:1984",
            "GO2RTC_STREAM": "tapo_cam",
            "ELEVENLABS_PLAYBACK": "none",
        },
        host_dependencies=("ffmpeg",),
    ),
)

_COMPONENT_BY_ID = {component.server_id: component for component in COMPONENTS}
_PROFILE_COMPONENTS = {
    RuntimeProfile.LITE: ("system-temperature",),
    RuntimeProfile.CORE: ("wifi-cam", "memory", "system-temperature"),
    RuntimeProfile.FULL: tuple(component.server_id for component in COMPONENTS),
    RuntimeProfile.CUSTOM: (),
}

PROFILE_DESCRIPTIONS = {
    RuntimeProfile.LITE: "Smallest install: system temperature only; no camera or vector DB.",
    RuntimeProfile.CORE: (
        "Recommended body: Wi-Fi camera, long-term memory, and temperature."
    ),
    RuntimeProfile.FULL: "Every MCP, including USB camera and ElevenLabs speech output.",
    RuntimeProfile.CUSTOM: "Your explicit module selection.",
}


def _profile_from_value(value: object) -> RuntimeProfile:
    if isinstance(value, RuntimeProfile):
        return value
    normalized = str(value or RuntimeProfile.CORE.value).strip().lower()
    try:
        return RuntimeProfile(normalized)
    except ValueError as error:
        choices = ", ".join(profile.value for profile in RuntimeProfile)
        raise ValueError(
            f"Unknown runtime profile {value!r}; expected one of: {choices}"
        ) from error


def profile_server_ids(profile: RuntimeProfile | str) -> tuple[str, ...]:
    """Return the ordered server IDs supplied by a named profile."""
    return _PROFILE_COMPONENTS[_profile_from_value(profile)]


def profile_component_flags(profile: RuntimeProfile | str) -> dict[str, bool]:
    """Return each installer's checkbox value for a named profile."""
    enabled = set(profile_server_ids(profile))
    return {
        component.selection_flag: component.server_id in enabled
        for component in COMPONENTS
    }


def infer_runtime_profile(config: Mapping[str, Any]) -> RuntimeProfile:
    """Identify a named profile when explicit component choices match one."""
    selected = enabled_server_ids({**config, "runtime_profile": "custom"})
    for profile in (RuntimeProfile.LITE, RuntimeProfile.CORE, RuntimeProfile.FULL):
        if selected == profile_server_ids(profile):
            return profile
    return RuntimeProfile.CUSTOM


def enabled_server_ids(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Resolve a preset plus explicit component overrides into server IDs."""
    enabled = set(profile_server_ids(config.get("runtime_profile", RuntimeProfile.CORE)))
    for component in COMPONENTS:
        if component.selection_flag not in config:
            continue
        if bool(config[component.selection_flag]):
            enabled.add(component.server_id)
        else:
            enabled.discard(component.server_id)
    return tuple(
        component.server_id
        for component in COMPONENTS
        if component.server_id in enabled
    )


def managed_server_ids() -> tuple[str, ...]:
    """Return every MCP server ID owned by this repository."""
    return tuple(component.server_id for component in COMPONENTS)


def dependency_projects(
    repo_path: Path,
    config: Mapping[str, Any],
) -> list[tuple[str, Path]]:
    """Return the policy host and enabled projects in installation order."""
    projects = [("action-policy", repo_path / "action-policy")]
    projects.extend(
        (
            _COMPONENT_BY_ID[server_id].project_directory,
            repo_path / _COMPONENT_BY_ID[server_id].project_directory,
        )
        for server_id in enabled_server_ids(config)
    )
    return projects


def required_host_dependencies(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Return host commands required by only the enabled components."""
    requirements: set[str] = {"Python", "uv"}
    for server_id in enabled_server_ids(config):
        requirements.update(_COMPONENT_BY_ID[server_id].host_dependencies)
    order = ("ffmpeg", "Python", "uv")
    return tuple(name for name in order if name in requirements)


def action_gate_matcher() -> str:
    """Protect every managed prefix, including during profile transitions."""
    return "|".join(f"mcp__{server_id}__.*" for server_id in managed_server_ids())


def runtime_config_from_fields(
    field_value: Callable[[str], object],
) -> dict[str, Any]:
    """Read the canonical runtime selection from a wizard-like field provider."""
    config: dict[str, Any] = {
        "runtime_profile": str(field_value("runtime_profile") or "core").lower(),
    }
    for component in COMPONENTS:
        config[component.selection_flag] = bool(field_value(component.selection_flag))
    for credential_field in ("tapo_host", "tapo_username", "tapo_password"):
        config[credential_field] = str(field_value(credential_field) or "").strip()
    return config


def build_mcp_config(repo_path: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    """Build Claude's MCP configuration for the resolved runtime profile."""
    servers: dict[str, Any] = {}
    for server_id in enabled_server_ids(config):
        component = _COMPONENT_BY_ID[server_id]
        environment = dict(component.default_environment)
        if server_id == "wifi-cam":
            configured_environment = {
                "TAPO_CAMERA_HOST": str(config.get("tapo_host", "")).strip(),
                "TAPO_USERNAME": str(config.get("tapo_username", "")).strip(),
                "TAPO_PASSWORD": str(config.get("tapo_password", "")).strip(),
            }
            environment.update(
                {
                    key: value
                    for key, value in configured_environment.items()
                    if value
                }
            )
        servers[server_id] = {
            "type": "stdio",
            "command": "uv",
            "args": [
                "run",
                "--directory",
                str(repo_path / component.project_directory),
                component.executable,
            ],
            "env": environment,
        }
    return {"mcpServers": servers}
