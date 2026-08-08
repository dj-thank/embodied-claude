"""Configuration for WiFi Camera MCP Server."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

MAX_CAPTURE_DIMENSION = 8192


def _parse_int_env(
    name: str,
    value: str | None,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Parse and range-check an integer environment variable."""
    raw_value = value or str(default)
    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc

    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _parse_mount_mode(value: str | None, name: str) -> str:
    """Parse the supported camera mounting modes."""
    mount_mode = (value or "normal").strip().lower()
    if mount_mode not in {"normal", "ceiling"}:
        raise ValueError(f"{name} must be 'normal' or 'ceiling'")
    return mount_mode


@dataclass(frozen=True)
class CameraConfig:
    """Camera connection configuration."""

    host: str
    username: str
    password: str
    onvif_port: int = 2020
    stream_url: str | None = None
    max_width: int = 1920
    max_height: int = 1080
    mount_mode: str = "normal"  # "normal" (desktop) or "ceiling" (inverted)

    def __post_init__(self) -> None:
        """Reject invalid values even when a config is constructed directly."""
        if not self.host.strip():
            raise ValueError("Camera host is required")
        if not self.username:
            raise ValueError("Camera username is required")
        if not self.password:
            raise ValueError("Camera password is required")
        if not 1 <= self.onvif_port <= 65535:
            raise ValueError("ONVIF port must be between 1 and 65535")
        if self.mount_mode not in {"normal", "ceiling"}:
            raise ValueError("Mount mode must be 'normal' or 'ceiling'")
        if not 1 <= self.max_width <= MAX_CAPTURE_DIMENSION:
            raise ValueError(f"Capture width must be between 1 and {MAX_CAPTURE_DIMENSION}")
        if not 1 <= self.max_height <= MAX_CAPTURE_DIMENSION:
            raise ValueError(f"Capture height must be between 1 and {MAX_CAPTURE_DIMENSION}")

    @classmethod
    def from_env(cls, prefix: str = "TAPO") -> "CameraConfig":
        """Create config from environment variables.

        Args:
            prefix: Environment variable prefix (default: "TAPO")
                    For right camera, use "TAPO_RIGHT"
        """
        host = os.getenv(f"{prefix}_CAMERA_HOST", "") or os.getenv("TAPO_CAMERA_HOST", "")
        username = os.getenv(f"{prefix}_USERNAME", "") or os.getenv("TAPO_USERNAME", "")
        password = os.getenv(f"{prefix}_PASSWORD", "") or os.getenv("TAPO_PASSWORD", "")
        onvif_port = _parse_int_env(
            f"{prefix}_ONVIF_PORT",
            os.getenv(f"{prefix}_ONVIF_PORT") or os.getenv("TAPO_ONVIF_PORT"),
            2020,
            1,
            65535,
        )
        stream_url = os.getenv(f"{prefix}_STREAM_URL") or os.getenv("TAPO_STREAM_URL")
        mount_mode = _parse_mount_mode(
            os.getenv(f"{prefix}_MOUNT_MODE") or os.getenv("TAPO_MOUNT_MODE"),
            f"{prefix}_MOUNT_MODE",
        )
        max_width = _parse_int_env(
            "CAPTURE_MAX_WIDTH", os.getenv("CAPTURE_MAX_WIDTH"), 1920, 1, MAX_CAPTURE_DIMENSION
        )
        max_height = _parse_int_env(
            "CAPTURE_MAX_HEIGHT", os.getenv("CAPTURE_MAX_HEIGHT"), 1080, 1, MAX_CAPTURE_DIMENSION
        )

        if not host:
            raise ValueError(f"{prefix}_CAMERA_HOST environment variable is required")
        if not username:
            raise ValueError(f"{prefix}_USERNAME environment variable is required")
        if not password:
            raise ValueError(f"{prefix}_PASSWORD environment variable is required")

        return cls(
            host=host,
            username=username,
            password=password,
            onvif_port=onvif_port,
            stream_url=stream_url,
            mount_mode=mount_mode,
            max_width=max_width,
            max_height=max_height,
        )

    @classmethod
    def right_camera_from_env(cls) -> "CameraConfig | None":
        """Create config for right camera if configured.

        Returns:
            CameraConfig for right camera, or None if not configured
        """
        host = os.getenv("TAPO_RIGHT_CAMERA_HOST", "")
        if not host:
            return None

        # Right camera can share username/password with left, or have its own
        username = os.getenv("TAPO_RIGHT_USERNAME", "") or os.getenv("TAPO_USERNAME", "")
        password = os.getenv("TAPO_RIGHT_PASSWORD", "") or os.getenv("TAPO_PASSWORD", "")
        onvif_port = _parse_int_env(
            "TAPO_RIGHT_ONVIF_PORT",
            os.getenv("TAPO_RIGHT_ONVIF_PORT") or os.getenv("TAPO_ONVIF_PORT"),
            2020,
            1,
            65535,
        )
        stream_url = os.getenv("TAPO_RIGHT_STREAM_URL")
        mount_mode = _parse_mount_mode(
            os.getenv("TAPO_RIGHT_MOUNT_MODE") or os.getenv("TAPO_MOUNT_MODE"),
            "TAPO_RIGHT_MOUNT_MODE",
        )
        max_width = _parse_int_env(
            "CAPTURE_MAX_WIDTH", os.getenv("CAPTURE_MAX_WIDTH"), 1920, 1, MAX_CAPTURE_DIMENSION
        )
        max_height = _parse_int_env(
            "CAPTURE_MAX_HEIGHT", os.getenv("CAPTURE_MAX_HEIGHT"), 1080, 1, MAX_CAPTURE_DIMENSION
        )

        if not username or not password:
            return None

        return cls(
            host=host,
            username=username,
            password=password,
            onvif_port=onvif_port,
            stream_url=stream_url,
            mount_mode=mount_mode,
            max_width=max_width,
            max_height=max_height,
        )


@dataclass(frozen=True)
class ServerConfig:
    """MCP Server configuration."""

    name: str = "wifi-cam-mcp"
    version: str = "0.1.0"
    capture_dir: str = "/tmp/wifi-cam-mcp"

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Create config from environment variables."""
        return cls(
            name=os.getenv("MCP_SERVER_NAME", "wifi-cam-mcp"),
            version=os.getenv("MCP_SERVER_VERSION", "0.1.0"),
            capture_dir=os.getenv("CAPTURE_DIR", "/tmp/wifi-cam-mcp"),
        )
