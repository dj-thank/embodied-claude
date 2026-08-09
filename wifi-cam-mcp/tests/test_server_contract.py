"""Public MCP contract tests for Wi-Fi camera tools."""

import os
import sys

import pytest
from mcp import Client, StdioServerParameters, stdio_client

from wifi_cam_mcp.camera import CaptureResult, Direction, MoveResult
from wifi_cam_mcp.server import CameraMCPServer

BASE_TOOL_NAMES = [
    "see",
    "look_left",
    "look_right",
    "look_up",
    "look_down",
    "look_around",
    "camera_info",
    "camera_presets",
    "camera_go_to_preset",
    "listen",
]

STEREO_TOOL_NAMES = [
    "see_right",
    "see_both",
    "right_eye_look_left",
    "right_eye_look_right",
    "right_eye_look_up",
    "right_eye_look_down",
    "both_eyes_look_left",
    "both_eyes_look_right",
    "both_eyes_look_up",
    "both_eyes_look_down",
    "get_eye_positions",
    "align_eyes",
    "reset_eye_positions",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_typed_registry_exposes_base_tools_without_stereo_hardware(mode: str) -> None:
    application = CameraMCPServer()

    async with Client(application.mcp, mode=mode) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == BASE_TOOL_NAMES
    movement_schema = next(
        tool.input_schema for tool in tools.tools if tool.name == "look_left"
    )
    assert movement_schema["properties"]["degrees"]["minimum"] == 1
    assert movement_schema["properties"]["degrees"]["maximum"] == 90


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_movement_failure_is_an_mcp_error_without_credentials(mode: str) -> None:
    class FailingCamera:
        async def pan_left(self, degrees: int) -> MoveResult:
            return MoveResult(
                Direction.LEFT,
                degrees,
                False,
                "RTSP failed at rtsp://camera-user:camera-secret@camera.local/live",
            )

    application = CameraMCPServer(camera=FailingCamera())

    async with Client(application.mcp, mode=mode) as client:
        result = await client.call_tool("look_left", {"degrees": 30})

    assert result.is_error is True
    assert "camera-secret" not in result.content[0].text
    assert "rtsp://camera-user:<redacted>@camera.local/live" in result.content[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_see_returns_the_camera_jpeg_contract(mode: str) -> None:
    class FakeCaptureCamera:
        async def capture_image(self) -> CaptureResult:
            return CaptureResult(
                image_base64="ZmFrZS1qcGVn",
                file_path=None,
                timestamp="20260809_120000_000000",
                width=640,
                height=480,
            )

    application = CameraMCPServer(camera=FakeCaptureCamera())

    async with Client(application.mcp, mode=mode) as client:
        result = await client.call_tool("see", {})

    assert result.is_error is False
    assert result.content[0].type == "image"
    assert result.content[0].mime_type == "image/jpeg"
    assert result.content[0].data == "ZmFrZS1qcGVn"
    assert result.content[1].text == (
        "Captured image at 20260809_120000_000000 (640x480)"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_stereo_configuration_exposes_all_23_tools(mode: str) -> None:
    application = CameraMCPServer(camera=object(), camera_right=object())

    async with Client(application.mcp, mode=mode) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == BASE_TOOL_NAMES + STEREO_TOOL_NAMES


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_typed_registry_rejects_invalid_motion_and_listen_ranges(mode: str) -> None:
    application = CameraMCPServer()

    async with Client(application.mcp, mode=mode) as client:
        invalid_motion = await client.call_tool("look_left", {"degrees": 0})
        invalid_duration = await client.call_tool("listen", {"duration": 31})

    assert invalid_motion.is_error is True
    assert invalid_duration.is_error is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_stdio_initializes_while_the_configured_camera_is_offline(
    mode: str,
    tmp_path,
) -> None:
    env = os.environ.copy()
    env.update(
        {
            "TAPO_CAMERA_HOST": "127.0.0.1",
            "TAPO_USERNAME": "test-user",
            "TAPO_PASSWORD": "test-password",
            "TAPO_ONVIF_PORT": "1",
            "CAPTURE_DIR": str(tmp_path),
        }
    )
    env.pop("TAPO_RIGHT_CAMERA_HOST", None)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "wifi_cam_mcp.server"],
        env=env,
    )

    async with Client(stdio_client(parameters), mode=mode) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == BASE_TOOL_NAMES
