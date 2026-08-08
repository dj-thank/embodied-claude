"""Tests for Wi-Fi camera configuration parsing."""

import pytest

from wifi_cam_mcp.config import CameraConfig


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAPO_CAMERA_HOST", "192.0.2.10")
    monkeypatch.setenv("TAPO_USERNAME", "camera-user")
    monkeypatch.setenv("TAPO_PASSWORD", "camera-password")


def test_from_env_parses_and_validates_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("TAPO_ONVIF_PORT", "2021")
    monkeypatch.setenv("TAPO_MOUNT_MODE", "CEILING")
    monkeypatch.setenv("CAPTURE_MAX_WIDTH", "1280")
    monkeypatch.setenv("CAPTURE_MAX_HEIGHT", "720")

    config = CameraConfig.from_env()

    assert config.onvif_port == 2021
    assert config.mount_mode == "ceiling"
    assert config.max_width == 1280
    assert config.max_height == 720


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        ("TAPO_ONVIF_PORT", "not-a-port", "must be an integer"),
        ("TAPO_ONVIF_PORT", "70000", "between 1 and 65535"),
        ("TAPO_MOUNT_MODE", "wall", "must be 'normal' or 'ceiling'"),
        ("CAPTURE_MAX_WIDTH", "0", "must be between 1 and 8192"),
    ],
)
def test_from_env_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
    message: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=message):
        CameraConfig.from_env()


def test_right_camera_rejects_invalid_mount_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("TAPO_RIGHT_CAMERA_HOST", "192.0.2.11")
    monkeypatch.setenv("TAPO_RIGHT_MOUNT_MODE", "wall")

    with pytest.raises(ValueError, match="must be 'normal' or 'ceiling'"):
        CameraConfig.right_camera_from_env()


def test_direct_config_rejects_oversized_capture() -> None:
    with pytest.raises(ValueError, match="Capture width must be between 1 and 8192"):
        CameraConfig(
            host="192.0.2.10",
            username="camera-user",
            password="camera-password",
            max_width=8193,
        )
