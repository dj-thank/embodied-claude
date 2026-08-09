"""MCP Server for Wi-Fi camera control."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from functools import wraps
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import Field

from .camera import (
    CaptureResult,
    MoveResult,
    TapoCamera,
    _normalize_duration,
    _redact_credentials,
)
from .config import CameraConfig, ServerConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Degrees = Annotated[
    int,
    Field(ge=1, le=90, description="Movement in degrees (1-90)"),
]
ListenDuration = Annotated[
    float,
    Field(ge=1, le=30, description="Listening duration in seconds (1-30)"),
]
PresetId = Annotated[
    str,
    Field(min_length=1, max_length=256, description="Saved camera preset ID"),
]


def _error_result(message: str) -> CallToolResult:
    """Return one redacted MCP tool error."""
    return CallToolResult(
        isError=True,
        content=[TextContent(type="text", text=f"Error: {message}")],
    )


def _mcp_error_boundary(function):
    """Convert camera boundary exceptions to credential-safe MCP errors."""

    @wraps(function)
    async def wrapped(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - MCP boundary must fail closed
            message = _redact_credentials(str(error))
            logger.error("Tool %s failed: %s", function.__name__, message)
            return _error_result(message)

    return wrapped


def _movement_result(result: MoveResult, prefix: str = "") -> str | CallToolResult:
    """Preserve movement diagnostics while exposing failures as MCP errors."""
    message = _redact_credentials(f"{prefix}{result.message}")
    if result.success:
        return message
    return _error_result(message)


def _capture_content(result: CaptureResult, label: str) -> CallToolResult:
    """Build a JPEG-plus-metadata MCP result."""
    return CallToolResult(
        content=[
            ImageContent(
                type="image",
                data=result.image_base64,
                mimeType="image/jpeg",
            ),
            TextContent(
                type="text",
                text=(
                    f"{label} at {result.timestamp} "
                    f"({result.width}x{result.height})"
                ),
            ),
        ]
    )


def _stereo_failure_result(
    left_result: MoveResult, right_result: MoveResult
) -> CallToolResult | None:
    """Return an MCP error when either side of a stereo move fails."""
    if left_result.success and right_result.success:
        return None

    left_status = "success" if left_result.success else "failed"
    right_status = "success" if right_result.success else "failed"
    left_message = _redact_credentials(left_result.message)
    right_message = _redact_credentials(right_result.message)
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=(
                    "Stereo move failed: "
                    f"left={left_status} ({left_message}); "
                    f"right={right_status} ({right_message})"
                ),
            )
        ],
        isError=True,
    )


class CameraMCPServer:
    """MCP server that gives an AI one or two local-network camera eyes."""

    def __init__(
        self,
        camera: TapoCamera | None = None,
        camera_right: TapoCamera | None = None,
    ) -> None:
        self._server_config = ServerConfig.from_env()
        self.mcp = MCPServer(
            self._server_config.name,
            version=self._server_config.version,
        )
        self._camera = camera
        self._camera_right = camera_right
        self._has_stereo = camera_right is not None
        self._stereo_tools_registered = False
        self._setup_base_tools()
        if self._has_stereo:
            self._setup_stereo_tools()

    def _primary_camera(self) -> TapoCamera:
        if self._camera is None:
            raise RuntimeError("Camera not connected")
        return self._camera

    def _right_camera(self) -> TapoCamera:
        if self._camera_right is None:
            raise RuntimeError("Right camera not configured")
        return self._camera_right

    def _setup_base_tools(self) -> None:
        """Register tools available with the primary camera."""

        @self.mcp.tool(
            name="see",
            description=(
                "Capture the current view from the primary camera. Returns a JPEG image."
            ),
            structured_output=False,
        )
        @_mcp_error_boundary
        async def see() -> CallToolResult:
            result = await self._primary_camera().capture_image()
            return _capture_content(result, "Captured image")

        @self.mcp.tool(
            name="look_left",
            description="Turn the primary camera left.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def look_left(degrees: Degrees = 30) -> str | CallToolResult:
            return _movement_result(await self._primary_camera().pan_left(degrees))

        @self.mcp.tool(
            name="look_right",
            description="Turn the primary camera right.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def look_right(degrees: Degrees = 30) -> str | CallToolResult:
            return _movement_result(await self._primary_camera().pan_right(degrees))

        @self.mcp.tool(
            name="look_up",
            description="Tilt the primary camera up.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def look_up(degrees: Degrees = 20) -> str | CallToolResult:
            return _movement_result(await self._primary_camera().tilt_up(degrees))

        @self.mcp.tool(
            name="look_down",
            description="Tilt the primary camera down.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def look_down(degrees: Degrees = 20) -> str | CallToolResult:
            return _movement_result(await self._primary_camera().tilt_down(degrees))

        @self.mcp.tool(
            name="look_around",
            description=(
                "Survey the surroundings at center, left, right, and up, then return "
                "the camera to center."
            ),
            structured_output=False,
        )
        @_mcp_error_boundary
        async def look_around() -> CallToolResult:
            captures = await self._primary_camera().look_around()
            content: list[TextContent | ImageContent] = []
            directions = ["Center", "Left", "Right", "Up"]
            for index, capture in enumerate(captures):
                direction = (
                    directions[index] if index < len(directions) else f"Angle {index}"
                )
                content.extend(
                    [
                        TextContent(type="text", text=f"--- {direction} View ---"),
                        ImageContent(
                            type="image",
                            data=capture.image_base64,
                            mimeType="image/jpeg",
                        ),
                    ]
                )
            content.append(
                TextContent(
                    type="text",
                    text=(
                        f"Captured {len(captures)} angles. "
                        "Camera returned to center position."
                    ),
                )
            )
            return CallToolResult(content=content)

        @self.mcp.tool(
            name="camera_info",
            description="Get information about the primary camera device.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def camera_info() -> str:
            info = await self._primary_camera().get_device_info()
            return f"Camera Info:\n{json.dumps(info, indent=2, ensure_ascii=False)}"

        @self.mcp.tool(
            name="camera_presets",
            description="List saved primary-camera position presets.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def camera_presets() -> str:
            presets = await self._primary_camera().get_presets()
            return f"Camera Presets:\n{json.dumps(presets, indent=2, ensure_ascii=False)}"

        @self.mcp.tool(
            name="camera_go_to_preset",
            description="Move the primary camera to a saved preset position.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def camera_go_to_preset(preset_id: PresetId) -> str | CallToolResult:
            preset_id = preset_id.strip()
            if not preset_id:
                return _error_result("preset_id is required")
            return _movement_result(
                await self._primary_camera().go_to_preset(preset_id)
            )

        @self.mcp.tool(
            name="listen",
            description=(
                "Record audio from the primary camera microphone and optionally "
                "transcribe it locally with Whisper."
            ),
            structured_output=False,
        )
        @_mcp_error_boundary
        async def listen(
            duration: ListenDuration = 5,
            transcribe: bool = True,
        ) -> str:
            duration = _normalize_duration(duration)
            result = await self._primary_camera().listen_audio(duration, transcribe)
            response = (
                f"Recorded {result.duration}s of audio at {result.timestamp}\n"
                f"Audio file: {result.file_path}\n"
            )
            if result.transcript:
                response += f"\n--- Transcript ---\n{result.transcript}"
            return response

    def _setup_stereo_tools(self) -> None:
        """Register tools that require a connected right camera exactly once."""
        if self._stereo_tools_registered:
            return

        @self.mcp.tool(
            name="see_right",
            description="Capture the current view from the right camera.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def see_right() -> CallToolResult:
            result = await self._right_camera().capture_image()
            return _capture_content(result, "Right eye captured")

        @self.mcp.tool(
            name="see_both",
            description="Capture both camera views concurrently for stereo comparison.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def see_both() -> CallToolResult:
            left, right = await asyncio.gather(
                self._primary_camera().capture_image(),
                self._right_camera().capture_image(),
            )
            return CallToolResult(
                content=[
                    TextContent(type="text", text="--- Left Eye ---"),
                    ImageContent(
                        type="image",
                        data=left.image_base64,
                        mimeType="image/jpeg",
                    ),
                    TextContent(type="text", text="--- Right Eye ---"),
                    ImageContent(
                        type="image",
                        data=right.image_base64,
                        mimeType="image/jpeg",
                    ),
                    TextContent(
                        type="text",
                        text=(
                            f"Stereo capture at {left.timestamp} "
                            f"(L: {left.width}x{left.height}, "
                            f"R: {right.width}x{right.height})"
                        ),
                    ),
                ]
            )

        @self.mcp.tool(
            name="right_eye_look_left",
            description="Turn the right camera left.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def right_eye_look_left(degrees: Degrees = 30) -> str | CallToolResult:
            return _movement_result(
                await self._right_camera().pan_left(degrees), "Right eye: "
            )

        @self.mcp.tool(
            name="right_eye_look_right",
            description="Turn the right camera right.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def right_eye_look_right(degrees: Degrees = 30) -> str | CallToolResult:
            return _movement_result(
                await self._right_camera().pan_right(degrees), "Right eye: "
            )

        @self.mcp.tool(
            name="right_eye_look_up",
            description="Tilt the right camera up.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def right_eye_look_up(degrees: Degrees = 20) -> str | CallToolResult:
            return _movement_result(
                await self._right_camera().tilt_up(degrees), "Right eye: "
            )

        @self.mcp.tool(
            name="right_eye_look_down",
            description="Tilt the right camera down.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def right_eye_look_down(degrees: Degrees = 20) -> str | CallToolResult:
            return _movement_result(
                await self._right_camera().tilt_down(degrees), "Right eye: "
            )

        @self.mcp.tool(
            name="both_eyes_look_left",
            description="Turn both cameras left concurrently.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def both_eyes_look_left(degrees: Degrees = 30) -> str | CallToolResult:
            return await self._move_both(
                "pan_left", degrees, f"Both eyes moved left by {degrees} degrees"
            )

        @self.mcp.tool(
            name="both_eyes_look_right",
            description="Turn both cameras right concurrently.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def both_eyes_look_right(degrees: Degrees = 30) -> str | CallToolResult:
            return await self._move_both(
                "pan_right", degrees, f"Both eyes moved right by {degrees} degrees"
            )

        @self.mcp.tool(
            name="both_eyes_look_up",
            description="Tilt both cameras up concurrently.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def both_eyes_look_up(degrees: Degrees = 20) -> str | CallToolResult:
            return await self._move_both(
                "tilt_up", degrees, f"Both eyes tilted up by {degrees} degrees"
            )

        @self.mcp.tool(
            name="both_eyes_look_down",
            description="Tilt both cameras down concurrently.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def both_eyes_look_down(degrees: Degrees = 20) -> str | CallToolResult:
            return await self._move_both(
                "tilt_down", degrees, f"Both eyes tilted down by {degrees} degrees"
            )

        @self.mcp.tool(
            name="get_eye_positions",
            description="Get software-tracked pan and tilt positions for both cameras.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def get_eye_positions() -> str:
            left = self._primary_camera().get_position()
            right = self._right_camera().get_position()
            return (
                f"Left eye:  pan={left.pan:+.0f}deg, tilt={left.tilt:+.0f}deg\n"
                f"Right eye: pan={right.pan:+.0f}deg, tilt={right.tilt:+.0f}deg\n"
                f"Difference: pan={left.pan - right.pan:+.0f}deg, "
                f"tilt={left.tilt - right.tilt:+.0f}deg"
            )

        @self.mcp.tool(
            name="align_eyes",
            description="Move the right camera to its software-tracked left-camera position.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def align_eyes() -> str | CallToolResult:
            left = self._primary_camera().get_position()
            right_camera = self._right_camera()
            right = right_camera.get_position()
            pan_difference = left.pan - right.pan
            tilt_difference = left.tilt - right.tilt
            messages: list[str] = []

            if pan_difference > 0:
                result = await right_camera.pan_right(pan_difference)
                if not result.success:
                    return _movement_result(result, "Right eye: ")
                messages.append(f"Right eye panned right by {pan_difference}°")
            elif pan_difference < 0:
                result = await right_camera.pan_left(-pan_difference)
                if not result.success:
                    return _movement_result(result, "Right eye: ")
                messages.append(f"Right eye panned left by {-pan_difference}°")

            if tilt_difference > 0:
                result = await right_camera.tilt_up(tilt_difference)
                if not result.success:
                    return _movement_result(result, "Right eye: ")
                messages.append(f"Right eye tilted up by {tilt_difference}°")
            elif tilt_difference < 0:
                result = await right_camera.tilt_down(-tilt_difference)
                if not result.success:
                    return _movement_result(result, "Right eye: ")
                messages.append(f"Right eye tilted down by {-tilt_difference}°")

            if not messages:
                return "Eyes already aligned!"
            return "Aligned eyes: " + ", ".join(messages)

        @self.mcp.tool(
            name="reset_eye_positions",
            description="Reset software position tracking for both cameras to zero.",
            structured_output=False,
        )
        @_mcp_error_boundary
        async def reset_eye_positions() -> str:
            self._primary_camera().reset_position_tracking()
            self._right_camera().reset_position_tracking()
            return "Both eyes position tracking reset to (0, 0)"

        self._stereo_tools_registered = True

    async def _move_both(
        self,
        method_name: str,
        degrees: int,
        success_message: str,
    ) -> str | CallToolResult:
        left_operation = getattr(self._primary_camera(), method_name)
        right_operation = getattr(self._right_camera(), method_name)
        left, right = await asyncio.gather(
            left_operation(degrees),
            right_operation(degrees),
        )
        failure = _stereo_failure_result(left, right)
        return failure or success_message

    def _configure_cameras(self) -> None:
        """Create lazy camera clients without performing network I/O."""
        if self._camera is None:
            config = CameraConfig.from_env()
            self._camera = TapoCamera(config, self._server_config.capture_dir)
            logger.info("Configured left/primary camera at %s", config.host)

        right_config = CameraConfig.right_camera_from_env()
        if right_config and self._camera_right is None:
            self._camera_right = TapoCamera(
                right_config,
                self._server_config.capture_dir,
            )
            self._has_stereo = True
            self._setup_stereo_tools()
            logger.info("Configured right camera at %s", right_config.host)

    async def connect_camera(self) -> None:
        """Eagerly connect configured cameras when explicitly requested."""
        self._configure_cameras()
        await self._primary_camera().connect()
        logger.info("Connected to left/primary camera")

        if self._camera_right:
            try:
                await self._camera_right.connect()
                self._has_stereo = True
                logger.info("Connected to right camera (stereo vision enabled)")
            except Exception as error:  # noqa: BLE001 - optional stereo fallback
                message = _redact_credentials(str(error))
                logger.warning("Failed to connect right camera: %s", message)

    async def disconnect_camera(self) -> None:
        """Disconnect from configured cameras."""
        if self._camera:
            await self._camera.disconnect()
            self._camera = None
            logger.info("Disconnected from left/primary camera")

        if self._camera_right:
            await self._camera_right.disconnect()
            self._camera_right = None
            self._has_stereo = False
            logger.info("Disconnected from right camera")

    @asynccontextmanager
    async def run_context(self):
        """Configure lazy cameras for the lifetime of the MCP stdio server."""
        try:
            self._configure_cameras()
            yield
        finally:
            await self.disconnect_camera()

    async def run(self) -> None:
        """Run the MCP server over stdio."""
        async with self.run_context():
            await self.mcp.run_stdio_async()


def main() -> None:
    """Run the Wi-Fi camera MCP server."""
    asyncio.run(CameraMCPServer().run())


if __name__ == "__main__":
    main()
