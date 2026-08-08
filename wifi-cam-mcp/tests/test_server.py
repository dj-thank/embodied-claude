"""Protocol-level tests for Wi-Fi camera MCP tool outcomes."""

from typing import Any

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from wifi_cam_mcp.camera import Direction, MoveResult
from wifi_cam_mcp.server import CameraMCPServer


class FakeMoveCamera:
    """Hardware-free camera that returns a configured movement outcome."""

    def __init__(self, result: MoveResult) -> None:
        self._result = result

    async def pan_left(self, degrees: int) -> MoveResult:
        return self._result

    async def pan_right(self, degrees: int) -> MoveResult:
        return self._result

    async def tilt_up(self, degrees: int) -> MoveResult:
        return self._result

    async def tilt_down(self, degrees: int) -> MoveResult:
        return self._result


async def call_tool(
    server: CameraMCPServer, name: str, arguments: dict[str, Any]
) -> Any:
    """Call through the registered MCP protocol handler."""
    request = CallToolRequest(
        params=CallToolRequestParams(name=name, arguments=arguments)
    )
    handler = server._server.request_handlers[CallToolRequest]
    return (await handler(request)).root


@pytest.mark.asyncio
async def test_both_eyes_move_reports_partial_failure() -> None:
    server = CameraMCPServer()
    server._has_stereo = True
    server._camera = FakeMoveCamera(
        MoveResult(Direction.LEFT, 30, True, "left eye moved")
    )  # type: ignore[assignment]
    server._camera_right = FakeMoveCamera(
        MoveResult(Direction.LEFT, 30, False, "right motor timeout")
    )  # type: ignore[assignment]

    result = await call_tool(server, "both_eyes_look_left", {"degrees": 30})

    assert result.isError is True
    response = result.content[0].text
    assert "left=success" in response
    assert "right=failed" in response
    assert "right motor timeout" in response
    assert "Both eyes moved" not in response


@pytest.mark.asyncio
async def test_both_eyes_move_right_reports_partial_failure() -> None:
    server = CameraMCPServer()
    server._has_stereo = True
    server._camera = FakeMoveCamera(
        MoveResult(Direction.RIGHT, 45, False, "left motor timeout")
    )  # type: ignore[assignment]
    server._camera_right = FakeMoveCamera(
        MoveResult(Direction.RIGHT, 45, True, "right eye moved")
    )  # type: ignore[assignment]

    result = await call_tool(server, "both_eyes_look_right", {"degrees": 45})

    assert result.isError is True
    response = result.content[0].text
    assert "left=failed" in response
    assert "left motor timeout" in response
    assert "right=success" in response
    assert "Both eyes moved" not in response


@pytest.mark.asyncio
async def test_both_eyes_tilt_up_reports_partial_failure() -> None:
    server = CameraMCPServer()
    server._has_stereo = True
    server._camera = FakeMoveCamera(
        MoveResult(Direction.UP, 20, True, "left eye tilted")
    )  # type: ignore[assignment]
    server._camera_right = FakeMoveCamera(
        MoveResult(Direction.UP, 20, False, "right tilt blocked")
    )  # type: ignore[assignment]

    result = await call_tool(server, "both_eyes_look_up", {"degrees": 20})

    assert result.isError is True
    response = result.content[0].text
    assert "left=success" in response
    assert "right=failed" in response
    assert "right tilt blocked" in response
    assert "Both eyes tilted" not in response


@pytest.mark.asyncio
async def test_both_eyes_tilt_down_reports_partial_failure() -> None:
    server = CameraMCPServer()
    server._has_stereo = True
    server._camera = FakeMoveCamera(
        MoveResult(Direction.DOWN, 20, False, "left tilt blocked")
    )  # type: ignore[assignment]
    server._camera_right = FakeMoveCamera(
        MoveResult(Direction.DOWN, 20, True, "right eye tilted")
    )  # type: ignore[assignment]

    result = await call_tool(server, "both_eyes_look_down", {"degrees": 20})

    assert result.isError is True
    response = result.content[0].text
    assert "left=failed" in response
    assert "left tilt blocked" in response
    assert "right=success" in response
    assert "Both eyes tilted" not in response


@pytest.mark.asyncio
async def test_both_eyes_move_preserves_success_contract() -> None:
    server = CameraMCPServer()
    server._has_stereo = True
    server._camera = FakeMoveCamera(
        MoveResult(Direction.LEFT, 30, True, "left eye moved")
    )  # type: ignore[assignment]
    server._camera_right = FakeMoveCamera(
        MoveResult(Direction.LEFT, 30, True, "right eye moved")
    )  # type: ignore[assignment]

    result = await call_tool(server, "both_eyes_look_left", {"degrees": 30})

    assert result.isError is False
    assert result.content[0].text == "Both eyes moved left by 30 degrees"
