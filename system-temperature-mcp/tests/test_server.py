"""Hardware-free tests for temperature and clock helpers."""

import sys

import pytest
from mcp import Client, StdioServerParameters, stdio_client

from system_temperature_mcp import server


def test_interpret_temperature_handles_empty_sensor_list() -> None:
    assert "センサー" in server.interpret_temperature([])


def test_interpret_temperature_uses_hottest_sensor() -> None:
    temperatures = [
        {"temperature_celsius": 45.0},
        {"temperature_celsius": 81.0},
    ]

    assert "かなり熱い" in server.interpret_temperature(temperatures)


def test_get_all_temperatures_deduplicates_same_sensor_reading(monkeypatch) -> None:
    reading = {"name": "cpu/temp", "temperature_celsius": 50.04}
    monkeypatch.setattr(server, "get_thermal_zones", lambda: [reading])
    monkeypatch.setattr(server, "get_psutil_temperatures", lambda: [reading.copy()])
    monkeypatch.setattr(server, "get_hwmon_temperatures", lambda: [])

    result = server.get_all_temperatures()

    assert len(result["temperatures"]) == 1


def test_get_current_time_returns_japan_localized_text() -> None:
    assert server.get_current_time().startswith("今は ")


@pytest.mark.asyncio
async def test_typed_registry_exposes_the_existing_tool_contract() -> None:
    tools = await server.mcp.list_tools()

    assert [tool.name for tool in tools] == [
        "get_system_temperature",
        "get_current_time",
    ]
    assert all(tool.input_schema["type"] == "object" for tool in tools)
    assert all(tool.input_schema["properties"] == {} for tool in tools)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_typed_registry_dispatches_modern_and_legacy_clients(mode: str) -> None:
    async with Client(server.mcp, mode=mode) as client:
        result = await client.call_tool("get_current_time", {})

    assert not result.is_error
    assert result.content[0].type == "text"
    assert result.content[0].text.startswith("今は ")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_stdio_server_supports_modern_and_legacy_clients(mode: str) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "system_temperature_mcp.server"],
    )

    async with Client(stdio_client(parameters), mode=mode) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == [
        "get_system_temperature",
        "get_current_time",
    ]
