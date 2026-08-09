"""Hardware-free tests for temperature and clock helpers."""

import sys

import pytest
from mcp import Client, StdioServerParameters, stdio_client
from mcp.client import advertise
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID

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
async def test_temperature_tool_keeps_text_fallback_for_all_clients(
    mode: str, monkeypatch
) -> None:
    monkeypatch.setattr(
        server,
        "get_all_temperatures",
        lambda: {
            "feeling": "快適やで〜。ちょうどええ感じ!",
            "temperatures": [],
        },
    )

    async with Client(server.mcp, mode=mode) as client:
        result = await client.call_tool("get_system_temperature", {})

    assert not result.is_error
    assert result.content[0].type == "text"
    assert result.content[0].text.startswith("快適やで〜。ちょうどええ感じ!")
    assert "センサーが見つかりませんでした" in result.content[0].text
    assert result.structured_content == {
        "feeling": "快適やで〜。ちょうどええ感じ!",
        "temperatures": [],
    }


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


@pytest.mark.asyncio
async def test_temperature_tool_exposes_a_network_free_mcp_app(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "get_all_temperatures",
        lambda: {
            "feeling": "快適やで〜。ちょうどええ感じ!",
            "temperatures": [
                {
                    "source": "test",
                    "name": "cpu/package",
                    "temperature_celsius": 48.5,
                }
            ],
        },
    )
    extension = advertise(EXTENSION_ID, {"mimeTypes": [APP_MIME_TYPE]})

    async with Client(server.mcp, extensions=[extension]) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        result = await client.call_tool("get_system_temperature", {})
        resource = await client.read_resource(server.DASHBOARD_URI)

    temperature_tool = next(
        tool for tool in tools.tools if tool.name == "get_system_temperature"
    )
    assert temperature_tool.meta == {
        "ui": {
            "resourceUri": server.DASHBOARD_URI,
            "visibility": ["model", "app"],
        }
    }
    assert [item.uri for item in resources.resources] == [server.DASHBOARD_URI]
    assert resource.contents[0].mime_type == APP_MIME_TYPE
    assert "ui/notifications/tool-result" in resource.contents[0].text
    assert "http://" not in resource.contents[0].text
    assert "https://" not in resource.contents[0].text
    assert result.structured_content == {
        "feeling": "快適やで〜。ちょうどええ感じ!",
        "temperatures": [
            {
                "source": "test",
                "name": "cpu/package",
                "temperature_celsius": 48.5,
            }
        ],
    }
