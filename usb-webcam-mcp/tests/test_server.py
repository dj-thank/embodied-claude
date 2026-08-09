"""Hardware-free tests for USB webcam helpers."""

import base64
import os
import sys
import threading

import pytest
from mcp import Client, StdioServerParameters, stdio_client

from usb_webcam_mcp import server as webcam_server


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_typed_registry_lists_cameras_without_blocking_the_event_loop(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_find_available_cameras() -> list[dict[str, int]]:
        assert threading.current_thread() is not threading.main_thread()
        return [{"index": 0, "width": 640, "height": 480}]

    monkeypatch.setattr(webcam_server, "find_available_cameras", fake_find_available_cameras)

    async with Client(webcam_server.mcp, mode=mode) as client:
        tools = await client.list_tools()
        result = await client.call_tool("list_cameras", {})

    assert [tool.name for tool in tools.tools] == ["list_cameras", "see"]
    assert result.is_error is False
    assert result.content[0].text == "Available cameras:\n  - Index 0: 640x480"


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
    monkeypatch.setattr(webcam_server.cv2, "VideoCapture", lambda *_: camera)

    with pytest.raises(RuntimeError, match="Cannot open camera"):
        webcam_server.capture_from_camera()

    assert camera.released


@pytest.mark.skipif(os.name != "nt", reason="DirectShow is Windows-only")
def test_windows_camera_scan_uses_directshow_and_releases_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_with: list[tuple[int, int]] = []

    class ClosedCamera:
        released = False

        def isOpened(self) -> bool:  # noqa: N802 - mirrors the OpenCV API
            return False

        def release(self) -> None:
            self.released = True

    camera = ClosedCamera()

    def open_camera(index: int, backend: int) -> ClosedCamera:
        opened_with.append((index, backend))
        return camera

    monkeypatch.setattr(webcam_server.cv2, "VideoCapture", open_camera)

    assert webcam_server.find_available_cameras(max_cameras=1) == []
    assert opened_with == [(0, webcam_server.cv2.CAP_DSHOW)]
    assert camera.released is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_typed_capture_returns_jpeg_off_the_event_loop(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_capture(camera_index: int, width: int | None, height: int | None) -> bytes:
        assert threading.current_thread() is not threading.main_thread()
        assert (camera_index, width, height) == (2, 640, 480)
        return b"jpeg"

    monkeypatch.setattr(webcam_server, "capture_from_camera", fake_capture)

    async with Client(webcam_server.mcp, mode=mode) as client:
        tools = await client.list_tools()
        result = await client.call_tool(
            "see",
            {"camera_index": 2, "width": 640, "height": 480},
        )

    see_tool = next(tool for tool in tools.tools if tool.name == "see")
    assert see_tool.input_schema["properties"]["camera_index"]["minimum"] == 0
    assert see_tool.input_schema["properties"]["width"]["anyOf"][0] == {
        "maximum": webcam_server.MAX_IMAGE_DIMENSION,
        "minimum": 1,
        "type": "integer",
    }
    assert result.is_error is False
    assert result.content[0].type == "image"
    assert result.content[0].mime_type == "image/jpeg"
    assert base64.b64decode(result.content[0].data) == b"jpeg"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_capture_failure_is_an_mcp_error_without_losing_diagnostics(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_camera(*_args: object) -> bytes:
        raise RuntimeError("Cannot open camera at index 7")

    monkeypatch.setattr(webcam_server, "capture_from_camera", unavailable_camera)

    async with Client(webcam_server.mcp, mode=mode) as client:
        runtime_error = await client.call_tool("see", {"camera_index": 7})
        validation_error = await client.call_tool("see", {"width": 0})

    assert runtime_error.is_error is True
    assert runtime_error.content[0].text == "Error: Cannot open camera at index 7"
    assert validation_error.is_error is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_stdio_process_exposes_the_same_typed_tools(mode: str) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "usb_webcam_mcp.server"],
    )

    async with Client(stdio_client(parameters), mode=mode) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == ["list_cameras", "see"]
