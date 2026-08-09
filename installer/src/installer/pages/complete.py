"""Completion page"""
from PyQt6.QtWidgets import (
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWizardPage,
)

from installer.runtime_profiles import enabled_server_ids, runtime_config_from_fields

_SERVER_DESCRIPTIONS = {
    "wifi-cam": "Eyes, neck, ears (Wi-Fi camera)",
    "usb-webcam": "Eyes (USB webcam)",
    "memory": "Long-term semantic memory (ChromaDB)",
    "system-temperature": "Body temperature sense",
    "elevenlabs-t2s": "Voice (ElevenLabs; API key supplied externally)",
}


class CompletePage(QWizardPage):
    """Installation complete page"""

    def __init__(self):
        super().__init__()
        self.setTitle("Installation Complete!")
        self.setSubTitle("Embodied Claude is ready to use")

        layout = QVBoxLayout()

        # Success message
        success_label = QLabel("✅ Installation completed successfully!")
        success_label.setStyleSheet(
            "QLabel { color: green; font-size: 16px; font-weight: bold; }"
        )
        layout.addWidget(success_label)

        # Next steps
        self.next_steps = QTextBrowser()
        self.next_steps.setOpenExternalLinks(True)
        layout.addWidget(self.next_steps)

        self.setLayout(layout)

    def initializePage(self) -> None:
        """Render exactly the MCP servers selected by the runtime profile."""
        config = runtime_config_from_fields(self.field)
        server_items = "".join(
            f"<li><strong>{server_id}</strong> - {_SERVER_DESCRIPTIONS[server_id]}</li>"
            for server_id in enabled_server_ids(config)
        )
        self.next_steps.setHtml(
            f"""
            <h3>Next Steps</h3>

            <ol>
                <li><strong>Restart Claude Code</strong> to load the new MCP servers</li>
                <li><strong>Test your setup:</strong>
                    <ul>
                        <li>"今何が見える?" (What do you see now?)</li>
                        <li>"左を見て" (Look left)</li>
                        <li>"何か聞こえる?" (Do you hear anything?)</li>
                        <li>"これ覚えておいて:..." (Remember this: ...)</li>
                    </ul>
                </li>
                <li><strong>Check the documentation:</strong>
                    <a href="https://github.com/dj-thank/embodied-claude">
                    GitHub Repository
                    </a>
                </li>
            </ol>

            <h3>Installed MCP Servers</h3>
            <p>Your Claude Code now has access to:</p>
            <ul>
                {server_items}
            </ul>

            <h3>Installed Action Gate</h3>
            <p>
                Sanpoloid MCP calls are routed through a user-scope PreToolUse gate.
                Outward actions require confirmation by default.
            </p>

            <h3>Troubleshooting</h3>
            <p>If you encounter issues:</p>
            <ul>
                <li>Check <code>~/.claude.json</code> for MCP configuration</li>
                <li>Check <code>~/.claude/settings.json</code> for the action gate hook</li>
                <li>View logs with <code>claude --verbose</code></li>
                <li>Report issues on
                    <a href="https://github.com/dj-thank/embodied-claude/issues">
                    GitHub Issues
                    </a>
                </li>
            </ul>

            <h3>Optional: Autonomous Action</h3>
            <p>
                To enable periodic autonomous observation (every 10 minutes),
                see the README section on "Autonomous Action Script".
            </p>
            """
        )
