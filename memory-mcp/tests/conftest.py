"""Pytest fixtures for Memory MCP tests."""

from pathlib import Path

import pytest
import pytest_asyncio

from memory_mcp.config import MemoryConfig
from memory_mcp.memory import MemoryStore


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    """Create a temporary database path."""
    return str(tmp_path / "test_chroma")


@pytest.fixture(params=("chroma", "sqlite"))
def memory_config(temp_db_path: str, request: pytest.FixtureRequest) -> MemoryConfig:
    """Exercise the shared store contract against both persistence backends."""
    backend = str(request.param)
    return MemoryConfig(
        db_path=f"{temp_db_path}_{backend}",
        collection_name="test_memories",
        backend=backend,
    )


@pytest_asyncio.fixture
async def memory_store(memory_config: MemoryConfig) -> MemoryStore:
    """Create and connect a memory store."""
    store = MemoryStore(memory_config)
    await store.connect()
    yield store
    await store.disconnect()
