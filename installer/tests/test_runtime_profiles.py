"""Tests for the installer runtime-profile domain model."""

import json
import tomllib
from pathlib import Path

from installer.runtime_profiles import (
    COMPONENTS,
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
    assert profile_server_ids(RuntimeProfile.LITE) == ("system-temperature",)
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
        "memory_enabled": False,
        "system_temperature_enabled": True,
        "elevenlabs_enabled": False,
    }
    assert infer_runtime_profile(flags) is RuntimeProfile.LITE
    assert infer_runtime_profile({**flags, "memory_enabled": True}) is RuntimeProfile.CUSTOM


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
        "memory_enabled": False,
        "system_temperature_enabled": True,
        "elevenlabs_enabled": False,
        "tapo_host": " 192.0.2.10 ",
        "tapo_username": " camera-user ",
        "tapo_password": " camera-password ",
    }

    assert runtime_config_from_fields(fields.get) == {
        **profile_component_flags(RuntimeProfile.LITE),
        "runtime_profile": "lite",
        "tapo_host": "192.0.2.10",
        "tapo_username": "camera-user",
        "tapo_password": "camera-password",
    }
    assert required_host_dependencies({"runtime_profile": "full"}) == (
        "ffmpeg",
        "Python",
        "uv",
    )


def test_lite_profile_syncs_only_policy_and_temperature() -> None:
    assert dependency_projects(Path("/repo"), {"runtime_profile": "lite"}) == [
        ("action-policy", Path("/repo/action-policy")),
        (
            "system-temperature-mcp",
            Path("/repo/system-temperature-mcp"),
        ),
    ]


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
    assert "ELEVENLABS_API_KEY" not in config["mcpServers"]["elevenlabs-t2s"]["env"]
    assert config["mcpServers"]["elevenlabs-t2s"]["env"] == {
        "GO2RTC_URL": "http://127.0.0.1:1984",
        "GO2RTC_STREAM": "tapo_cam",
        "ELEVENLABS_PLAYBACK": "none",
    }


def test_action_gate_always_covers_every_managed_component() -> None:
    matcher = action_gate_matcher()

    assert matcher == (
        "mcp__wifi-cam__.*|mcp__usb-webcam__.*|mcp__memory__.*|"
        "mcp__system-temperature__.*|mcp__elevenlabs-t2s__.*"
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
