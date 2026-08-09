"""Welcome page for the installer wizard"""
from PyQt6.QtWidgets import (
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWizardPage,
)


class WelcomePage(QWizardPage):
    """Welcome page with project introduction"""

    def __init__(self):
        super().__init__()
        self.setTitle("Welcome to Sanpoloid")
        self.setSubTitle(
            "Choose the body you need today — from Lite sensors to the full stack"
        )

        layout = QVBoxLayout()

        # Project description
        description = QTextBrowser()
        description.setOpenExternalLinks(True)
        description.setMaximumHeight(400)
        description.setHtml(
            """
            <h2>sanpo-loid — AIに身体を与えるプロジェクト</h2>
            <p>
                Embodied Claude は、安価なハードウェア(約4,000円)で Claude に
                「目」「首」「耳」「脳(長期記憶)」を与える MCP サーバー群です。
            </p>

            <h3>コンセプト</h3>
            <blockquote>
                「AIに身体を」と聞くと高価なロボットを想像しがちですが、
                <strong>3,980円のWi-Fiカメラで目と首は十分実現できます</strong>。
                本質(見る・動かす)だけ抽出したシンプルさが特徴です。
            </blockquote>

            <h3>実行プロファイル</h3>
            <ul>
                <li><strong>Lite</strong>: SQLite長期記憶と体温感覚。カメラやVector DBなし。</li>
                <li><strong>Core</strong>: Wi-Fiカメラ、長期記憶、体温感覚。</li>
                <li><strong>Full</strong>: ローカル推論、USBカメラ、ElevenLabsの声を含む全MCP。</li>
                <li><strong>Custom</strong>: 必要な身体moduleだけを手動選択。</li>
            </ul>

            <h3>必要なハードウェア</h3>
            <ul>
                <li>Wi-Fi PTZ カメラ(推奨: TP-Link Tapo C210/C220 - 約3,980円)</li>
                <li>GPU(Whisper 音声認識用、オプション)</li>
            </ul>

            <p>
                <a href="https://github.com/dj-thank/embodied-claude">
                GitHub リポジトリ
                </a>
            </p>
            """
        )
        layout.addWidget(description)

        # Note
        note = QLabel(
            "⚠️ このインストーラは Claude Code の MCP 設定を自動生成します。\n"
            "既存の設定は上書きされませんが、バックアップを推奨します。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("QLabel { color: #94a3b8; margin-top: 10px; }")
        layout.addWidget(note)

        self.setLayout(layout)
