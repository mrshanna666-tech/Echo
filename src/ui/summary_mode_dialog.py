from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.i18n import tr


class SummaryModeDialog(QDialog):
    LOCAL = "local"
    AI = "ai"
    CANCEL = "cancel"

    def __init__(self, preview: str, ai_available: bool, ai_is_local: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.choice = self.CANCEL
        self.setWindowTitle(tr("生成日报", "Generate daily reflection"))
        self.setMinimumSize(620, 520)

        layout = QVBoxLayout(self)
        title = QLabel(tr("选择整理方式", "Choose how Echo should reflect"))
        title.setObjectName("pageTitle")
        explanation = QLabel(
            tr(
                "本地总结不会发送任何数据。AI 深度回顾只会在你确认后使用下方脱敏内容。" if ai_is_local else "本地总结不会发送任何数据。AI 深度回顾只会在你确认后发送下方脱敏内容。",
                "Local summary sends nothing. AI reflection uses only the sanitized preview below after you confirm." if ai_is_local else "Local summary sends nothing. AI reflection sends only the sanitized preview below after you confirm.",
            )
        )
        explanation.setWordWrap(True)
        preview_box = QPlainTextEdit()
        preview_box.setReadOnly(True)
        preview_box.setPlainText(preview)

        buttons = QDialogButtonBox()
        local_button = QPushButton(tr("使用本地总结", "Use local summary"))
        ai_button = QPushButton(
            tr("使用本地 AI 生成", "Generate with local AI") if ai_is_local else tr("发送脱敏数据并生成", "Send sanitized data and generate")
        )
        cancel_button = QPushButton(tr("取消", "Cancel"))
        ai_button.setEnabled(ai_available)
        if not ai_available:
            ai_button.setToolTip(
                tr(
                    "请先在设置中填写本地模型名。" if ai_is_local else "请先在设置中安全保存 OpenAI API Key。",
                    "Enter a local model name in Settings first." if ai_is_local else "Save an OpenAI API key securely in Settings first.",
                )
            )
        buttons.addButton(local_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(ai_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        local_button.clicked.connect(lambda: self._finish(self.LOCAL))
        ai_button.clicked.connect(lambda: self._finish(self.AI))
        cancel_button.clicked.connect(self.reject)

        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addWidget(preview_box, 1)
        layout.addWidget(buttons)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def reject(self) -> None:
        self.choice = self.CANCEL
        super().reject()

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()
