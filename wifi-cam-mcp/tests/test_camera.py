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


@pytest.mark.asyncio
async def test_move_reconnects_after_transient_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = TapoCamera(_config())
    relative_move_calls = 0
    ensure_connected_calls = 0

    class FlakyPtzService:
        async def RelativeMove(self, request: dict[str, object]) -> None:  # noqa: N802
            nonlocal relative_move_calls
            relative_move_calls += 1
            if relative_move_calls == 1:
                raise TimeoutError("ONVIF connection timeout")

    service = FlakyPtzService()
    camera._connected = True
    camera._cam = object()
    camera._ptz_service = service
    camera._profile_token = "profile-1"

    async def fake_ensure_connected() -> None:
        nonlocal ensure_connected_calls
        ensure_connected_calls += 1
        camera._connected = True
        camera._cam = object()
        camera._ptz_service = service

    async def no_sleep(delay: float) -> None:
        return None

    camera._ensure_connected = fake_ensure_connected  # type: ignore[method-assign]
    monkeypatch.setattr("wifi_cam_mcp.camera.asyncio.sleep", no_sleep)

    result = await camera.move(Direction.LEFT, 30)

    assert result.success is True
    assert relative_move_calls == 2
    assert ensure_connected_calls == 2
    assert camera.get_position().pan == -30


@pytest.mark.asyncio
async def test_device_info_failure_is_redacted_and_propagated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    camera = TapoCamera(_config())

    class FailingDeviceService:
        async def GetDeviceInformation(self) -> None:  # noqa: N802
            raise RuntimeError(
                "ONVIF failed at rtsp://camera-user:camera-secret@camera.local/live"
            )

    camera._connected = True
    camera._cam = object()
    camera._devicemgmt_service = FailingDeviceService()
    caplog.set_level("ERROR", logger="wifi_cam_mcp.camera")

    with pytest.raises(RuntimeError, match="ONVIF failed") as error:
        await camera.get_device_info()

    assert "camera-secret" not in str(error.value)
    assert "rtsp://camera-user:<redacted>@camera.local/live" in str(error.value)
    assert "camera-secret" not in caplog.text


@pytest.mark.asyncio
async def test_move_returns_redacted_failure_after_reconnect_is_exhausted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    camera = TapoCamera(_config())
    relative_move_calls = 0
    ensure_connected_calls = 0

    class FailingPtzService:
        async def RelativeMove(self, request: dict[str, object]) -> None:  # noqa: N802
            nonlocal relative_move_calls
            relative_move_calls += 1
            raise TimeoutError(
                "RTSP timeout at rtsp://camera-user:camera-password@camera.local/live"
            )

    service = FailingPtzService()
    camera._connected = True
    camera._cam = object()
    camera._ptz_service = service
    camera._profile_token = "profile-1"

    async def fake_ensure_connected() -> None:
        nonlocal ensure_connected_calls
        ensure_connected_calls += 1
        camera._connected = True
        camera._cam = object()
        camera._ptz_service = service

    camera._ensure_connected = fake_ensure_connected  # type: ignore[method-assign]
    caplog.set_level("WARNING", logger="wifi_cam_mcp.camera")

    result = await camera.move(Direction.RIGHT, 120)

    assert result.success is False
    assert result.degrees == 90
    assert relative_move_calls == 2
    assert ensure_connected_calls == 2
    assert camera.get_position().pan == 0
    assert "camera-password" not in result.message
    assert "rtsp://camera-user:<redacted>@camera.local/live" in result.message
    assert "camera-password" not in caplog.text
    assert "rtsp://camera-user:<redacted>@camera.local/live" in caplog.text
