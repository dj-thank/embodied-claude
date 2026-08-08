"""Hardware-free tests for USB webcam helpers."""

import threading

import pytest

from usb_webcam_mcp import server as webcam_server


@pytest.mark.parametrize("options", [(0, 0, None), (-1, None, None), (0, 1, 9000)])
def test_capture_options_reject_invalid_values(options: tuple[object, object, object]) -> None:
    with pytest.raises(ValueError):
        webcam_server._validate_capture_options(*options)  # type: ignore[arg-type]


def test_capture_from_camera_releases_closed_camera(monkeypatch: pytest.MonkeyPatch) -> None:
    class ClosedCamera:
        released = False

        def isOpened(self) -> bool:  # noqa: N802 - mirrors the OpenCV API
            return False

        def release(self) -> None:
            self.released = True

    camera = ClosedCamera()
    monkeypatch.setattr(webcam_server.cv2, "VideoCapture", lambda _: camera)

    with pytest.raises(RuntimeError, match="Cannot open camera"):
        webcam_server.capture_from_camera()

    assert camera.released


@pytest.mark.asyncio
async def test_call_tool_captures_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webcam_server, "capture_from_camera", lambda *_: b"jpeg")

    result = await webcam_server.call_tool("see", {})

    assert len(result) == 1
    assert result[0].type == "image"


@pytest.mark.asyncio
async def test_list_cameras_offloads_device_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_find_available_cameras() -> list[dict[str, int]]:
        assert threading.current_thread() is not threading.main_thread()
        return [{"index": 0, "width": 640, "height": 480}]

    monkeypatch.setattr(webcam_server, "find_available_cameras", fake_find_available_cameras)

    result = await webcam_server.call_tool("list_cameras", {})

    assert result[0].text == "Available cameras:\n  - Index 0: 640x480"
