"""Tests for go2rtc auto-download and process management."""

import hashlib
import json
import os
import stat
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from elevenlabs_t2s_mcp.go2rtc import (
    GO2RTC_VERSION,
    Go2RTCProcess,
    ReleaseArtifact,
    _download_file,
    _get_release_artifact,
    detect_platform,
    ensure_binary,
    generate_config,
)
from elevenlabs_t2s_mcp.server import ElevenLabsTTSMCP


class TestDetectPlatform:
    """Tests for platform detection."""

    @patch("elevenlabs_t2s_mcp.go2rtc.platform")
    def test_linux_amd64(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        mock_platform.machine.return_value = "x86_64"
        assert detect_platform() == "go2rtc_linux_amd64"

    @patch("elevenlabs_t2s_mcp.go2rtc.platform")
    def test_linux_arm64(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        mock_platform.machine.return_value = "aarch64"
        assert detect_platform() == "go2rtc_linux_arm64"

    @patch("elevenlabs_t2s_mcp.go2rtc.platform")
    def test_darwin_arm64(self, mock_platform):
        mock_platform.system.return_value = "Darwin"
        mock_platform.machine.return_value = "arm64"
        assert detect_platform() == "go2rtc_mac_arm64"

    @patch("elevenlabs_t2s_mcp.go2rtc.platform")
    def test_unsupported_platform(self, mock_platform):
        mock_platform.system.return_value = "FreeBSD"
        mock_platform.machine.return_value = "sparc64"
        with pytest.raises(RuntimeError, match="Unsupported platform"):
            detect_platform()


class TestEnsureBinary:
    """Tests for binary download."""

    def test_binary_already_exists(self, tmp_path):
        bin_path = tmp_path / "go2rtc"
        bin_path.write_text("fake binary")
        result = ensure_binary(bin_path)
        assert result == bin_path

    def test_managed_cache_detects_tampering_and_redownloads(self, tmp_path):
        bin_path = tmp_path / "go2rtc"
        payload = b"pinned go2rtc binary"
        artifact = ReleaseArtifact(
            name="go2rtc_linux_amd64",
            version=GO2RTC_VERSION,
            url="https://example.com/go2rtc_linux_amd64",
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        download_count = 0

        def fake_download(_url, destination, _expected_sha256):
            nonlocal download_count
            download_count += 1
            destination.write_bytes(payload)

        with (
            patch(
                "elevenlabs_t2s_mcp.go2rtc.default_bin_path",
                return_value=bin_path,
            ),
            patch(
                "elevenlabs_t2s_mcp.go2rtc.detect_platform",
                return_value=artifact.name,
            ),
            patch(
                "elevenlabs_t2s_mcp.go2rtc._get_release_artifact",
                return_value=artifact,
            ),
            patch(
                "elevenlabs_t2s_mcp.go2rtc._download_file",
                side_effect=fake_download,
            ),
            patch("elevenlabs_t2s_mcp.go2rtc.platform") as mock_platform,
        ):
            mock_platform.system.return_value = "Linux"

            assert ensure_binary() == bin_path
            assert download_count == 1

            assert ensure_binary() == bin_path
            assert download_count == 1

            bin_path.write_bytes(b"tampered after installation")

            assert ensure_binary() == bin_path
            assert download_count == 2

    def test_managed_zip_is_verified_extracted_and_recorded(self, tmp_path):
        source_zip = tmp_path / "source.zip"
        binary_bytes = b"windows go2rtc executable"
        with zipfile.ZipFile(source_zip, "w") as archive:
            archive.writestr("release/go2rtc.exe", binary_bytes)
        archive_bytes = source_zip.read_bytes()
        source_zip.unlink()

        artifact = ReleaseArtifact(
            name="go2rtc_win64.zip",
            version=GO2RTC_VERSION,
            url="https://example.com/go2rtc_win64.zip",
            sha256=hashlib.sha256(archive_bytes).hexdigest(),
        )
        bin_path = tmp_path / "cache" / "go2rtc.exe"

        def fake_retrieve(_url, filename):
            Path(filename).write_bytes(archive_bytes)

        with (
            patch(
                "elevenlabs_t2s_mcp.go2rtc.default_bin_path",
                return_value=bin_path,
            ),
            patch(
                "elevenlabs_t2s_mcp.go2rtc.detect_platform",
                return_value="go2rtc_win64",
            ),
            patch(
                "elevenlabs_t2s_mcp.go2rtc._get_release_artifact",
                return_value=artifact,
            ),
            patch(
                "elevenlabs_t2s_mcp.go2rtc.urllib.request.urlretrieve",
                side_effect=fake_retrieve,
            ),
            patch("elevenlabs_t2s_mcp.go2rtc.platform") as mock_platform,
        ):
            mock_platform.system.return_value = "Windows"

            assert ensure_binary() == bin_path

        assert bin_path.read_bytes() == binary_bytes
        assert bin_path.with_name("go2rtc.exe.manifest.json").exists()
        assert list(bin_path.parent.glob("*.zip")) == []
        assert list(bin_path.parent.glob("*.tmp")) == []

    @patch("elevenlabs_t2s_mcp.go2rtc._get_release_artifact")
    @patch("elevenlabs_t2s_mcp.go2rtc._download_file")
    @patch("elevenlabs_t2s_mcp.go2rtc.detect_platform")
    @patch("elevenlabs_t2s_mcp.go2rtc.platform")
    def test_download_linux_binary(
        self, mock_platform, mock_detect, mock_download, mock_artifact, tmp_path
    ):
        mock_platform.system.return_value = "Linux"
        mock_detect.return_value = "go2rtc_linux_amd64"
        artifact = ReleaseArtifact(
            name="go2rtc_linux_amd64",
            version=GO2RTC_VERSION,
            url="https://example.com/go2rtc_linux_amd64",
            sha256="1" * 64,
        )
        mock_artifact.return_value = artifact

        bin_path = tmp_path / "go2rtc"

        def fake_download(url, dest, expected_sha256):
            assert expected_sha256 == artifact.sha256
            dest.write_text("fake binary")

        mock_download.side_effect = fake_download

        result = ensure_binary(bin_path)
        assert result == bin_path
        assert bin_path.exists()
        mock_download.assert_called_once_with(
            artifact.url,
            bin_path,
            artifact.sha256,
        )


class TestReleaseArtifact:
    """Tests for deterministic release selection and integrity checks."""

    def test_supported_artifact_is_version_and_digest_pinned(self):
        artifact = _get_release_artifact("go2rtc_linux_amd64")

        assert artifact.version == GO2RTC_VERSION == "v1.9.14"
        assert artifact.name == "go2rtc_linux_amd64"
        assert artifact.url.endswith("/v1.9.14/go2rtc_linux_amd64")
        assert artifact.sha256 == (
            "32d616af226bd731678ffde328b94cfb94e30339bfefc469cfb76323144615a6"
        )

    def test_unknown_artifact_is_rejected(self):
        with pytest.raises(RuntimeError, match="No pinned go2rtc artifact"):
            _get_release_artifact("go2rtc_plan9_mips")

    @patch("elevenlabs_t2s_mcp.go2rtc.urllib.request.urlretrieve")
    def test_download_commits_verified_bytes(self, mock_retrieve, tmp_path):
        payload = b"verified go2rtc binary"
        expected_sha256 = hashlib.sha256(payload).hexdigest()
        destination = tmp_path / "go2rtc"

        def fake_retrieve(_url, filename):
            Path(filename).write_bytes(payload)

        mock_retrieve.side_effect = fake_retrieve

        _download_file("https://example.com/go2rtc", destination, expected_sha256)

        assert destination.read_bytes() == payload
        assert list(tmp_path.glob("*.tmp")) == []

    @patch("elevenlabs_t2s_mcp.go2rtc.urllib.request.urlretrieve")
    def test_download_rejects_checksum_mismatch(self, mock_retrieve, tmp_path):
        destination = tmp_path / "go2rtc"

        def fake_retrieve(_url, filename):
            Path(filename).write_bytes(b"tampered")

        mock_retrieve.side_effect = fake_retrieve

        with pytest.raises(RuntimeError, match="checksum mismatch"):
            _download_file("https://example.com/go2rtc", destination, "0" * 64)

        assert not destination.exists()
        assert list(tmp_path.glob("*.tmp")) == []


class TestGenerateConfig:
    """Tests for config file generation."""

    def test_generates_private_loopback_config_without_credentials(self, tmp_path):
        config_path = tmp_path / "go2rtc.yaml"
        result = generate_config(
            config_path=config_path,
            stream_name="tapo_cam",
            camera_host="192.168.1.100",
            username="user@example",
            password="p@ss:word/with spaces",
            ffmpeg_bin="/usr/bin/ffmpeg",
        )

        assert result.path == config_path
        assert result.environment == {
            "SANPOLOID_GO2RTC_USERNAME": "user%40example",
            "SANPOLOID_GO2RTC_PASSWORD": "p%40ss%3Aword%2Fwith%20spaces",
            "SANPOLOID_GO2RTC_API_USERNAME": result.api_credentials[0],
            "SANPOLOID_GO2RTC_API_PASSWORD": result.api_credentials[1],
        }
        assert all(result.api_credentials)
        assert "p@ss:word/with spaces" not in repr(result)
        assert result.api_credentials[0] not in repr(result)
        assert result.api_credentials[1] not in repr(result)
        content = config_path.read_text()
        assert "user@example" not in content
        assert "p@ss:word/with spaces" not in content
        assert "${SANPOLOID_GO2RTC_USERNAME}" in content
        assert "${SANPOLOID_GO2RTC_PASSWORD}" in content
        assert 'listen: "127.0.0.1:1984"' in content
        assert 'listen: "127.0.0.1:8554"' in content
        assert 'webrtc:\n  listen: ""' in content
        assert 'srtp:\n  listen: ""' in content
        assert 'username: "${SANPOLOID_GO2RTC_API_USERNAME}"' in content
        assert 'password: "${SANPOLOID_GO2RTC_API_PASSWORD}"' in content
        assert "local_auth: true" in content
        assert 'bin: "/usr/bin/ffmpeg"' in content
        assert '"/api/streams"' in content
        if os.name != "nt":
            assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    def test_creates_parent_directories(self, tmp_path):
        config_path = tmp_path / "sub" / "dir" / "go2rtc.yaml"
        result = generate_config(
            config_path=config_path,
            stream_name="cam",
            camera_host="10.0.0.1",
            username="u",
            password="p",
        )
        assert result.path == config_path
        assert config_path.exists()

    def test_structurally_quotes_dynamic_yaml_scalars(self, tmp_path):
        config_path = tmp_path / "go2rtc.yaml"
        stream_name = 'cam:\napi:\n  listen: ":9999"'
        ffmpeg_bin = 'ffmpeg\nlog:\n  level: "trace"'

        generate_config(
            config_path=config_path,
            stream_name=stream_name,
            camera_host="10.0.0.1",
            username="user",
            password="password",
            ffmpeg_bin=ffmpeg_bin,
        )

        content = config_path.read_text()
        assert f"  {json.dumps(stream_name)}:" in content
        assert f"  bin: {json.dumps(ffmpeg_bin)}" in content
        assert content.count("\napi:\n") == 1
        assert content.count("\nlog:\n") == 1

    @pytest.mark.parametrize(
        "camera_host",
        ["", "10.0.0.1/path", "user@10.0.0.1", "10.0.0.1\napi: {}"],
    )
    def test_rejects_invalid_camera_authority(self, tmp_path, camera_host):
        with pytest.raises(ValueError, match="camera host"):
            generate_config(
                config_path=tmp_path / "go2rtc.yaml",
                stream_name="cam",
                camera_host=camera_host,
                username="user",
                password="password",
            )

    def test_overwrites_existing(self, tmp_path):
        config_path = tmp_path / "go2rtc.yaml"
        config_path.write_text("old content")
        with patch("elevenlabs_t2s_mcp.go2rtc.os.replace", wraps=os.replace) as replace:
            generate_config(
                config_path=config_path,
                stream_name="new_cam",
                camera_host="10.0.0.2",
                username="u",
                password="p",
            )

        replace.assert_called_once()
        assert list(tmp_path.glob("*.tmp")) == []
        content = config_path.read_text()
        assert '"new_cam":' in content
        assert "old content" not in content


class TestGo2RTCProcess:
    """Tests for process lifecycle."""

    @pytest.mark.asyncio
    async def test_managed_process_receives_only_encoded_camera_credentials(
        self, monkeypatch
    ):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-secret")
        monkeypatch.setenv("TAPO_USERNAME", "raw-user")
        monkeypatch.setenv("TAPO_PASSWORD", "raw-password")
        monkeypatch.setenv("GO2RTC_CAMERA_USERNAME", "raw-go2rtc-user")
        monkeypatch.setenv("GO2RTC_CAMERA_PASSWORD", "raw-go2rtc-password")
        monkeypatch.setenv("GO2RTC_API_USERNAME", "raw-api-user")
        monkeypatch.setenv("GO2RTC_API_PASSWORD", "raw-api-password")
        monkeypatch.setenv("SANPOLOID_UNRELATED_PARENT_SECRET", "must-not-leak")
        process = MagicMock()
        process.poll.return_value = None
        process.pid = 1234
        credentials = {
            "SANPOLOID_GO2RTC_USERNAME": "user%40example",
            "SANPOLOID_GO2RTC_PASSWORD": "p%40ssword",
            "SANPOLOID_GO2RTC_API_USERNAME": "api-user",
            "SANPOLOID_GO2RTC_API_PASSWORD": "api-password",
        }
        go2rtc = Go2RTCProcess(
            Path("/fake/go2rtc"),
            Path("/fake/config.yaml"),
            environment=credentials,
            api_credentials=("api-user", "api-password"),
        )

        with (
            patch.object(go2rtc, "_endpoint_is_occupied", return_value=False),
            patch.object(go2rtc, "is_running", return_value=True),
            patch(
                "elevenlabs_t2s_mcp.go2rtc.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "elevenlabs_t2s_mcp.go2rtc.subprocess.Popen",
                return_value=process,
            ) as popen,
        ):
            await go2rtc.start()

        child_env = popen.call_args.kwargs["env"]
        assert child_env["SANPOLOID_GO2RTC_USERNAME"] == "user%40example"
        assert child_env["SANPOLOID_GO2RTC_PASSWORD"] == "p%40ssword"
        assert child_env["SANPOLOID_GO2RTC_API_USERNAME"] == "api-user"
        assert child_env["SANPOLOID_GO2RTC_API_PASSWORD"] == "api-password"
        for name in (
            "ELEVENLABS_API_KEY",
            "TAPO_USERNAME",
            "TAPO_PASSWORD",
            "GO2RTC_CAMERA_USERNAME",
            "GO2RTC_CAMERA_PASSWORD",
            "GO2RTC_API_USERNAME",
            "GO2RTC_API_PASSWORD",
            "SANPOLOID_UNRELATED_PARENT_SECRET",
        ):
            assert name not in child_env
        assert popen.call_args.kwargs["stdout"] is subprocess.DEVNULL
        assert popen.call_args.kwargs["stderr"] is subprocess.DEVNULL

    def test_managed_config_repr_does_not_disclose_credentials(self, tmp_path):
        config_path = tmp_path / "go2rtc.yaml"
        generated = generate_config(
            config_path=config_path,
            stream_name="cam",
            camera_host="10.0.0.1",
            username="private-user",
            password="private-password",
        )

        assert "private-user" not in repr(generated)
        assert "private-password" not in repr(generated)

    def test_is_running_returns_false_when_unreachable(self):
        proc = Go2RTCProcess(
            Path("/fake/go2rtc"),
            Path("/fake/config.yaml"),
            api_url="http://localhost:19999",
        )
        assert proc.is_running() is False

    def test_managed_process_rejects_non_loopback_api_url(self):
        with pytest.raises(ValueError, match="loopback"):
            Go2RTCProcess(
                Path("/fake/go2rtc"),
                Path("/fake/config.yaml"),
                api_url="http://192.0.2.10:1984",
                environment={"SANPOLOID_GO2RTC_PASSWORD": "secret"},
                api_credentials=("api-user", "api-password"),
            )

    @patch("elevenlabs_t2s_mcp.go2rtc.urllib.request.urlopen")
    def test_is_running_returns_true_when_api_responds(self, mock_urlopen):
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        proc = Go2RTCProcess(
            Path("/fake/go2rtc"),
            Path("/fake/config.yaml"),
        )
        assert proc.is_running() is True
        request = mock_urlopen.call_args.args[0]
        assert request.get_header("Authorization") is None

    @patch("elevenlabs_t2s_mcp.go2rtc.urllib.request.urlopen")
    def test_managed_health_check_uses_basic_auth(self, mock_urlopen):
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        proc = Go2RTCProcess(
            Path("/fake/go2rtc"),
            Path("/fake/config.yaml"),
            environment={"SANPOLOID_GO2RTC_PASSWORD": "secret"},
            api_credentials=("api-user", "api-password"),
        )

        assert proc.is_running() is True

        request = mock_urlopen.call_args.args[0]
        assert request.get_header("Authorization").startswith("Basic ")

    @pytest.mark.asyncio
    @patch("elevenlabs_t2s_mcp.go2rtc.socket.create_connection")
    @patch("elevenlabs_t2s_mcp.go2rtc.urllib.request.urlopen")
    async def test_start_probes_unowned_service_without_disclosing_auth(
        self, mock_urlopen, mock_create_connection
    ):
        mock_create_connection.return_value.__enter__ = MagicMock()
        mock_create_connection.return_value.__exit__ = MagicMock(return_value=False)
        proc = Go2RTCProcess(
            Path("/fake"),
            Path("/fake"),
            environment={"SANPOLOID_GO2RTC_PASSWORD": "secret"},
            api_credentials=("future-user", "future-password"),
        )

        with pytest.raises(RuntimeError, match="already responding"):
            await proc.start()

        assert proc._process is None
        mock_create_connection.assert_called_once_with(("localhost", 1984), timeout=2)
        mock_urlopen.assert_not_called()

    def test_stop_when_no_process(self):
        proc = Go2RTCProcess(Path("/fake"), Path("/fake"))
        # Should not raise
        proc.stop()


@pytest.mark.asyncio
async def test_mcp_runtime_wires_managed_environment_and_api_credentials(tmp_path):
    runtime = ElevenLabsTTSMCP.__new__(ElevenLabsTTSMCP)
    runtime._config = SimpleNamespace(
        go2rtc_url="http://localhost:1984",
        go2rtc_auto_start=True,
        go2rtc_bin=None,
        go2rtc_config=None,
        go2rtc_camera_host="192.0.2.10",
        go2rtc_camera_username="camera-user",
        go2rtc_camera_password="camera-password",
        go2rtc_stream="tapo_cam",
        go2rtc_ffmpeg="ffmpeg",
    )
    runtime._go2rtc = None
    runtime._go2rtc_api_credentials = None
    generated = SimpleNamespace(
        path=tmp_path / "go2rtc.yaml",
        environment={"SANPOLOID_GO2RTC_PASSWORD": "encoded-password"},
        api_credentials=("api-user", "api-password"),
    )
    process = MagicMock()
    process.start = AsyncMock()

    with (
        patch(
            "elevenlabs_t2s_mcp.go2rtc.ensure_binary",
            return_value=tmp_path / "go2rtc.exe",
        ),
        patch(
            "elevenlabs_t2s_mcp.go2rtc.default_config_path",
            return_value=generated.path,
        ),
        patch(
            "elevenlabs_t2s_mcp.go2rtc.generate_config",
            return_value=generated,
        ),
        patch(
            "elevenlabs_t2s_mcp.go2rtc.Go2RTCProcess",
            return_value=process,
        ) as process_class,
    ):
        await runtime._ensure_go2rtc()

    process_class.assert_called_once_with(
        tmp_path / "go2rtc.exe",
        generated.path,
        "http://localhost:1984",
        environment=generated.environment,
        api_credentials=generated.api_credentials,
    )
    process.start.assert_awaited_once()
    assert runtime._go2rtc_api_credentials == generated.api_credentials
