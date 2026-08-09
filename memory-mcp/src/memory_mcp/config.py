"""Configuration for Memory MCP Server."""

import os
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse an opt-in environment flag; unknown values fail closed."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _deletion_token_ttl() -> int:
    """Read a bounded deletion-token TTL."""
    try:
        value = int(os.getenv("MEMORY_DELETION_TOKEN_TTL_SECONDS", "300"))
    except ValueError:
        return 300
    return max(30, min(3600, value))


@dataclass(frozen=True)
class MemoryConfig:
    """Memory storage configuration."""

    db_path: str
    collection_name: str
    backend: str = "chroma"

    def __post_init__(self) -> None:
        if self.backend not in {"chroma", "sqlite"}:
            raise ValueError("MemoryConfig.backend must be 'chroma' or 'sqlite'")

    @classmethod
    def from_env(cls) -> "MemoryConfig":
        """Create config from environment variables."""
        backend = os.getenv("MEMORY_BACKEND", "auto").strip().lower()
        if backend not in {"auto", "chroma", "sqlite"}:
            raise ValueError("MEMORY_BACKEND must be 'auto', 'chroma', or 'sqlite'")
        if backend == "auto":
            backend = "chroma" if find_spec("chromadb") is not None else "sqlite"
        default_path = str(Path.home() / ".claude" / "memories" / backend)

        return cls(
            db_path=os.getenv("MEMORY_DB_PATH", default_path),
            collection_name=os.getenv("MEMORY_COLLECTION_NAME", "claude_memories"),
            backend=backend,
        )


@dataclass(frozen=True)
class ServerConfig:
    """MCP Server configuration."""

    name: str = "memory-mcp"
    version: str = "0.1.0"
    deletion_enabled: bool = False
    deletion_token_ttl_seconds: int = 300

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Create config from environment variables."""
        return cls(
            name=os.getenv("MCP_SERVER_NAME", "memory-mcp"),
            version=os.getenv("MCP_SERVER_VERSION", "0.1.0"),
            deletion_enabled=_env_flag("MEMORY_DELETION_ENABLED"),
            deletion_token_ttl_seconds=_deletion_token_ttl(),
        )
