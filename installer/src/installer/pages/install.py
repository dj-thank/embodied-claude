"""Installation page"""
import json
import shutil
import subprocess
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
    QWizardPage,
)


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

            # Install dependencies for each enabled MCP server
            projects = [("system-temperature-mcp", repo_path / "system-temperature-mcp")]
            if self.config.get("wifi_camera_enabled"):
                projects.insert(0, ("wifi-cam-mcp", repo_path / "wifi-cam-mcp"))

            if self.config.get("usb_camera_enabled"):
                projects.insert(0, ("usb-webcam-mcp", repo_path / "usb-webcam-mcp"))

            if self.config.get("memory_enabled"):
                projects.insert(0, ("memory-mcp", repo_path / "memory-mcp"))

            for project_name, project_path in projects:
                if not project_path.exists():
                    raise FileNotFoundError(f"{project_name} directory not found at {project_path}")
                self.progress.emit(f"\n📦 Installing {project_name} dependencies...")
                self._run_uv_sync(project_path)

            # Write to Claude Code configuration only after all project installs succeed.
            settings_path = Path.home() / ".claude.json"
            self.progress.emit(f"💾 Writing to: {settings_path}")

            if settings_path.exists():
                backup_path = settings_path.with_suffix(".json.backup")
                self.progress.emit(f"💾 Creating backup: {backup_path}")
                shutil.copy2(settings_path, backup_path)

            self._update_claude_settings(settings_path, mcp_config)
            self.progress.emit("✅ MCP configuration updated")

            self.progress.emit("\n✅ Installation completed successfully!")
            self.finished.emit(True, "Installation completed")

        except Exception as e:  # noqa: BLE001 - surface worker failures to the UI
            error_msg = f"Installation failed: {e!s}"
            self.progress.emit(f"\n❌ {error_msg}")
            self.finished.emit(False, error_msg)

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

        # Write back
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

    def _run_uv_sync(self, directory):
        """Run uv sync in a directory"""
        self.progress.emit(f"Running uv sync in: {directory}")

        # Ensure directory exists
        if not directory.exists():
            raise FileNotFoundError(f"Directory does not exist: {directory}")

        try:
            result = subprocess.run(
                ["uv", "sync"],
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
