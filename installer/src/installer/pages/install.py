"""Installation page"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
    QWizardPage,
)

_ACTION_GATE_MATCHER = (
    "mcp__wifi-cam__.*|mcp__usb-webcam__.*|mcp__memory__.*|"
    "mcp__system-temperature__.*|mcp__elevenlabs-t2s__.*"
)
_ACTION_GATE_STATUS = "Checking Sanpoloid action policy"


class InstallationWorker(QThread):
    """Worker thread for installation tasks"""

    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        """Run installation"""
        try:
            # Get repository path
            # __file__ is installer/src/installer/pages/install.py
            # Go up 5 levels: pages/ -> installer/ -> src/ -> installer/ -> repo root
            repo_path = Path(__file__).parent.parent.parent.parent.parent.absolute()
            self.progress.emit(f"📁 Repository path: {repo_path}")
            self.progress.emit(f"📁 Path exists: {repo_path.exists()}")

            # List subdirectories to verify
            if repo_path.exists():
                subdirs = [d.name for d in repo_path.iterdir() if d.is_dir()]
                self.progress.emit(f"📁 Found directories: {', '.join(subdirs)}")

            # Create MCP configuration
            self.progress.emit("\n📝 Creating MCP configuration...")
            mcp_config = self._create_mcp_config(repo_path)

            # Install the policy host first, then each enabled MCP server.
            for project_name, project_path in self._dependency_projects(repo_path):
                if not project_path.exists():
                    raise FileNotFoundError(f"{project_name} directory not found at {project_path}")
                self.progress.emit(f"\n📦 Installing {project_name} dependencies...")
                self._run_uv_sync(project_path)

            action_gate = self._action_gate_executable(repo_path)
            if not action_gate.is_file():
                raise FileNotFoundError(
                    f"action gate executable not found after uv sync: {action_gate}"
                )
            action_gate_wrapper = self._action_gate_wrapper(repo_path)
            if not action_gate_wrapper.is_file():
                raise FileNotFoundError(
                    f"action gate wrapper not found: {action_gate_wrapper}"
                )

            # Install the user-scope gate before exposing MCP servers globally.
            user_settings_path = Path.home() / ".claude" / "settings.json"
            self.progress.emit(f"🛡️ Writing action gate hook to: {user_settings_path}")
            self._backup_if_exists(user_settings_path)
            self._update_claude_user_hooks(user_settings_path, repo_path)

            # Write MCP configuration only after all project installs and the gate succeed.
            settings_path = Path.home() / ".claude.json"
            self.progress.emit(f"💾 Writing to: {settings_path}")

            self._backup_if_exists(settings_path)

            self._update_claude_settings(settings_path, mcp_config)
            self.progress.emit("✅ MCP configuration updated")

            self.progress.emit("\n✅ Installation completed successfully!")
            self.finished.emit(True, "Installation completed")

        except Exception as e:  # noqa: BLE001 - surface worker failures to the UI
            error_msg = f"Installation failed: {e!s}"
            self.progress.emit(f"\n❌ {error_msg}")
            self.finished.emit(False, error_msg)

    def _dependency_projects(self, repo_path: Path) -> list[tuple[str, Path]]:
        """Return projects that must be synced before configuration is exposed."""
        projects = [("action-policy", repo_path / "action-policy")]
        if self.config.get("wifi_camera_enabled"):
            projects.append(("wifi-cam-mcp", repo_path / "wifi-cam-mcp"))
        if self.config.get("usb_camera_enabled"):
            projects.append(("usb-webcam-mcp", repo_path / "usb-webcam-mcp"))
        if self.config.get("memory_enabled"):
            projects.append(("memory-mcp", repo_path / "memory-mcp"))
        projects.append(
            ("system-temperature-mcp", repo_path / "system-temperature-mcp")
        )
        return projects

    @staticmethod
    def _action_gate_executable(repo_path: Path) -> Path:
        """Return the platform-specific console entry point created by uv sync."""
        script_directory = "Scripts" if os.name == "nt" else "bin"
        executable = (
            "embodied-action-gate.exe"
            if os.name == "nt"
            else "embodied-action-gate"
        )
        return (
            repo_path.absolute()
            / "action-policy"
            / ".venv"
            / script_directory
            / executable
        )

    @staticmethod
    def _action_gate_wrapper(repo_path: Path) -> Path:
        """Return the platform-specific blocking hook wrapper."""
        extension = "ps1" if os.name == "nt" else "sh"
        return repo_path.absolute() / ".claude" / "hooks" / f"action-gate.{extension}"

    def _action_gate_hook_handler(self, repo_path: Path) -> dict:
        """Build the user-scope handler with absolute, platform-safe paths."""
        wrapper = self._action_gate_wrapper(repo_path)
        action_policy = repo_path.absolute() / "action-policy"
        if os.name == "nt":
            return {
                "type": "command",
                "command": "powershell.exe",
                "args": [
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(wrapper),
                    "-ActionPolicyDirectory",
                    str(action_policy),
                ],
                "timeout": 10,
                "statusMessage": _ACTION_GATE_STATUS,
            }
        return {
            "type": "command",
            "command": str(wrapper),
            "args": [str(action_policy)],
            "timeout": 10,
            "statusMessage": _ACTION_GATE_STATUS,
        }

    @staticmethod
    def _is_managed_action_gate_handler(handler: object) -> bool:
        """Identify only a hook handler owned by this installer."""
        if not (
            isinstance(handler, dict)
            and handler.get("type") == "command"
            and handler.get("statusMessage") == _ACTION_GATE_STATUS
        ):
            return False

        command = handler.get("command")
        if not isinstance(command, str):
            return False
        command_name = command.replace("\\", "/").rsplit("/", maxsplit=1)[-1].lower()
        if command_name in {
            "action-gate.sh",
            "embodied-action-gate",
            "embodied-action-gate.exe",
        }:
            return True
        if command_name not in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            return False

        args = handler.get("args")
        return bool(
            isinstance(args, list)
            and any(
                isinstance(argument, str)
                and argument.replace("\\", "/")
                .rsplit("/", maxsplit=1)[-1]
                .lower()
                == "action-gate.ps1"
                for argument in args
            )
        )

    def _update_claude_user_hooks(
        self,
        settings_path: Path,
        repo_path: Path,
    ) -> None:
        """Idempotently merge the global Sanpoloid action gate hook."""
        existing: dict = {}
        if settings_path.exists():
            with open(settings_path, "r", encoding="utf-8") as file:
                loaded = json.load(file)
            if not isinstance(loaded, dict):
                raise ValueError("Claude user settings root must be a JSON object")
            existing = loaded

        hooks = existing.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise ValueError("Claude user settings hooks must be a JSON object")
        pre_tool_use = hooks.setdefault("PreToolUse", [])
        if not isinstance(pre_tool_use, list):
            raise ValueError("Claude user settings PreToolUse must be a JSON array")

        retained = []
        for group in pre_tool_use:
            if not isinstance(group, dict):
                retained.append(group)
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                if group.get("matcher") == _ACTION_GATE_MATCHER:
                    raise ValueError(
                        "Sanpoloid PreToolUse hook group handlers must be a JSON array"
                    )
                retained.append(group)
                continue
            custom_handlers = [
                handler
                for handler in handlers
                if not self._is_managed_action_gate_handler(handler)
            ]
            if len(custom_handlers) == len(handlers):
                retained.append(group)
            elif custom_handlers:
                retained_group = dict(group)
                retained_group["hooks"] = custom_handlers
                retained.append(retained_group)
        retained.append(
            {
                "matcher": _ACTION_GATE_MATCHER,
                "hooks": [self._action_gate_hook_handler(repo_path)],
            }
        )
        hooks["PreToolUse"] = retained
        self._write_json_atomic(settings_path, existing)

    def _backup_if_exists(self, path: Path) -> None:
        """Create the installer's existing single recoverable backup."""
        if not path.exists():
            return
        backup_path = path.with_suffix(".json.backup")
        self.progress.emit(f"💾 Creating backup: {backup_path}")
        shutil.copy2(path, backup_path)

    @staticmethod
    def _write_json_atomic(path: Path, data: dict) -> None:
        """Write one JSON settings file without exposing a partial file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                json.dump(data, file, indent=2, ensure_ascii=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def _create_mcp_config(self, repo_path):
        """Create MCP server configuration"""
        config = {"mcpServers": {}}

        # Wi-Fi camera
        if self.config.get("wifi_camera_enabled"):
            config["mcpServers"]["wifi-cam"] = {
                "type": "stdio",
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    str(repo_path / "wifi-cam-mcp"),
                    "wifi-cam-mcp",
                ],
                "env": {
                    "TAPO_CAMERA_HOST": self.config.get("tapo_host", ""),
                    "TAPO_USERNAME": self.config.get("tapo_username", ""),
                    "TAPO_PASSWORD": self.config.get("tapo_password", ""),
                },
            }

        # USB camera
        if self.config.get("usb_camera_enabled"):
            config["mcpServers"]["usb-webcam"] = {
                "type": "stdio",
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    str(repo_path / "usb-webcam-mcp"),
                    "usb-webcam-mcp",
                ],
                "env": {}
            }

        # Memory
        if self.config.get("memory_enabled"):
            config["mcpServers"]["memory"] = {
                "type": "stdio",
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    str(repo_path / "memory-mcp"),
                    "memory-mcp",
                ],
                "env": {}
            }

        # System temperature
        config["mcpServers"]["system-temperature"] = {
            "type": "stdio",
            "command": "uv",
            "args": [
                "run",
                "--directory",
                str(repo_path / "system-temperature-mcp"),
                "system-temperature-mcp",
            ],
            "env": {}
        }

        return config

    def _update_claude_settings(self, settings_path, mcp_config):
        """Update Claude Code .claude.json configuration"""
        # No need to create parent directory for ~/.claude.json

        # Load existing settings
        existing = {}
        if settings_path.exists():
            with open(settings_path, "r", encoding="utf-8") as f:
                existing = json.load(f)

        # Merge MCP servers
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}

        existing["mcpServers"].update(mcp_config["mcpServers"])

        self._write_json_atomic(settings_path, existing)

    def _run_uv_sync(self, directory):
        """Run uv sync in a directory"""
        self.progress.emit(f"Running uv sync in: {directory}")

        # Ensure directory exists
        if not directory.exists():
            raise FileNotFoundError(f"Directory does not exist: {directory}")

        try:
            result = subprocess.run(
                ["uv", "sync", "--locked"],
                cwd=str(directory),  # Convert Path to string for Windows compatibility
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes timeout
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(f"uv sync failed in {directory.name}: {result.stderr}")

            self.progress.emit(result.stdout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"uv sync timed out in {directory.name}") from None


class InstallationPage(QWizardPage):
    """Run installation"""

    def __init__(self):
        super().__init__()
        self.setTitle("Installation")
        self.setSubTitle("Installing Embodied Claude MCP servers")

        layout = QVBoxLayout()

        # Progress label
        self.progress_label = QLabel("Ready to install...")
        layout.addWidget(self.progress_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        self.setLayout(layout)

        # Installation worker
        self.worker = None
        self.installation_complete = False

    def initializePage(self):
        """Start installation when page is shown"""
        # Gather configuration from previous pages
        config = {
            "wifi_camera_enabled": self.field("wifi_camera_enabled"),
            "tapo_host": self.field("tapo_host"),
            "tapo_username": self.field("tapo_username"),
            "tapo_password": self.field("tapo_password"),
            "usb_camera_enabled": self.field("usb_camera_enabled"),
            "memory_enabled": self.field("memory_enabled"),
        }

        # Start installation
        self.progress_label.setText("Installing...")
        self.progress_bar.show()
        self.log_output.clear()

        self.worker = InstallationWorker(config)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, message):
        """Handle progress updates"""
        self.log_output.append(message)

    def _on_finished(self, success, message):
        """Handle installation completion"""
        self.progress_bar.hide()
        self.installation_complete = success

        if success:
            self.progress_label.setText("✅ Installation completed!")
            self.progress_label.setStyleSheet("QLabel { color: green; font-weight: bold; }")
        else:
            self.progress_label.setText(f"❌ Installation failed: {message}")
            self.progress_label.setStyleSheet("QLabel { color: red; font-weight: bold; }")

        self.completeChanged.emit()

    def isComplete(self):
        """Page is complete when installation finishes successfully"""
        return self.installation_complete
