"""Public MCP contract tests for ElevenLabs speech output."""

import os
import sys

import pytest
from mcp import Client, StdioServerParameters, stdio_client

from elevenlabs_t2s_mcp.server import ElevenLabsTTSMCP


def _configure_server(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_PLAY_AUDIO", "false")
    monkeypatch.setenv("ELEVENLABS_SAVE_DIR", str(tmp_path))
    monkeypatch.delenv("GO2RTC_URL", raising=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_typed_registry_preserves_the_say_contract(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_server(monkeypatch, tmp_path)
    application = ElevenLabsTTSMCP()

    async with Client(application.mcp, mode=mode) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == ["say"]
    schema = tools.tools[0].input_schema
    assert schema["required"] == ["text"]
    assert schema["properties"]["speaker"]["anyOf"][0]["enum"] == [
        "camera",
        "local",
        "both",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_say_generates_and_saves_audio_without_forcing_playback(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_server(monkeypatch, tmp_path)
    requests: list[dict[str, str]] = []

    class FakeTextToSpeech:
        def convert(self, **request: str) -> list[bytes]:
            requests.append(request)
            return [b"fake-", b"audio"]

    class FakeElevenLabs:
        text_to_speech = FakeTextToSpeech()

    application = ElevenLabsTTSMCP(client=FakeElevenLabs())

    async with Client(application.mcp, mode=mode) as client:
        result = await client.call_tool(
            "say",
            {
                "text": "  Sanpoloid says hello.  ",
                "voice_id": "voice-test",
                "model_id": "model-test",
                "output_format": "mp3_44100_128",
                "play_audio": False,
                "speaker": "local",
            },
        )

    assert result.is_error is False
    assert requests == [
        {
            "text": "Sanpoloid says hello.",
            "voice_id": "voice-test",
            "model_id": "model-test",
            "output_format": "mp3_44100_128",
        }
    ]
    saved_files = list(tmp_path.glob("tts_*.mp3"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"fake-audio"
    assert "Playback: skipped" in result.content[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_say_reports_validation_and_provider_failures_as_mcp_errors(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_server(monkeypatch, tmp_path)

    class FailingTextToSpeech:
        def convert(self, **_request: str) -> list[bytes]:
            raise RuntimeError("provider unavailable")

    class FailingElevenLabs:
        text_to_speech = FailingTextToSpeech()

    application = ElevenLabsTTSMCP(client=FailingElevenLabs())

    async with Client(application.mcp, mode=mode) as client:
        empty_text = await client.call_tool("say", {"text": "   "})
        invalid_speaker = await client.call_tool(
            "say", {"text": "hello", "speaker": "everywhere"}
        )
        provider_failure = await client.call_tool(
            "say", {"text": "hello", "play_audio": False}
        )

    assert empty_text.is_error is True
    assert invalid_speaker.is_error is True
    assert provider_failure.is_error is True
    assert provider_failure.content[0].text == "Error: provider unavailable"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_camera_only_request_fails_before_generation_when_go2rtc_is_unconfigured(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_server(monkeypatch, tmp_path)
    provider_calls = 0

    class FakeTextToSpeech:
        def convert(self, **_request: str) -> list[bytes]:
            nonlocal provider_calls
            provider_calls += 1
            return [b"audio"]

    class FakeElevenLabs:
        text_to_speech = FakeTextToSpeech()

    application = ElevenLabsTTSMCP(client=FakeElevenLabs())

    async with Client(application.mcp, mode=mode) as client:
        result = await client.call_tool("say", {"text": "hello", "speaker": "camera"})

    assert result.is_error is True
    assert result.content[0].text == "Error: camera speaker is not configured"
    assert provider_calls == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_stdio_process_exposes_the_same_typed_tool(mode: str, tmp_path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "ELEVENLABS_API_KEY": "test-key",
            "ELEVENLABS_PLAY_AUDIO": "false",
            "ELEVENLABS_SAVE_DIR": str(tmp_path),
        }
    )
    env.pop("GO2RTC_URL", None)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "elevenlabs_t2s_mcp.server"],
        env=env,
    )

    async with Client(stdio_client(parameters), mode=mode) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools.tools] == ["say"]
