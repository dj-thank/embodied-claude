"""MCP Server for ElevenLabs text-to-speech."""

import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.parse import quote

if TYPE_CHECKING:
    from .go2rtc import Go2RTCProcess

from elevenlabs.client import ElevenLabs
from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from .config import ElevenLabsConfig, ServerConfig

logger = logging.getLogger(__name__)


def _collect_audio_bytes(audio: Any) -> bytes:
    if isinstance(audio, (bytes, bytearray)):
        return bytes(audio)
    if hasattr(audio, "__iter__"):
        return b"".join(audio)
    raise TypeError("Unsupported audio payload")


def _output_extension(output_format: str) -> str:
    if not output_format:
        return "mp3"
    extension = output_format.split("_", 1)[0].lower()
    if not re.fullmatch(r"[a-z0-9]+", extension):
        raise ValueError("output_format must produce a safe file extension")
    return extension


def _save_audio(audio_bytes: bytes, output_format: str, save_dir: str) -> str:
    os.makedirs(save_dir, exist_ok=True)
    ext = _output_extension(output_format)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_path = os.path.join(save_dir, f"tts_{timestamp}.{ext}")
    with open(file_path, "wb") as f:
        f.write(audio_bytes)
    return file_path


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for stable TTS generation."""
    parts = re.split(r"(?<=[。！？!?.])\s*", text)
    return [p.strip() for p in parts if p.strip()]


def _build_mpv_env(
    pulse_sink: str | None, pulse_server: str | None,
) -> dict[str, str] | None:
    """Build environment dict with PulseAudio settings for mpv."""
    if not pulse_sink and not pulse_server:
        return None
    env = os.environ.copy()
    if pulse_sink:
        env["PULSE_SINK"] = pulse_sink
    if pulse_server:
        env["PULSE_SERVER"] = pulse_server
    return env


def _start_mpv(
    pulse_sink: str | None = None, pulse_server: str | None = None,
) -> subprocess.Popen:
    """Start an mpv process for streaming playback."""
    mpv = shutil.which("mpv")
    if not mpv:
        raise FileNotFoundError("mpv not found")

    env = _build_mpv_env(pulse_sink, pulse_server)
    return subprocess.Popen(
        [mpv, "--no-cache", "--no-terminal", "--", "fd://0"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )


def _stream_sentences_with_mpv(
    client: ElevenLabs,
    sentences: list[str],
    voice_id: str,
    model_id: str,
    output_format: str,
    pulse_sink: str | None = None,
    pulse_server: str | None = None,
) -> tuple[bytes, str]:
    """Stream sentences with separate mpv processes, waiting for each to finish."""
    all_chunks: list[bytes] = []
    for sentence in sentences:
        audio_stream = client.text_to_speech.stream(
            text=sentence,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
        )
        process = _start_mpv(pulse_sink, pulse_server)
        try:
            for chunk in audio_stream:
                all_chunks.append(chunk)
                process.stdin.write(chunk)
                process.stdin.flush()
        finally:
            process.stdin.close()
            process.wait()

    return b"".join(all_chunks), f"streamed via mpv ({len(sentences)} sentences)"


def _stream_with_mpv(
    audio_stream: Iterator[bytes],
    pulse_sink: str | None = None,
    pulse_server: str | None = None,
) -> tuple[bytes, str]:
    """Stream audio chunks to mpv for real-time playback. Returns collected bytes and status."""
    process = _start_mpv(pulse_sink, pulse_server)
    chunks: list[bytes] = []
    try:
        for chunk in audio_stream:
            chunks.append(chunk)
            process.stdin.write(chunk)
            process.stdin.flush()
    finally:
        process.stdin.close()
        process.wait()

    return b"".join(chunks), "streamed via mpv"


def _play_with_paplay(
    file_path: str, pulse_sink: str | None, pulse_server: str | None
) -> tuple[bool, str]:
    paplay = shutil.which("paplay")
    if not paplay:
        return False, "paplay not available"

    wav_path = file_path
    if not file_path.lower().endswith((".wav", ".wave")):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return False, "paplay needs WAV (ffmpeg missing)"
        wav_path = str(Path(file_path).with_suffix(".wav"))
        result = subprocess.run(
            [ffmpeg, "-y", "-i", file_path, wav_path],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            return False, f"paplay conversion failed: {error}"

    env = os.environ.copy()
    if pulse_sink:
        env["PULSE_SINK"] = pulse_sink
    if pulse_server:
        env["PULSE_SERVER"] = pulse_server
    result = subprocess.run(
        [paplay, wav_path],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode == 0:
        notes: list[str] = []
        if pulse_sink:
            notes.append(f"PULSE_SINK={pulse_sink}")
        if pulse_server:
            notes.append(f"PULSE_SERVER={pulse_server}")
        suffix = f" ({', '.join(notes)})" if notes else ""
        return True, f"played via paplay{suffix}"
    error = result.stderr.strip() or result.stdout.strip()
    return False, f"paplay failed: {error}"


def _play_with_go2rtc(
    file_path: str,
    go2rtc_url: str,
    go2rtc_stream: str,
    go2rtc_ffmpeg: str,
) -> tuple[bool, str]:
    try:
        import json
        import urllib.request

        abs_path = os.path.abspath(file_path)
        src = f"ffmpeg:{abs_path}#audio=pcma#input=file"
        url = f"{go2rtc_url}/api/streams?dst={quote(go2rtc_stream, safe='')}&src={quote(src, safe='')}"

        req = urllib.request.Request(url, method="POST", data=b"")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())

        producers = body.get("producers", [])
        has_sender = False
        for consumer in body.get("consumers", []):
            if consumer.get("senders"):
                has_sender = True
                break

        if not has_sender:
            return False, "go2rtc: no audio sender established (camera may not support backchannel)"

        # Wait for ffmpeg producer to finish playing
        ffmpeg_producer_id = None
        for p in producers:
            if p.get("format_name") == "wav" or "ffmpeg" in p.get("source", ""):
                ffmpeg_producer_id = p.get("id")
                break

        if ffmpeg_producer_id:
            # Poll stream status until ffmpeg producer disappears (audio finished)
            for _ in range(60):  # max 30 seconds
                time.sleep(0.5)
                try:
                    status_url = f"{go2rtc_url}/api/streams"
                    with urllib.request.urlopen(status_url, timeout=5) as r:
                        streams = json.loads(r.read())
                    stream = streams.get(go2rtc_stream, {})
                    still_playing = False
                    for p in stream.get("producers", []):
                        if p.get("id") == ffmpeg_producer_id:
                            still_playing = True
                            break
                    if not still_playing:
                        break
                except Exception:
                    break

        return True, f"played via go2rtc → {go2rtc_stream}"
    except Exception as exc:
        return False, f"go2rtc failed: {exc}"


def _play_audio(
    audio_bytes: bytes,
    file_path: str,
    playback: str,
    pulse_sink: str | None,
    pulse_server: str | None,
) -> str:
    playback = (playback or "auto").strip().lower()
    last_error: str | None = None

    if playback in {"auto", "afplay"}:
        afplay = shutil.which("afplay")
        if afplay:
            result = subprocess.run(
                [afplay, file_path],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return "played via afplay"
            error = result.stderr.strip() or result.stdout.strip()
            last_error = f"afplay failed: {error}"
            if playback == "afplay":
                return last_error
        else:
            last_error = "afplay not available"
            if playback == "afplay":
                return last_error

    if playback in {"auto", "paplay"}:
        ok, message = _play_with_paplay(file_path, pulse_sink, pulse_server)
        if ok:
            return message
        last_error = message
        if playback == "paplay":
            return message

    if playback in {"auto", "elevenlabs"}:
        try:
            from elevenlabs.play import play

            old_sink = os.environ.get("PULSE_SINK")
            old_server = os.environ.get("PULSE_SERVER")
            if pulse_sink:
                os.environ["PULSE_SINK"] = pulse_sink
            if pulse_server:
                os.environ["PULSE_SERVER"] = pulse_server
            try:
                play(audio_bytes)
            finally:
                if pulse_sink:
                    if old_sink is None:
                        os.environ.pop("PULSE_SINK", None)
                    else:
                        os.environ["PULSE_SINK"] = old_sink
                if pulse_server:
                    if old_server is None:
                        os.environ.pop("PULSE_SERVER", None)
                    else:
                        os.environ["PULSE_SERVER"] = old_server
            notes: list[str] = []
            if pulse_sink:
                notes.append(f"PULSE_SINK={pulse_sink}")
            if pulse_server:
                notes.append(f"PULSE_SERVER={pulse_server}")
            suffix = f" ({', '.join(notes)})" if notes else ""
            return f"played via elevenlabs{suffix}"
        except Exception as exc:  # noqa: BLE001 - fallback playback
            last_error = f"elevenlabs play failed: {exc}"
            if playback == "elevenlabs":
                return last_error

    if playback in {"auto", "ffplay"}:
        ffplay = shutil.which("ffplay")
        if not ffplay:
            return f"playback skipped (no ffplay, last error: {last_error})"

        result = subprocess.run(
            [ffplay, "-nodisp", "-autoexit", "-loglevel", "error", file_path],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return "played via ffplay"
        error = result.stderr.strip() or result.stdout.strip()
        return f"playback failed via ffplay: {error}"

    return f"playback skipped (unknown playback setting: {playback})"


class ElevenLabsTTSMCP:
    """MCP server that speaks text using ElevenLabs."""

    def __init__(self, client: Any | None = None) -> None:
        self._server_config = ServerConfig.from_env()
        self._config = ElevenLabsConfig.from_env()
        self._client = (
            client if client is not None else ElevenLabs(api_key=self._config.api_key)
        )
        self.mcp = MCPServer(
            self._server_config.name,
            version=self._server_config.version,
        )
        self._go2rtc: "Go2RTCProcess | None" = None
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        @self.mcp.tool(
            name="say",
            description=(
                "Speak text out loud using ElevenLabs TTS. Use this when you want to say "
                "something aloud."
            ),
            structured_output=False,
        )
        async def say(
            text: Annotated[str, Field(description="Text to speak")],
            voice_id: Annotated[
                str | None,
                Field(max_length=256, description="Override voice ID (optional)"),
            ] = None,
            model_id: Annotated[
                str | None,
                Field(max_length=256, description="Override model ID (optional)"),
            ] = None,
            output_format: Annotated[
                str | None,
                Field(max_length=128, description="Override output format (optional)"),
            ] = None,
            play_audio: Annotated[
                bool | None,
                Field(description="Override configured local audio playback (optional)"),
            ] = None,
            speaker: Annotated[
                Literal["camera", "local", "both"] | None,
                Field(
                    description=(
                        "Where to play: camera, local, or both; defaults from go2rtc config"
                    )
                ),
            ] = None,
        ) -> str | CallToolResult:
            text = text.strip()
            if not text:
                return CallToolResult(
                    isError=True,
                    content=[TextContent(type="text", text="Error: 'text' is required")],
                )

            voice_id = voice_id or self._config.voice_id
            model_id = model_id or self._config.model_id
            output_format = output_format or self._config.output_format
            play_audio = self._config.play_audio if play_audio is None else play_audio
            speaker = speaker or ("both" if self._config.go2rtc_url else "local")
            if speaker in {"camera", "both"} and not self._config.go2rtc_url:
                return CallToolResult(
                    isError=True,
                    content=[
                        TextContent(
                            type="text",
                            text="Error: camera speaker is not configured",
                        )
                    ],
                )
            use_local = speaker in {"local", "both"}
            use_camera = speaker in {"camera", "both"}

            try:
                playback_mode = (self._config.playback or "auto").strip().lower()
                use_streaming = (
                    play_audio
                    and use_local
                    and playback_mode in {"auto", "stream"}
                    and shutil.which("mpv") is not None
                )

                if use_streaming:
                    pulse_sink = self._config.pulse_sink
                    pulse_server = self._config.pulse_server
                    sentences = _split_sentences(text)
                    if len(sentences) > 1:
                        audio_bytes, playback = await asyncio.to_thread(
                            _stream_sentences_with_mpv,
                            self._client,
                            sentences,
                            voice_id,
                            model_id,
                            output_format,
                            pulse_sink,
                            pulse_server,
                        )
                    else:
                        audio_stream = await asyncio.to_thread(
                            self._client.text_to_speech.stream,
                            text=text,
                            voice_id=voice_id,
                            model_id=model_id,
                            output_format=output_format,
                        )
                        audio_bytes, playback = await asyncio.to_thread(
                            _stream_with_mpv, audio_stream,
                            pulse_sink, pulse_server,
                        )
                    file_path = _save_audio(audio_bytes, output_format, self._config.save_dir)
                else:
                    audio = await asyncio.to_thread(
                        self._client.text_to_speech.convert,
                        text=text,
                        voice_id=voice_id,
                        model_id=model_id,
                        output_format=output_format,
                    )
                    audio_bytes = _collect_audio_bytes(audio)
                    file_path = _save_audio(audio_bytes, output_format, self._config.save_dir)

                    playback = "skipped"
                    if play_audio and use_local:
                        playback = _play_audio(
                            audio_bytes,
                            file_path,
                            self._config.playback,
                            self._config.pulse_sink,
                            self._config.pulse_server,
                        )

                camera_playback = "not configured"
                if use_camera:
                    ok, cam_msg = await asyncio.to_thread(
                        _play_with_go2rtc,
                        file_path,
                        self._config.go2rtc_url,
                        self._config.go2rtc_stream,
                        self._config.go2rtc_ffmpeg,
                    )
                    camera_playback = cam_msg

                message = (
                    "Spoken via ElevenLabs\n"
                    f"Voice: {voice_id}\n"
                    f"Model: {model_id}\n"
                    f"Output: {output_format}\n"
                    f"File: {file_path}\n"
                    f"Speaker: {speaker}\n"
                    f"Playback: {playback}\n"
                    f"Camera: {camera_playback}"
                )
                return message
            except Exception as exc:  # noqa: BLE001 - surface error to caller
                return CallToolResult(
                    isError=True,
                    content=[TextContent(type="text", text=f"Error: {exc}")],
                )

    async def _ensure_go2rtc(self) -> None:
        """Auto-download and start go2rtc if configured."""
        if not self._config.go2rtc_url or not self._config.go2rtc_auto_start:
            return

        from .go2rtc import Go2RTCProcess, default_config_path, ensure_binary, generate_config

        # Step 1: Ensure binary
        try:
            bin_path = Path(self._config.go2rtc_bin) if self._config.go2rtc_bin else None
            bin_path = ensure_binary(bin_path)
        except Exception as exc:
            logger.warning("go2rtc binary not available: %s", exc)
            return

        # Step 2: Ensure config
        if self._config.go2rtc_config:
            config_path = Path(self._config.go2rtc_config)
        elif self._config.go2rtc_camera_host and self._config.go2rtc_camera_password:
            config_path = generate_config(
                config_path=default_config_path(),
                stream_name=self._config.go2rtc_stream,
                camera_host=self._config.go2rtc_camera_host,
                username=self._config.go2rtc_camera_username or "",
                password=self._config.go2rtc_camera_password,
                ffmpeg_bin=self._config.go2rtc_ffmpeg,
            )
        else:
            logger.warning("go2rtc: no config and no camera credentials, skipping auto-start")
            return

        # Step 3: Start process
        try:
            self._go2rtc = Go2RTCProcess(bin_path, config_path, self._config.go2rtc_url)
            await self._go2rtc.start()
        except Exception as exc:
            logger.warning("go2rtc failed to start: %s", exc)
            self._go2rtc = None

    async def run(self) -> None:
        try:
            await self._ensure_go2rtc()
            await self.mcp.run_stdio_async()
        finally:
            if self._go2rtc:
                self._go2rtc.stop()


def main() -> None:
    asyncio.run(ElevenLabsTTSMCP().run())


if __name__ == "__main__":
    main()
