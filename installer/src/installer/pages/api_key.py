"""Legacy authentication information page.

The current wizard deliberately does not collect or write Anthropic API keys.
"""

from PyQt6.QtWidgets import QTextBrowser, QVBoxLayout, QWizardPage


class ApiKeyPage(QWizardPage):
    """Explain that Claude Code authentication is configured separately."""

    def __init__(self):
        super().__init__()
        self.setTitle("Claude Authentication")
        self.setSubTitle("Configure Claude Code authentication separately")

        instructions = QTextBrowser()
        instructions.setOpenExternalLinks(True)
        instructions.setHtml(
            """
            <p>
                This installer configures MCP servers only. It does not collect or
                store Anthropic API keys.
            </p>
            <p>
                Configure Claude Code authentication using your normal Claude Code
                setup before starting the installed servers.
            </p>
            <p>
                <a href="https://docs.anthropic.com/en/docs/claude-code">
                Claude Code documentation
                </a>
            </p>
            """
        )

        layout = QVBoxLayout()
        layout.addWidget(instructions)
        self.setLayout(layout)
