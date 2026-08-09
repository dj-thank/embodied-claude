"""MCP Server for USB webcam capture."""

import asyncio
import base64
import io
import os
from typing import Annotated, Any

# Suppress OpenCV error messages
os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["OPENCV_VIDEOIO_DEBUG"] = "0"

import cv2
from mcp.server import MCPServer
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image
from pydantic import Field

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except AttributeError:
    # Older supported OpenCV builds may only honor the environment variables above.
    pass

mcp = MCPServer("usb-webcam-mcp")

MAX_IMAGE_DIMENSION = 7680


def _open_camera(camera_index: int):
    """Open a camera with the faster native backend on Windows."""
    if os.name == "nt":
        return cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    return cv2.VideoCapture(camera_index)


def _validate_capture_options(
    camera_index: int,
    width: int | None,
    height: int | None,
) -> None:
    """Validate user-provided camera and image parameters."""
    if isinstance(camera_index, bool) or not isinstance(camera_index, int) or camera_index < 0:
        raise ValueError("camera_index must be a non-negative integer")

    for name, value in (("width", width), ("height", height)):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if not 1 <= value <= MAX_IMAGE_DIMENSION:
            raise ValueError(f"{name} must be between 1 and {MAX_IMAGE_DIMENSION}")


def find_available_cameras(max_cameras: int = 10) -> list[dict[str, Any]]:
    """Find available camera devices."""
    cameras = []
    for i in range(max_cameras):
        cap = _open_camera(i)
        try:
            if cap.isOpened():
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cameras.append(
                    {
                        "index": i,
                        "width": width,
                        "height": height,
                    }
                )
        finally:
            cap.release()
    return cameras


def capture_from_camera(
    camera_index: int = 0,
    width: int | None = None,
    height: int | None = None,
) -> bytes:
    """Capture an image from the specified camera."""
    _validate_capture_options(camera_index, width, height)
    cap = _open_camera(camera_index)

    try:
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera at index {camera_index}")

        if width is not None:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height is not None:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        # Read a few frames to let the camera adjust
        for _ in range(5):
            cap.read()

        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("Failed to capture image from camera")

        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Convert to PIL Image and then to JPEG bytes
        image = Image.fromarray(frame_rgb)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()
    finally:
        cap.release()


@mcp.tool(
    name="list_cameras",
    description=(
        "List available camera devices connected to the system. These cameras serve as "
        "your eyes - your visual perception of the physical world."
    ),
    structured_output=False,
)
async def list_cameras() -> str:
    """List available camera devices without blocking the MCP event loop."""
    cameras = await asyncio.to_thread(find_available_cameras)
    if not cameras:
        return "No cameras found"

    lines = ["Available cameras:"]
    for camera in cameras:
        lines.append(f"  - Index {camera['index']}: {camera['width']}x{camera['height']}")
    return "\n".join(lines)


@mcp.tool(
    name="see",
    description=(
        "Capture an image from a USB webcam. This camera serves as your eyes - your visual "
        "perception of the physical world. Use this tool to see what's happening around you. "
        "Returns the image as base64-encoded JPEG."
    ),
    structured_output=False,
)
async def see(
    camera_index: Annotated[
        int,
        Field(ge=0, description="Camera device index (default: 0)"),
    ] = 0,
    width: Annotated[
        int | None,
        Field(
            ge=1,
            le=MAX_IMAGE_DIMENSION,
            description="Desired image width in pixels (optional)",
        ),
    ] = None,
    height: Annotated[
        int | None,
        Field(
            ge=1,
            le=MAX_IMAGE_DIMENSION,
            description="Desired image height in pixels (optional)",
        ),
    ] = None,
) -> CallToolResult:
    """Capture one JPEG without blocking the MCP event loop."""
    try:
        image_bytes = await asyncio.to_thread(
            capture_from_camera,
            camera_index,
            width,
            height,
        )
    except (RuntimeError, ValueError) as error:
        return CallToolResult(
            isError=True,
            content=[TextContent(type="text", text=f"Error: {error}")],
        )

    return CallToolResult(
        content=[
            ImageContent(
                type="image",
                data=base64.b64encode(image_bytes).decode("ascii"),
                mimeType="image/jpeg",
            )
        ]
    )


def main():
    """Entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
