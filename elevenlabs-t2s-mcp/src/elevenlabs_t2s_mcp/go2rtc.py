"""Auto-download and manage go2rtc for audio backchannel."""

import asyncio
import hashlib
import json
import logging
import os
import platform
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger(__name__)

GO2RTC_VERSION = "v1.9.14"
GITHUB_RELEASE_DOWNLOAD_URL = (
    f"https://github.com/AlexxIT/go2rtc/releases/download/{GO2RTC_VERSION}"
)


@dataclass(frozen=True)
class ReleaseArtifact:
    """Pinned identity and digest for one go2rtc release artifact."""

    name: str
    version: str
    url: str
    sha256: str


# Digests published by AlexxIT/go2rtc for v1.9.14. Updating the version requires
# updating these values from the upstream release and running the integrity tests.
PINNED_ARTIFACTS: dict[str, tuple[str, str]] = {
    "go2rtc_linux_amd64": (
        "go2rtc_linux_amd64",
        "32d616af226bd731678ffde328b94cfb94e30339bfefc469cfb76323144615a6",
    ),
    "go2rtc_linux_arm64": (
        "go2rtc_linux_arm64",
        "359fabade8a7a51e81a55fe6df6b0ef81764a5e1d63179577534eaaa71904b50",
    ),
    "go2rtc_linux_arm": (
        "go2rtc_linux_arm",
        "4d7e1639af5a2722a28e864468fd8099b3c1682565446c798bf9e3b38fde12e4",
    ),
    "go2rtc_linux_armv6": (
        "go2rtc_linux_armv6",
        "4dc20370556b29f3a90f4c7a09dcd95472c8f74cca56d4d1fb91f32bdd15174c",
    ),
    "go2rtc_mac_amd64": (
        "go2rtc_mac_amd64.zip",
        "9b0b9a27a4dc3a5b8b93376e7e8fc2787c6af624a512842622be84aec0171c7a",
    ),
    "go2rtc_mac_arm64": (
        "go2rtc_mac_arm64.zip",
        "919b78adc759d6b3883d1e1b2ac915ac0985bb903ff1897b4d228527bd64690c",
    ),
    "go2rtc_win64": (
        "go2rtc_win64.zip",
        "dd4167d75cb04abe618855b7c71f8658bd009f60c1a71835d134d2c11c939907",
    ),
    "go2rtc_win32": (
        "go2rtc_win32.zip",
        "6fafb817477f4d34e5edfd8bb3c547151dfc5c404bde41e274db146b17ed5c03",
    ),
}

PLATFORM_MAP = {
    ("linux", "x86_64"): "go2rtc_linux_amd64",
    ("linux", "aarch64"): "go2rtc_linux_arm64",
    ("linux", "armv7l"): "go2rtc_linux_arm",
    ("linux", "armv6l"): "go2rtc_linux_armv6",
    ("darwin", "x86_64"): "go2rtc_mac_amd64",
    ("darwin", "arm64"): "go2rtc_mac_arm64",
    ("windows", "amd64"): "go2rtc_win64",
    ("windows", "x86"): "go2rtc_win32",
}


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "embodied-claude" / "go2rtc"


def default_bin_path() -> Path:
    name = "go2rtc.exe" if platform.system().lower() == "windows" else "go2rtc"
    return default_cache_dir() / name


def default_config_path() -> Path:
    return default_cache_dir() / "go2rtc.yaml"


