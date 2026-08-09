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


@dataclass(frozen=True)
class DependencyProject:
    """One uv project plus the optional features required by a profile."""

    name: str
    path: Path
    extras: tuple[str, ...] = ()


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
        server_id="local-inference",
        selection_flag="local_inference_enabled",
        project_directory="local-inference-mcp",
        executable="local-inference-mcp",
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
    RuntimeProfile.LITE: ("memory", "system-temperature"),
    RuntimeProfile.CORE: ("wifi-cam", "memory", "system-temperature"),
    RuntimeProfile.FULL: tuple(component.server_id for component in COMPONENTS),
    RuntimeProfile.CUSTOM: (),
}
_PROFILE_MEMORY_BACKENDS = {
    RuntimeProfile.LITE: "sqlite",
    RuntimeProfile.CORE: "chroma",
    RuntimeProfile.FULL: "chroma",
    RuntimeProfile.CUSTOM: "sqlite",
}

PROFILE_DESCRIPTIONS = {
    RuntimeProfile.LITE: (
        "Lightweight local memory (SQLite FTS) and temperature; no camera or vector DB."
    ),
    RuntimeProfile.CORE: (
        "Recommended body: Wi-Fi camera, long-term memory, and temperature."
    ),
    RuntimeProfile.FULL: (
        "Every MCP, including local inference, USB camera, and ElevenLabs speech output."
    ),
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
        backend_matches = (
            "memory" not in selected
            or "memory_backend" not in config
            or resolve_memory_backend(config) == _PROFILE_MEMORY_BACKENDS[profile]
        )
        if selected == profile_server_ids(profile) and backend_matches:
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


def resolve_memory_backend(config: Mapping[str, Any]) -> str:
    """Resolve a UI label or explicit backend from the selected profile."""
    raw_value = config.get("memory_backend")
    if raw_value is None or not str(raw_value).strip():
        profile = _profile_from_value(config.get("runtime_profile", RuntimeProfile.CORE))
        return _PROFILE_MEMORY_BACKENDS[profile]
    normalized = str(raw_value).strip().lower()
    if normalized.startswith("sqlite"):
        return "sqlite"
    if normalized.startswith("chroma"):
        return "chroma"
    raise ValueError("memory_backend must select SQLite or Chroma")


def resolve_local_inference_backend(config: Mapping[str, Any]) -> tuple[str, str]:
    """Resolve a fixed loopback runtime label into its identifier and base URL."""
    raw_value = str(config.get("local_inference_backend", "lmstudio")).strip().lower()
    if raw_value.startswith("lm studio") or raw_value == "lmstudio":
        return "lmstudio", "http://127.0.0.1:1234/v1"
    if raw_value.startswith("llama.cpp") or raw_value == "llama.cpp":
        return "llama.cpp", "http://127.0.0.1:8080/v1"
    raise ValueError("local_inference_backend must select LM Studio or llama.cpp")


def dependency_projects(
    repo_path: Path,
    config: Mapping[str, Any],
) -> list[DependencyProject]:
    """Return the policy host and enabled projects in installation order."""
    projects = [DependencyProject("action-policy", repo_path / "action-policy")]
    projects.extend(
        DependencyProject(
            name=_COMPONENT_BY_ID[server_id].project_directory,
            path=repo_path / _COMPONENT_BY_ID[server_id].project_directory,
            extras=("chroma",)
            if server_id == "memory" and resolve_memory_backend(config) == "chroma"
            else (),
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
    config["memory_backend"] = resolve_memory_backend(
        {**config, "memory_backend": field_value("memory_backend")}
    )
    backend, _base_url = resolve_local_inference_backend(
        {"local_inference_backend": field_value("local_inference_backend")}
    )
    config["local_inference_backend"] = backend
    config["local_inference_model"] = str(
        field_value("local_inference_model") or ""
    ).strip()
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
        elif server_id == "memory":
            environment["MEMORY_BACKEND"] = resolve_memory_backend(config)
        elif server_id == "local-inference":
            _backend, base_url = resolve_local_inference_backend(config)
            environment["SANPOLOID_LOCAL_LLM_BASE_URL"] = base_url
            model = str(config.get("local_inference_model", "")).strip()
            if model:
                environment["SANPOLOID_LOCAL_LLM_MODEL"] = model
        arguments = [
            "run",
            "--directory",
            str(repo_path / component.project_directory),
        ]
        if server_id == "memory" and environment["MEMORY_BACKEND"] == "chroma":
            arguments.extend(("--extra", "chroma"))
        arguments.append(component.executable)
        servers[server_id] = {
            "type": "stdio",
            "command": "uv",
            "args": arguments,
            "env": environment,
        }
    return {"mcpServers": servers}
