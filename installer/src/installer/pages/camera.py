"""Camera selection page"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

from installer.runtime_profiles import (
    PROFILE_DESCRIPTIONS,
    RuntimeProfile,
    infer_runtime_profile,
    profile_component_flags,
    resolve_memory_backend,
)


class CameraSelectionPage(QWizardPage):
    """Select cameras to use"""

    def __init__(self):
        super().__init__()
        self.setTitle("Runtime Profile")
        self.setSubTitle("Choose a lightweight preset, then customize its MCP modules")

        content = QWidget()
        content.setObjectName("runtimeProfileContent")
        layout = QVBoxLayout(content)

        profile_group = QGroupBox("Runtime footprint")
        profile_layout = QVBoxLayout()
        self.runtime_profile = QComboBox()
        self.runtime_profile.addItems(["Lite", "Core", "Full", "Custom"])
        self.runtime_profile.setCurrentText("Core")
        profile_layout.addWidget(self.runtime_profile)
        self.profile_description = QLabel()
        self.profile_description.setWordWrap(True)
        self.profile_description.setStyleSheet("QLabel { color: #94a3b8; }")
        profile_layout.addWidget(self.profile_description)
        profile_group.setLayout(profile_layout)
        layout.addWidget(profile_group)

        # Wi-Fi Camera (Tapo) section
        wifi_group = QGroupBox("Wi-Fi PTZ Camera (Recommended)")
        wifi_layout = QVBoxLayout()

        self.use_wifi_camera = QCheckBox("Use Wi-Fi Camera (TP-Link Tapo)")
        self.use_wifi_camera.setChecked(True)
        self.use_wifi_camera.stateChanged.connect(self._on_wifi_camera_changed)
        wifi_layout.addWidget(self.use_wifi_camera)

        # WiFi camera configuration form
        self.wifi_form = QWidget()
        wifi_form_layout = QFormLayout()

        self.tapo_host = QLineEdit()
        self.tapo_host.setPlaceholderText("192.168.1.xxx")
        wifi_form_layout.addRow("Camera IP:", self.tapo_host)

        self.tapo_username = QLineEdit()
        self.tapo_username.setPlaceholderText("admin")
        wifi_form_layout.addRow("Username:", self.tapo_username)

        self.tapo_password = QLineEdit()
        self.tapo_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.tapo_password.setPlaceholderText("Password")
        wifi_form_layout.addRow("Password:", self.tapo_password)

        for field in (self.tapo_host, self.tapo_username, self.tapo_password):
            field.textChanged.connect(self._on_camera_config_changed)

        self.wifi_form.setLayout(wifi_form_layout)
        wifi_layout.addWidget(self.wifi_form)

        # Note about Tapo setup
        self.tapo_note = QLabel(
            "📝 Note: Create a local account on your Tapo camera first\n"
            "(Camera Settings → Advanced → Camera Account)"
        )
        self.tapo_note.setWordWrap(True)
        self.tapo_note.setStyleSheet("QLabel { color: #94a3b8; margin-top: 5px; }")
        wifi_layout.addWidget(self.tapo_note)

        wifi_group.setLayout(wifi_layout)
        layout.addWidget(wifi_group)

        # USB Camera section
        usb_group = QGroupBox("USB Webcam (Optional)")
        usb_layout = QVBoxLayout()

        self.use_usb_camera = QCheckBox("Use USB Webcam")
        self.use_usb_camera.stateChanged.connect(self._on_usb_camera_changed)
        usb_layout.addWidget(self.use_usb_camera)

        self.usb_camera_list = QListWidget()
        self.usb_camera_list.hide()
        usb_layout.addWidget(self.usb_camera_list)

        self.scan_button = QPushButton("Scan USB Cameras")
        self.scan_button.clicked.connect(self._scan_usb_cameras)
        self.scan_button.hide()
        usb_layout.addWidget(self.scan_button)

        usb_group.setLayout(usb_layout)
        layout.addWidget(usb_group)

        # Memory MCP section
        memory_group = QGroupBox("Long-term Memory (Brain)")
        memory_layout = QVBoxLayout()

        self.use_memory = QCheckBox("Enable long-term memory")
        self.use_memory.setChecked(True)
        self.use_memory.stateChanged.connect(self._on_memory_changed)
        memory_layout.addWidget(self.use_memory)

        self.memory_backend = QComboBox()
        self.memory_backend.addItems(
            ["SQLite FTS (lightweight)", "Chroma (semantic search)"]
        )
        self.memory_backend.setCurrentText("Chroma (semantic search)")
        memory_layout.addWidget(self.memory_backend)

        memory_note = QLabel(
            "💡 Memories will be stored in ~/.claude/memories/"
        )
        memory_note.setStyleSheet("QLabel { color: #94a3b8; }")
        memory_layout.addWidget(memory_note)

        memory_group.setLayout(memory_layout)
        layout.addWidget(memory_group)

        component_group = QGroupBox("Additional body modules")
        component_layout = QVBoxLayout()

        self.use_system_temperature = QCheckBox(
            "Enable system temperature sense (lightweight)"
        )
        component_layout.addWidget(self.use_system_temperature)

        self.use_elevenlabs = QCheckBox("Enable ElevenLabs speech output")
        component_layout.addWidget(self.use_elevenlabs)
        elevenlabs_note = QLabel(
            "🔑 The API key is not collected here; provide ELEVENLABS_API_KEY "
            "in the launch environment."
        )
        elevenlabs_note.setWordWrap(True)
        elevenlabs_note.setStyleSheet("QLabel { color: #94a3b8; }")
        component_layout.addWidget(elevenlabs_note)

        component_group.setLayout(component_layout)
        layout.addWidget(component_group)

        layout.addStretch()
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(content)
        scroll_area.setStyleSheet(
            "QScrollArea { border: 0; background: #0f172a; }"
            "QWidget#runtimeProfileContent { background: #0f172a; }"
        )
        page_layout = QVBoxLayout()
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll_area)
        self.setLayout(page_layout)

        # Register fields for later access
        self.registerField("wifi_camera_enabled", self.use_wifi_camera)
        self.registerField(
            "runtime_profile",
            self.runtime_profile,
            "currentText",
            self.runtime_profile.currentTextChanged,
        )
        self.registerField("tapo_host", self.tapo_host)
        self.registerField("tapo_username", self.tapo_username)
        self.registerField("tapo_password", self.tapo_password)
        self.registerField("usb_camera_enabled", self.use_usb_camera)
        self.registerField("memory_enabled", self.use_memory)
        self.registerField(
            "memory_backend",
            self.memory_backend,
            "currentText",
            self.memory_backend.currentTextChanged,
        )
        self.registerField(
            "system_temperature_enabled", self.use_system_temperature
        )
        self.registerField("elevenlabs_enabled", self.use_elevenlabs)

        self._updating_profile = False
        self.runtime_profile.currentTextChanged.connect(self._apply_profile)
        self.memory_backend.currentTextChanged.connect(self._on_components_changed)
        for checkbox in (
            self.use_wifi_camera,
            self.use_usb_camera,
            self.use_memory,
            self.use_system_temperature,
            self.use_elevenlabs,
        ):
            checkbox.stateChanged.connect(self._on_components_changed)
        self._apply_profile("Core")

    def _apply_profile(self, profile_name: str) -> None:
        """Apply a named footprint without fighting later manual choices."""
        profile = RuntimeProfile(profile_name.lower())
        self.profile_description.setText(PROFILE_DESCRIPTIONS[profile])
        if profile is RuntimeProfile.CUSTOM:
            return
        self._updating_profile = True
        try:
            for flag, checked in profile_component_flags(profile).items():
                self._component_widgets()[flag].setChecked(checked)
            backend = resolve_memory_backend({"runtime_profile": profile.value})
            self.memory_backend.setCurrentText(
                "SQLite FTS (lightweight)"
                if backend == "sqlite"
                else "Chroma (semantic search)"
            )
        finally:
            self._updating_profile = False
        self.completeChanged.emit()

    def _on_components_changed(self, _state: int) -> None:
        """Keep the displayed preset honest after a manual checkbox change."""
        if self._updating_profile:
            return
        config = {
            flag: checkbox.isChecked()
            for flag, checkbox in self._component_widgets().items()
        }
        config["memory_backend"] = self.memory_backend.currentText()
        profile = infer_runtime_profile(config)
        profile_name = profile.value.title()
        self.runtime_profile.blockSignals(True)
        try:
            self.runtime_profile.setCurrentText(profile_name)
            self.profile_description.setText(PROFILE_DESCRIPTIONS[profile])
        finally:
            self.runtime_profile.blockSignals(False)
        self.completeChanged.emit()

    def _on_memory_changed(self, state: int) -> None:
        """Only expose backend selection while long-term memory is enabled."""
        self.memory_backend.setEnabled(state == Qt.CheckState.Checked.value)
        self.completeChanged.emit()

    def _component_widgets(self) -> dict[str, QCheckBox]:
        """Bind domain selection flags to their visible controls."""
        return {
            "wifi_camera_enabled": self.use_wifi_camera,
            "usb_camera_enabled": self.use_usb_camera,
            "memory_enabled": self.use_memory,
            "system_temperature_enabled": self.use_system_temperature,
            "elevenlabs_enabled": self.use_elevenlabs,
        }

    def _on_wifi_camera_changed(self, state):
        """Show Wi-Fi details only when that body module is selected."""
        enabled = state == Qt.CheckState.Checked.value
        self.wifi_form.setVisible(enabled)
        self.tapo_note.setVisible(enabled)
        self.completeChanged.emit()

    def _on_usb_camera_changed(self, state):
        """Enable/disable USB camera list"""
        enabled = state == Qt.CheckState.Checked.value
        self.usb_camera_list.setVisible(enabled)
        self.scan_button.setVisible(enabled)
        self.completeChanged.emit()

    def _on_camera_config_changed(self, _text):
        """Refresh the wizard's completion state after editing credentials."""
        self.completeChanged.emit()

    def _scan_usb_cameras(self):
        """Scan for USB cameras"""
        self.usb_camera_list.clear()

        try:
            import cv2
            # Try to open cameras 0-9
            found_cameras = []
            for i in range(10):
                cap = cv2.VideoCapture(i)
                try:
                    if cap.isOpened():
                        found_cameras.append(f"Camera {i}")
                finally:
                    cap.release()

            if found_cameras:
                for camera in found_cameras:
                    item = QListWidgetItem(f"✅ {camera}")
                    self.usb_camera_list.addItem(item)
            else:
                item = QListWidgetItem("No USB cameras found")
                item.setForeground(Qt.GlobalColor.gray)
                self.usb_camera_list.addItem(item)

        except ImportError:
            item = QListWidgetItem("⚠️ OpenCV not installed")
            item.setForeground(Qt.GlobalColor.red)
            self.usb_camera_list.addItem(item)

    def isComplete(self):
        """Page is complete if at least one camera is selected with valid config"""
        if self.use_wifi_camera.isChecked() and not (
            self.tapo_host.text().strip()
            and self.tapo_username.text().strip()
            and self.tapo_password.text().strip()
        ):
            return False

        return any(
            checkbox.isChecked()
            for checkbox in (
                self.use_wifi_camera,
                self.use_usb_camera,
                self.use_memory,
                self.use_system_temperature,
                self.use_elevenlabs,
            )
        )
