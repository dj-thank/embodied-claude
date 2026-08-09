"""
Embodied Claude Installer
GUI installer for setting up Embodied Claude MCP servers
"""
import sys

from PyQt6.QtWidgets import QApplication, QWizard

from .pages.camera import CameraSelectionPage
from .pages.complete import CompletePage
from .pages.dependencies import DependenciesPage
from .pages.install import InstallationPage
from .pages.welcome import WelcomePage

_APP_STYLESHEET = """
QWizard { background: #0f172a; color: #e2e8f0; }
QWizardPage { background: #0f172a; }
QLabel { color: #cbd5e1; }
QLabel#qt_wizard_title, QLabel#qt_wizard_subtitle { color: #0f172a; }
QGroupBox {
    color: #e2e8f0;
    font-weight: 600;
    border: 1px solid #334155;
    border-radius: 10px;
    margin-top: 12px;
    padding: 12px 10px 8px 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLineEdit, QComboBox, QListWidget, QTextEdit, QTextBrowser {
    background: #111c2f;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 7px;
    padding: 6px;
    selection-background-color: #0891b2;
}
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox, QLineEdit { min-height: 24px; }
QCheckBox { color: #e2e8f0; spacing: 8px; }
QPushButton {
    background: #0e7490;
    color: white;
    border: 0;
    border-radius: 7px;
    padding: 8px 15px;
    font-weight: 600;
}
QPushButton:hover { background: #0891b2; }
QPushButton:disabled { background: #334155; color: #94a3b8; }
QProgressBar { border: 1px solid #334155; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #06b6d4; border-radius: 5px; }
"""


class EmbodiedClaudeInstaller(QWizard):
    """Main installer wizard"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Embodied Claude Installer")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.HaveHelpButton, False)
        self.setMinimumSize(800, 600)
        self.setStyleSheet(_APP_STYLESHEET)

        # Add pages
        self.addPage(WelcomePage())
        self.addPage(CameraSelectionPage())
        self.addPage(DependenciesPage())
        self.addPage(InstallationPage())
        self.addPage(CompletePage())


def main():
    """Entry point for the installer"""
    app = QApplication(sys.argv)
    app.setApplicationName("Embodied Claude Installer")

    wizard = EmbodiedClaudeInstaller()
    wizard.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
