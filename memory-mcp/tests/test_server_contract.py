"""Public MCP SDK v2 contract tests for long-term memory tools."""

import os
import sys

import pytest
from mcp import Client, StdioServerParameters, stdio_client

from memory_mcp.server import MemoryMCPServer

TOOL_NAMES = [
    "remember",
    "prepare_forget",
    "forget",
    "search_memories",
    "recall",
    "list_recent_memories",
    "get_memory_stats",
    "recall_with_associations",
    "recall_divergent",
    "get_association_diagnostics",
    "consolidate_memories",
    "get_memory_chain",
    "create_episode",
    "search_episodes",
    "get_episode_memories",
    "save_visual_memory",
    "save_audio_memory",
    "recall_by_camera_position",
    "get_working_memory",
    "refresh_working_memory",
    "link_memories",
    "get_causal_chain",
    "tom",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_typed_registry_exposes_all_memory_tools(mode: str) -> None:
    application = MemoryMCPServer()

    async with Client(application.mcp, mode=mode) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == TOOL_NAMES
    remember = next(tool for tool in tools.tools if tool.name == "remember")
    importance = remember.input_schema["properties"]["importance"]
    assert importance["minimum"] == 1
    assert importance["maximum"] == 5
    assert remember.input_schema["properties"]["emotion"]["enum"] == [
        "happy",
        "sad",
        "surprised",
        "moved",
        "excited",
        "nostalgic",
        "curious",
        "neutral",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_typed_registry_rejects_invalid_ranges(mode: str) -> None:
    application = MemoryMCPServer()

    async with Client(application.mcp, mode=mode) as client:
        invalid_importance = await client.call_tool(
            "remember", {"content": "range check", "importance": 6}
        )
        invalid_depth = await client.call_tool(
            "get_causal_chain", {"memory_id": "memory-1", "max_depth": 0}
        )

    assert invalid_importance.is_error is True
    assert invalid_depth.is_error is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_stdio_initializes_with_lightweight_sqlite_backend(
    mode: str,
    tmp_path,
) -> None:
    env = os.environ.copy()
    env.update(
        {
            "MEMORY_BACKEND": "sqlite",
            "MEMORY_DB_PATH": str(tmp_path / "memory.db"),
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "memory_mcp.server"],
        env=env,
    )

    async with Client(stdio_client(parameters), mode=mode) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == TOOL_NAMES
