"""Tests for pure ElevenLabs server helpers."""

import base64
from pathlib import Path

import pytest

from elevenlabs_t2s_mcp.server import _go2rtc_request, _output_extension, _save_audio


class TestAudioOutput:
    """Tests for generated audio file names."""

    def test_output_extension_uses_format_prefix(self):
        assert _output_extension("mp3_44100_128") == "mp3"
        assert _output_extension("wav") == "wav"
        assert _output_extension("") == "mp3"

    def test_output_extension_rejects_path_components(self):
        with pytest.raises(ValueError, match="safe file extension"):
            _output_extension("mp3/../../outside")

    def test_save_audio_stays_in_save_directory(self, tmp_path: Path):
        file_path = Path(_save_audio(b"audio", "mp3_44100_128", str(tmp_path)))

        assert file_path.parent == tmp_path
        assert file_path.suffix == ".mp3"
        assert file_path.read_bytes() == b"audio"


def test_go2rtc_request_adds_basic_auth_without_putting_it_in_url() -> None:
    request = _go2rtc_request(
        "http://127.0.0.1:1984/api/streams",
        method="POST",
        data=b"",
        api_credentials=("api-user", "api-password"),
    )

    token = base64.b64encode(b"api-user:api-password").decode("ascii")
    assert request.full_url == "http://127.0.0.1:1984/api/streams"
    assert request.get_header("Authorization") == f"Basic {token}"
