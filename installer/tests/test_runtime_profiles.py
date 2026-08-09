"""Tests for the installer runtime-profile domain model."""

import json
import tomllib
from pathlib import Path

from installer.runtime_profiles import (
    COMPONENTS,
    DependencyProject,
    RuntimeProfile,
    action_gate_matcher,
    build_mcp_config,
    dependency_projects,
    enabled_server_ids,
    infer_runtime_profile,
    profile_component_flags,
    profile_server_ids,
    required_host_dependencies,
    runtime_config_from_fields,
)


def test_profiles_make_the_weight_tradeoff_explicit() -> None:
    assert profile_server_ids(RuntimeProfile.LITE) == (
        "memory",
        "system-temperature",
    )
    assert profile_server_ids(RuntimeProfile.CORE) == (
        "wifi-cam",
        "memory",
        "system-temperature",
    )
    assert profile_server_ids(RuntimeProfile.FULL) == (
        "wifi-cam",
        "usb-webcam",
        "memory",
        "system-temperature",
        "local-inference",
        "elevenlabs-t2s",
    )


def test_explicit_component_choices_override_a_named_profile() -> None:
    config = {
        "runtime_profile": "core",
        "wifi_camera_enabled": False,
        "memory_enabled": False,
        "system_temperature_enabled": True,
        "elevenlabs_enabled": True,
    }

    assert enabled_server_ids(config) == (
        "system-temperature",
        "elevenlabs-t2s",
    )


def test_profile_flags_and_inference_share_the_component_registry() -> None:
    flags = profile_component_flags(RuntimeProfile.LITE)

    assert flags == {
        "wifi_camera_enabled": False,
        "usb_camera_enabled": False,
        "memory_enabled": True,
        "system_temperature_enabled": True,
        "local_inference_enabled": False,
        "elevenlabs_enabled": False,
    }
    assert infer_runtime_profile(flags) is RuntimeProfile.LITE
    assert infer_runtime_profile({**flags, "memory_backend": "chroma"}) is RuntimeProfile.CUSTOM


def test_lite_does_not_require_media_tooling() -> None:
    assert required_host_dependencies({"runtime_profile": "lite"}) == (
        "Python",
        "uv",
    )


def test_runtime_config_reads_wizard_fields_in_one_place() -> None:
    fields = {
        "runtime_profile": "Lite",
        "wifi_camera_enabled": False,
        "usb_camera_enabled": False,
        "memory_enabled": True,
        "memory_backend": "SQLite FTS (lightweight)",
        "system_temperature_enabled": True,
        "local_inference_enabled": False,
        "elevenlabs_enabled": False,
        "tapo_host": " 192.0.2.10 ",
        "tapo_username": " camera-user ",
        "tapo_password": " camera-password ",
        "local_inference_backend": "LM Studio (127.0.0.1:1234)",
        "local_inference_model": " local-jp ",
    }

    assert runtime_config_from_fields(fields.get) == {
        **profile_component_flags(RuntimeProfile.LITE),
        "runtime_profile": "lite",
        "memory_backend": "sqlite",
        "tapo_host": "192.0.2.10",
        "tapo_username": "camera-user",
        "tapo_password": "camera-password",
        "local_inference_backend": "lmstudio",
        "local_inference_model": "local-jp",
    }
    assert required_host_dependencies({"runtime_profile": "full"}) == (
        "ffmpeg",
        "Python",
        "uv",
    )


def test_lite_profile_syncs_memory_without_chroma_extra() -> None:
    assert dependency_projects(Path("/repo"), {"runtime_profile": "lite"}) == [
        DependencyProject("action-policy", Path("/repo/action-policy")),
        DependencyProject("memory-mcp", Path("/repo/memory-mcp")),
        DependencyProject(
            "system-temperature-mcp", Path("/repo/system-temperature-mcp")
        ),
    ]
    memory = build_mcp_config(Path("/repo"), {"runtime_profile": "lite"})[
        "mcpServers"
    ]["memory"]
    assert "--extra" not in memory["args"]


def test_core_profile_installs_chroma_as_an_explicit_extra() -> None:
    projects = dependency_projects(Path("/repo"), {"runtime_profile": "core"})

    memory = next(project for project in projects if project.name == "memory-mcp")
    assert memory.extras == ("chroma",)


def test_full_profile_builds_every_mcp_server_without_collecting_api_keys() -> None:
    config = build_mcp_config(
        Path("/repo"),
        {
            "runtime_profile": "full",
            "tapo_host": "192.0.2.10",
            "tapo_username": "camera-user",
            "tapo_password": "camera-password",
        },
    )

    assert tuple(config["mcpServers"]) == profile_server_ids(RuntimeProfile.FULL)
    assert config["mcpServers"]["memory"]["env"] == {
        "MEMORY_BACKEND": "chroma"
    }
    assert config["mcpServers"]["memory"]["args"] == [
        "run",
        "--directory",
        str(Path("/repo/memory-mcp")),
        "--extra",
        "chroma",
        "memory-mcp",
    ]
    assert "ELEVENLABS_API_KEY" not in config["mcpServers"]["elevenlabs-t2s"]["env"]
    assert config["mcpServers"]["elevenlabs-t2s"]["env"] == {
        "GO2RTC_URL": "http://127.0.0.1:1984",
        "GO2RTC_STREAM": "tapo_cam",
        "ELEVENLABS_PLAYBACK": "none",
    }
    assert config["mcpServers"]["local-inference"]["env"] == {
        "SANPOLOID_LOCAL_LLM_BASE_URL": "http://127.0.0.1:1234/v1"
    }


def test_local_inference_backend_projects_only_fixed_loopback_endpoints() -> None:
    lm_studio = build_mcp_config(
        Path("/repo"),
        {
            "runtime_profile": "custom",
            "local_inference_enabled": True,
            "local_inference_backend": "LM Studio (127.0.0.1:1234)",
            "local_inference_model": "local-jp",
        },
    )["mcpServers"]["local-inference"]
    llama_cpp = build_mcp_config(
        Path("/repo"),
        {
            "runtime_profile": "custom",
            "local_inference_enabled": True,
            "local_inference_backend": "llama.cpp (127.0.0.1:8080)",
        },
    )["mcpServers"]["local-inference"]

    assert lm_studio["env"] == {
        "SANPOLOID_LOCAL_LLM_BASE_URL": "http://127.0.0.1:1234/v1",
        "SANPOLOID_LOCAL_LLM_MODEL": "local-jp",
    }
    assert llama_cpp["env"] == {
        "SANPOLOID_LOCAL_LLM_BASE_URL": "http://127.0.0.1:8080/v1"
    }


def test_action_gate_always_covers_every_managed_component() -> None:
    matcher = action_gate_matcher()

    assert matcher == (
        "mcp__wifi-cam__.*|mcp__usb-webcam__.*|mcp__memory__.*|"
        "mcp__system-temperature__.*|mcp__local-inference__.*|"
        "mcp__elevenlabs-t2s__.*"
    )


def test_repository_mcp_config_is_the_full_profile_projection() -> None:
    repo_root = Path(__file__).parents[2]
    committed = json.loads((repo_root / ".mcp.json").read_text(encoding="utf-8"))

    assert committed == build_mcp_config(Path("."), {"runtime_profile": "full"})


def test_component_registry_points_to_real_console_scripts() -> None:
    repo_root = Path(__file__).parents[2]

    for component in COMPONENTS:
        project = repo_root / component.project_directory
        metadata = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))

        assert project.is_dir()
        assert component.executable in metadata["project"]["scripts"]
