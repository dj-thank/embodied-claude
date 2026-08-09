"""Hardware-free tests for installer configuration and page logic."""

import json
import os
import runpy
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QWizardPage

from installer.main import EmbodiedClaudeInstaller
from installer.pages.camera import CameraSelectionPage
from installer.pages.complete import CompletePage
from installer.pages.dependencies import DependenciesPage
from installer.pages.install import InstallationWorker
from installer.runtime_profiles import action_gate_matcher


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Create the application object required by Qt widgets."""
    return QApplication.instance() or QApplication([])


def test_camera_page_allows_memory_without_camera(qapp: QApplication) -> None:
    page = CameraSelectionPage()

    assert not page.isComplete()
    page.use_wifi_camera.setChecked(False)
    assert page.isComplete()

    page.use_memory.setChecked(False)
    assert page.isComplete()

    page.use_system_temperature.setChecked(False)
    assert not page.isComplete()


def test_runtime_profile_selection_updates_visible_components(
    qapp: QApplication,
) -> None:
    page = CameraSelectionPage()

    page.runtime_profile.setCurrentText("Lite")
    assert not page.use_wifi_camera.isChecked()
    assert page.wifi_form.isHidden()
    assert not page.use_usb_camera.isChecked()
    assert page.usb_camera_list.isHidden()
    assert page.use_memory.isChecked()
    assert page.memory_backend.currentText().startswith("SQLite")
    assert page.use_system_temperature.isChecked()
    assert not page.use_elevenlabs.isChecked()

    page.runtime_profile.setCurrentText("Full")
    assert page.use_wifi_camera.isChecked()
    assert not page.wifi_form.isHidden()
    assert page.use_usb_camera.isChecked()
    assert not page.usb_camera_list.isHidden()
    assert page.use_memory.isChecked()
    assert page.memory_backend.currentText().startswith("Chroma")
    assert page.use_system_temperature.isChecked()
    assert page.use_elevenlabs.isChecked()


def test_profile_precedes_dependency_check_and_changes_requirements(
    qapp: QApplication,
) -> None:
    wizard = EmbodiedClaudeInstaller()
    pages = [wizard.page(page_id) for page_id in wizard.pageIds()]
    profile_page = next(page for page in pages if isinstance(page, CameraSelectionPage))
    dependencies_page = next(
        page for page in pages if isinstance(page, DependenciesPage)
    )

    assert pages.index(profile_page) < pages.index(dependencies_page)
    profile_page.runtime_profile.setCurrentText("Lite")
    assert dependencies_page._required_dependencies() == ("Python", "uv")
    assert "#0f172a" in wizard.styleSheet()
    wizard.show()
    qapp.processEvents()
    header_labels = []
    for label in wizard.findChildren(QLabel):
        parent = label.parentWidget()
        while parent is not None and parent is not wizard:
            if isinstance(parent, QWizardPage):
                break
            parent = parent.parentWidget()
        else:
            header_labels.append(label)
    assert header_labels
    assert all("#0f172a" in label.styleSheet() for label in header_labels)


def test_completion_page_lists_only_selected_servers(qapp: QApplication) -> None:
    wizard = EmbodiedClaudeInstaller()
    pages = [wizard.page(page_id) for page_id in wizard.pageIds()]
    profile_page = next(page for page in pages if isinstance(page, CameraSelectionPage))
    complete_page = next(page for page in pages if isinstance(page, CompletePage))
    profile_page.runtime_profile.setCurrentText("Lite")

    complete_page.initializePage()
    rendered = complete_page.next_steps.toPlainText()

    assert "system-temperature" in rendered
    assert "memory" in rendered
    assert "wifi-cam" not in rendered


def test_pyinstaller_entrypoint_imports_package_without_starting_ui() -> None:
    installer_root = Path(__file__).parents[1]

    namespace = runpy.run_path(
        str(installer_root / "pyinstaller_entrypoint.py"),
        run_name="bundle_import_smoke",
    )

    assert callable(namespace["main"])
    assert "pyinstaller_entrypoint.py" in (
        installer_root / "embodied-claude-installer.spec"
    ).read_text(encoding="utf-8")


def test_create_mcp_config_uses_valid_uv_arguments() -> None:
    worker = InstallationWorker(
        {
            "wifi_camera_enabled": True,
            "tapo_host": "192.0.2.10",
            "tapo_username": "camera-user",
            "tapo_password": "camera-password",
            "usb_camera_enabled": True,
            "memory_enabled": True,
        }
    )

    config = worker._create_mcp_config(Path("/repo"))

    assert set(config["mcpServers"]) == {
        "wifi-cam",
        "usb-webcam",
        "memory",
        "system-temperature",
    }
    for server in config["mcpServers"].values():
        assert server["args"][0] == "run"
        assert server["args"][1] == "--directory"


def test_update_claude_settings_preserves_existing_values(tmp_path: Path) -> None:
    worker = InstallationWorker({})
    settings_path = tmp_path / "claude.json"
    settings_path.write_text(json.dumps({"existing": True}), encoding="utf-8")

    worker._update_claude_settings(
        settings_path,
        {"mcpServers": {"memory": {"command": "uv"}}},
    )

    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["existing"] is True
    assert saved["mcpServers"]["memory"]["command"] == "uv"


def test_update_claude_settings_replaces_managed_servers_for_profile_switch(
    tmp_path: Path,
) -> None:
    worker = InstallationWorker({"runtime_profile": "lite"})
    settings_path = tmp_path / "claude.json"
    settings_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "wifi-cam": {"command": "old-wifi"},
                    "memory": {"command": "old-memory"},
                    "user-owned": {"command": "keep-me"},
                }
            }
        ),
        encoding="utf-8",
    )

    worker._update_claude_settings(
        settings_path,
        worker._create_mcp_config(Path("/repo")),
    )

    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert set(saved["mcpServers"]) == {
        "memory",
        "system-temperature",
        "user-owned",
    }
    assert saved["mcpServers"]["user-owned"]["command"] == "keep-me"


def test_dependency_projects_always_include_action_policy() -> None:
    worker = InstallationWorker({})

    projects = worker._dependency_projects(Path("/repo"))

    assert projects[0].name == "action-policy"
    assert projects[0].path == Path("/repo/action-policy")
    assert any(project.name == "system-temperature-mcp" for project in projects)


def test_uv_sync_uses_committed_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = InstallationWorker({})
    observed: dict[str, object] = {}

    class SuccessfulSync:
        returncode = 0
        stdout = "sync complete"
        stderr = ""

    def fake_run(command: list[str], **kwargs: object) -> SuccessfulSync:
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SuccessfulSync()

    monkeypatch.setattr("installer.pages.install.subprocess.run", fake_run)

    worker._run_uv_sync(tmp_path, extras=("chroma",))

    assert observed["command"] == ["uv", "sync", "--locked", "--extra", "chroma"]


def test_user_action_gate_hook_merge_is_preserving_and_idempotent(
    tmp_path: Path,
) -> None:
    worker = InstallationWorker({})
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    existing_hook = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "existing-check"}],
    }
    colocated_custom_handler = {
        "type": "command",
        "command": "custom-embodied-audit",
    }
    status_collision_handler = {
        "type": "command",
        "command": "custom-policy",
        "statusMessage": "Checking Sanpoloid action policy",
    }
    previous_managed_handler = {
        "type": "command",
        "command": "/old/repo/action-policy/.venv/bin/embodied-action-gate",
        "args": [],
        "timeout": 10,
        "statusMessage": "Checking Sanpoloid action policy",
    }
    embodied_matcher = action_gate_matcher()
    settings_path.write_text(
        json.dumps(
            {
                "theme": "dark",
                "hooks": {
                    "PreToolUse": [
                        existing_hook,
                        {
                            "matcher": "mcp__memory__.*",
                            "hooks": [previous_managed_handler],
                        },
                        {
                            "matcher": embodied_matcher,
                            "hooks": [
                                colocated_custom_handler,
                                status_collision_handler,
                            ],
                        },
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    repo_path = tmp_path / "repo"

    worker._update_claude_user_hooks(settings_path, repo_path)
    worker._update_claude_user_hooks(settings_path, repo_path)

    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["theme"] == "dark"
    assert existing_hook in saved["hooks"]["PreToolUse"]
    handlers = [
        handler
        for group in saved["hooks"]["PreToolUse"]
        for handler in group.get("hooks", [])
        if isinstance(handler, dict)
    ]
    assert colocated_custom_handler in handlers
    assert status_collision_handler in handlers
    managed = [
        handler
        for handler in handlers
        if worker._is_managed_action_gate_handler(handler)
    ]
    assert len(managed) == 1
    managed_groups = [
        group
        for group in saved["hooks"]["PreToolUse"]
        if managed[0] in group.get("hooks", [])
    ]
    assert len(managed_groups) == 1
    assert managed_groups[0]["matcher"] == action_gate_matcher()

    if os.name == "nt":
        assert managed[0]["command"] == "powershell.exe"
        assert managed[0]["args"][:4] == [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ]
        assert Path(managed[0]["args"][4]).name == "action-gate.ps1"
        assert managed[0]["args"][5] == "-ActionPolicyDirectory"
        assert Path(managed[0]["args"][6]).name == "action-policy"
    else:
        assert Path(managed[0]["command"]).name == "action-gate.sh"
        assert len(managed[0]["args"]) == 1
        assert Path(managed[0]["args"][0]).name == "action-policy"
    assert list(settings_path.parent.glob(".settings.json.*.tmp")) == []


def test_installer_publishes_global_mcp_config_only_after_user_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = InstallationWorker({})
    action_gate = tmp_path / "embodied-action-gate.exe"
    action_gate.touch()
    wrapper = tmp_path / "action-gate.ps1"
    wrapper.touch()
    writes: list[str] = []

    monkeypatch.setattr(worker, "_create_mcp_config", lambda _repo: {"mcpServers": {}})
    monkeypatch.setattr(worker, "_dependency_projects", lambda _repo: [])
    monkeypatch.setattr(worker, "_action_gate_executable", lambda _repo: action_gate)
    monkeypatch.setattr(worker, "_action_gate_wrapper", lambda _repo: wrapper)
    monkeypatch.setattr(worker, "_backup_if_exists", lambda _path: None)
    monkeypatch.setattr(
        worker,
        "_update_claude_user_hooks",
        lambda _settings, _repo: writes.append("user-gate"),
    )
    monkeypatch.setattr(
        worker,
        "_update_claude_settings",
        lambda _settings, _config: writes.append("global-mcp"),
    )

    worker.run()

    assert writes == ["user-gate", "global-mcp"]


def test_user_action_gate_hook_rejects_invalid_existing_shape_without_overwrite(
    tmp_path: Path,
) -> None:
    worker = InstallationWorker({})
    settings_path = tmp_path / "settings.json"
    original = json.dumps({"hooks": {"PreToolUse": {"not": "a list"}}})
    settings_path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="PreToolUse"):
        worker._update_claude_user_hooks(settings_path, tmp_path / "repo")

    assert settings_path.read_text(encoding="utf-8") == original
