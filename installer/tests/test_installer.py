"""Hardware-free tests for installer configuration and page logic."""

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from installer.pages.camera import CameraSelectionPage
from installer.pages.install import InstallationWorker


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Create the application object required by Qt widgets."""
    return QApplication.instance() or QApplication([])


def test_camera_page_allows_memory_without_camera(qapp: QApplication) -> None:
    page = CameraSelectionPage()

    assert not page.isComplete()
    page.use_wifi_camera.setChecked(False)
    assert page.isComplete()

    page.use_memory.setChecked(False)
    assert not page.isComplete()


def test_create_mcp_config_uses_valid_uv_arguments() -> None:
    worker = InstallationWorker(
        {
            "wifi_camera_enabled": True,
            "tapo_host": "192.0.2.10",
            "tapo_username": "camera-user",
            "tapo_password": "camera-password",
            "usb_camera_enabled": True,
            "memory_enabled": True,
        }
    )

    config = worker._create_mcp_config(Path("/repo"))

    assert set(config["mcpServers"]) == {
        "wifi-cam",
        "usb-webcam",
        "memory",
        "system-temperature",
    }
    for server in config["mcpServers"].values():
        assert server["args"][0] == "run"
        assert server["args"][1] == "--directory"


def test_update_claude_settings_preserves_existing_values(tmp_path: Path) -> None:
    worker = InstallationWorker({})
    settings_path = tmp_path / "claude.json"
    settings_path.write_text(json.dumps({"existing": True}), encoding="utf-8")

    worker._update_claude_settings(
        settings_path,
        {"mcpServers": {"memory": {"command": "uv"}}},
    )

    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["existing"] is True
    assert saved["mcpServers"]["memory"]["command"] == "uv"
