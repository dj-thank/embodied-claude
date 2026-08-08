"""Hardware-free tests for camera lifecycle and URL handling."""

from pathlib import Path

import pytest

from wifi_cam_mcp.camera import (
    CaptureResult,
    Direction,
    MoveResult,
    TapoCamera,
    _normalize_duration,
    _redact_credentials,
)
from wifi_cam_mcp.config import CameraConfig


def _config() -> CameraConfig:
    return CameraConfig(
        host="192.0.2.10",
        username="camera/user",
        password="p@ss:word",
    )


def test_rtsp_url_quotes_credentials() -> None:
    camera = TapoCamera(_config())

    url = camera._get_rtsp_url()

    assert url == "rtsp://camera%2Fuser:p%40ss%3Aword@192.0.2.10:554/stream1"
    assert "p@ss:word" not in url


def test_redact_credentials_removes_secrets() -> None:
    message = "ffmpeg failed for rtsp://user:secret@192.0.2.10:554/stream1"

    redacted = _redact_credentials(message)

    assert "secret" not in redacted
    assert "rtsp://user:<redacted>@192.0.2.10" in redacted


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, 1.0), (5.5, 5.5), (30, 30.0)],
)
def test_normalize_duration_accepts_supported_range(value: float, expected: float) -> None:
    assert _normalize_duration(value) == expected


@pytest.mark.parametrize("value", [0, 30.1, float("inf"), "not-a-number"])
def test_normalize_duration_rejects_unsupported_values(value: object) -> None:
    with pytest.raises(ValueError, match="duration"):
        _normalize_duration(value)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_look_around_restores_position_when_capture_fails(tmp_path: Path) -> None:
    camera = TapoCamera(_config(), str(tmp_path))
    moves: list[tuple[Direction, int]] = []
    capture_count = 0

    async def fake_move(direction: Direction, degrees: int) -> MoveResult:
        moves.append((direction, degrees))
        return MoveResult(direction, degrees, True, "ok")

    async def fake_capture() -> CaptureResult:
        nonlocal capture_count
        capture_count += 1
        if capture_count == 2:
            raise RuntimeError("capture failed")
        return CaptureResult("image", None, "timestamp", 1, 1)

    camera.move = fake_move  # type: ignore[method-assign]
    camera.capture_image = fake_capture  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="capture failed"):
        await camera.look_around()

    assert moves == [(Direction.LEFT, 45), (Direction.RIGHT, 45)]