def detect_platform() -> str:
    """Detect the go2rtc asset name for the current platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    key = (system, machine)
    asset_name = PLATFORM_MAP.get(key)
    if not asset_name:
        raise RuntimeError(f"Unsupported platform: {system}/{machine}")
    return asset_name


def _get_release_artifact(asset_name: str) -> ReleaseArtifact:
    """Resolve a supported platform to an immutable release artifact."""
    try:
        filename, digest = PINNED_ARTIFACTS[asset_name]
    except KeyError as exc:
        raise RuntimeError(
            f"No pinned go2rtc artifact for platform asset '{asset_name}'"
        ) from exc

    return ReleaseArtifact(
        name=filename,
        version=GO2RTC_VERSION,
        url=f"{GITHUB_RELEASE_DOWNLOAD_URL}/{filename}",
        sha256=digest,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_file(url: str, dest: Path, expected_sha256: str) -> None:
    """Download, verify, and atomically commit a release artifact."""
    normalized_digest = expected_sha256.strip().lower()
    if len(normalized_digest) != 64 or any(
        character not in "0123456789abcdef" for character in normalized_digest
    ):
        raise ValueError("Expected SHA-256 digest must contain 64 hexadecimal characters")

    dest.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(
        prefix=f".{dest.name}.",
        suffix=".tmp",
        dir=dest.parent,
    )
    os.close(descriptor)
    tmp_path = Path(tmp_name)
    try:
        urllib.request.urlretrieve(url, str(tmp_path))
        actual_sha256 = _sha256_file(tmp_path)
        if actual_sha256 != normalized_digest:
            raise RuntimeError(
                "Downloaded go2rtc artifact checksum mismatch: "
                f"expected {normalized_digest}, got {actual_sha256}"
            )
        os.replace(tmp_path, dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _extract_binary(zip_path: Path, bin_path: Path) -> None:
    """Extract exactly one expected go2rtc executable and commit it atomically."""
    expected_name = "go2rtc.exe" if bin_path.suffix.lower() == ".exe" else "go2rtc"
    descriptor, tmp_name = tempfile.mkstemp(
        prefix=f".{bin_path.name}.",
        suffix=".tmp",
        dir=bin_path.parent,
    )
    os.close(descriptor)
    tmp_path = Path(tmp_name)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = [
                name
                for name in archive.namelist()
                if not name.endswith("/") and Path(name).name.lower() == expected_name
            ]
            if len(members) != 1:
                raise RuntimeError(
                    f"Expected exactly one {expected_name} in go2rtc archive, "
                    f"found {len(members)}"
                )
            with archive.open(members[0]) as source, tmp_path.open("wb") as destination:
                shutil.copyfileobj(source, destination)
        os.replace(tmp_path, bin_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _manifest_path(bin_path: Path) -> Path:
    return bin_path.with_name(f"{bin_path.name}.manifest.json")


def _write_manifest(bin_path: Path, artifact: ReleaseArtifact) -> None:
    manifest_path = _manifest_path(bin_path)
    descriptor, tmp_name = tempfile.mkstemp(
        prefix=f".{manifest_path.name}.",
        suffix=".tmp",
        dir=manifest_path.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_handle:
            json.dump(
                {
                    "version": artifact.version,
                    "asset": artifact.name,
                    "asset_sha256": artifact.sha256,
                    "binary_sha256": _sha256_file(bin_path),
                },
                file_handle,
                indent=2,
            )
            file_handle.write("\n")
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(tmp_path, manifest_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _managed_binary_is_verified(bin_path: Path, artifact: ReleaseArtifact) -> bool:
    manifest_path = _manifest_path(bin_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return False
        if manifest.get("version") != artifact.version:
            return False
        if manifest.get("asset") != artifact.name:
            return False
        if manifest.get("asset_sha256") != artifact.sha256:
            return False
        binary_sha256 = manifest.get("binary_sha256")
        if not isinstance(binary_sha256, str) or len(binary_sha256) != 64:
            return False
        return _sha256_file(bin_path) == binary_sha256
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def ensure_binary(bin_path: Path | None = None) -> Path:
    """Ensure a verified go2rtc binary exists, downloading if needed."""
    managed_path = bin_path is None
    if bin_path is None:
        bin_path = default_bin_path()

    # An explicit existing GO2RTC_BIN is operator-managed and intentionally
    # bypasses the managed cache policy.
    if bin_path.exists() and not managed_path:
        return bin_path

    asset_name = detect_platform()
    artifact = _get_release_artifact(asset_name)

    if bin_path.exists() and _managed_binary_is_verified(bin_path, artifact):
        return bin_path

    if bin_path.exists():
        logger.warning("go2rtc managed cache is unverified or stale; replacing it")

    logger.info("Downloading pinned go2rtc %s", artifact.version)
    logger.info("Downloading go2rtc from %s", artifact.url)

    is_zip = artifact.name.endswith(".zip")
    if is_zip:
        zip_path = bin_path.with_name(f"{bin_path.name}.{artifact.version}.zip")
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _download_file(artifact.url, zip_path, artifact.sha256)
            _extract_binary(zip_path, bin_path)
        finally:
            zip_path.unlink(missing_ok=True)
    else:
        _download_file(artifact.url, bin_path, artifact.sha256)

    # Make executable on Unix
    if platform.system().lower() != "windows":
        bin_path.chmod(bin_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

    try:
        _write_manifest(bin_path, artifact)
    except Exception:
        bin_path.unlink(missing_ok=True)
        raise

    logger.info("go2rtc downloaded to %s", bin_path)
    return bin_path


def generate_config(
    config_path: Path,
    stream_name: str,
    camera_host: str,
    username: str,
    password: str,
    ffmpeg_bin: str | None = None,
) -> Path:
    """Generate go2rtc.yaml config file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_ffmpeg = ffmpeg_bin or "ffmpeg"
    encoded_username = quote(username, safe="")
    encoded_password = quote(password, safe="")
    content = (
        f"streams:\n"
        f"  {stream_name}:\n"
        f"    - rtsp://{encoded_username}:{encoded_password}@{camera_host}:554/stream1\n"
        f"    - tapo://{encoded_password}@{camera_host}\n"
        f"\n"
        f"ffmpeg:\n"
        f"  bin: {resolved_ffmpeg}\n"
        f"\n"
        f"api:\n"
        f"  listen: \":1984\"\n"
        f"\n"
        f"log:\n"
        f"  level: info\n"
    )
    config_path.write_text(content, encoding="utf-8")
    if os.name != "nt":
        config_path.chmod(0o600)
    logger.info("go2rtc config written to %s", config_path)
    return config_path


