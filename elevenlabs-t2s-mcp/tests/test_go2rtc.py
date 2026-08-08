"""Tests for go2rtc auto-download and process management."""

import hashlib
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_generates_valid_yaml(self, tmp_path):
        config_path = tmp_path / "go2rtc.yaml"
        result = generate_config(
            config_path=config_path,
            stream_name="tapo_cam",
            camera_host="192.168.1.100",
            username="admin",
            password="secret",
            ffmpeg_bin="/usr/bin/ffmpeg",
        )
        assert result == config_path
        content = config_path.read_text()
        assert "tapo_cam:" in content
        assert "rtsp://admin:secret@192.168.1.100:554/stream1" in content
        assert "tapo://secret@192.168.1.100" in content
        assert "/usr/bin/ffmpeg" in content
        assert '":1984"' in content

    def test_creates_parent_directories(self, tmp_path):
        config_path = tmp_path / "sub" / "dir" / "go2rtc.yaml"
        generate_config(
            config_path=config_path,
            stream_name="cam",
            camera_host="10.0.0.1",
            username="u",
            password="p",
        )
        assert config_path.exists()

    def test_escapes_credentials_in_urls(self, tmp_path):
        config_path = tmp_path / "go2rtc.yaml"

        generate_config(
            config_path=config_path,
            stream_name="cam",
            camera_host="10.0.0.1",
            username="user@example",
            password="p@ss:word/with spaces",
        )

        content = config_path.read_text()
        assert "user%40example:p%40ss%3Aword%2Fwith%20spaces@10.0.0.1" in content

    def test_overwrites_existing(self, tmp_path):
        config_path = tmp_path / "go2rtc.yaml"
        config_path.write_text("old content")
        generate_config(
            config_path=config_path,
            stream_name="new_cam",
            camera_host="10.0.0.2",
            username="u",
            password="p",
        )
        content = config_path.read_text()
        assert "new_cam:" in content
        assert "old content" not in content


class TestGo2RTCProcess:
    """Tests for process lifecycle."""

    def test_is_running_returns_false_when_unreachable(self):
        proc = Go2RTCProcess(
            Path("/fake/go2rtc"),
            Path("/fake/config.yaml"),
            api_url="http://localhost:19999",
        )
        assert proc.is_running() is False

    @patch("elevenlabs_t2s_mcp.go2rtc.urllib.request.urlopen")
    def test_is_running_returns_true_when_api_responds(self, mock_urlopen):
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        proc = Go2RTCProcess(
            Path("/fake/go2rtc"),
            Path("/fake/config.yaml"),
        )
        assert proc.is_running() is True

    @pytest.mark.asyncio
    @patch.object(Go2RTCProcess, "is_running", return_value=True)
    async def test_start_skips_when_already_running(self, mock_running):
        proc = Go2RTCProcess(Path("/fake"), Path("/fake"))
        await proc.start()
        # Should not spawn a process
        assert proc._process is None

    def test_stop_when_no_process(self):
        proc = Go2RTCProcess(Path("/fake"), Path("/fake"))
        # Should not raise
        proc.stop()
