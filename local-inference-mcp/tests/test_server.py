"""MCP contract tests for local inference."""

import sys
from dataclasses import dataclass

import pytest
from mcp import Client, StdioServerParameters, stdio_client

from local_inference_mcp.inference import InferenceResult
from local_inference_mcp.server import create_server


@dataclass
class StubInference:
    def status(self) -> dict:
        return {
            "available": True,
            "endpoint": "http://127.0.0.1:1234/v1",
            "configured_model": "local-jp",
            "models": ["local-jp"],
        }

    def complete(self, prompt: str, **kwargs) -> InferenceResult:
        assert prompt == "短く挨拶して"
        assert kwargs == {
            "system_prompt": "日本語で答える",
            "model": None,
            "preset": "strict",
            "json_schema": None,
            "temperature": 0.2,
            "max_tokens": 64,
        }
        return InferenceResult(
            text="こんにちは。",
            model="local-jp",
            prompt_tokens=8,
            completion_tokens=4,
            total_tokens=12,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_server_exposes_a_small_typed_interface_in_all_client_modes(mode: str) -> None:
    mcp = create_server(lambda: StubInference())

    async with Client(mcp, mode=mode) as client:
        tools = await client.list_tools()
        status = await client.call_tool("get_local_inference_status", {})
        completion = await client.call_tool(
            "ask_local_model",
            {
                "prompt": "短く挨拶して",
                "system_prompt": "日本語で答える",
                "preset": "strict",
                "temperature": 0.2,
                "max_tokens": 64,
            },
        )

    assert [tool.name for tool in tools.tools] == [
        "get_local_inference_status",
        "ask_local_model",
    ]
    ask_tool = next(tool for tool in tools.tools if tool.name == "ask_local_model")
    assert ask_tool.input_schema["properties"]["preset"]["enum"] == [
        "default",
        "strict",
        "concise",
        "json",
    ]
    assert status.structured_content["models"] == ["local-jp"]
    assert completion.structured_content == {
        "text": "こんにちは。",
        "model": "local-jp",
        "usage": {
            "prompt_tokens": 8,
            "completion_tokens": 4,
            "total_tokens": 12,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_stdio_process_exposes_the_same_interface(mode: str) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "local_inference_mcp.server"],
    )

    async with Client(stdio_client(parameters), mode=mode) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == [
        "get_local_inference_status",
        "ask_local_model",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_json_completion_exposes_parsed_structured_content(mode: str) -> None:
    class JsonInference:
        def complete(self, prompt: str, **kwargs) -> InferenceResult:
            return InferenceResult(
                text='{"状態":"正常"}',
                model="local-jp",
                parsed_json={"状態": "正常"},
            )

    async with Client(create_server(lambda: JsonInference()), mode=mode) as client:
        result = await client.call_tool(
            "ask_local_model",
            {"prompt": "状態を返して", "preset": "json"},
        )

    assert result.is_error is False
    assert result.structured_content["parsed_json"] == {"状態": "正常"}