class Go2RTCProcess:
    """Manage go2rtc daemon lifecycle."""

    def __init__(self, bin_path: Path, config_path: Path, api_url: str = "http://localhost:1984"):
        self._bin_path = bin_path
        self._config_path = config_path
        self._api_url = api_url
        self._process: subprocess.Popen | None = None

    def is_running(self) -> bool:
        """Check if go2rtc is already responding."""
        try:
            req = urllib.request.Request(f"{self._api_url}/api", method="GET")
            with urllib.request.urlopen(req, timeout=2):
                return True
        except Exception:
            return False

    async def start(self) -> None:
        """Start go2rtc as a background process."""
        if self.is_running():
            logger.info("go2rtc already running at %s", self._api_url)
            return

        self._process = subprocess.Popen(
            [str(self._bin_path), "-config", str(self._config_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        # Wait briefly and verify it started
        await asyncio.sleep(1.5)

        if self._process.poll() is not None:
            stderr = self._process.stderr.read().decode() if self._process.stderr else ""
            raise RuntimeError(f"go2rtc exited immediately: {stderr}")

        if not self.is_running():
            stderr = ""
            if self._process.stderr:
                self._process.stderr.close()
            self._process.terminate()
            raise RuntimeError("go2rtc started but not responding")

        logger.info("go2rtc started (pid=%d)", self._process.pid)

    def stop(self) -> None:
        """Stop go2rtc process."""
        if self._process is None or self._process.poll() is not None:
            return
        logger.info("Stopping go2rtc (pid=%d)", self._process.pid)
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2)
