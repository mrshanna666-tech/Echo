from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGraphicsOpacityEffect,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from src.i18n import tr


class NoteDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("留下一句话", "Leave a note"))
        self.setMinimumWidth(460)
        self.setObjectName("noteDialog")
        self._has_faded_in = False

        self.editor = QTextEdit()
        self.editor.setPlaceholderText(tr("今天最值得记住的是……", "What is most worth remembering today?"))
        self.editor.setMinimumHeight(130)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setObjectName("primaryButton")
        ok_button.setText(tr("保存", "Save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消", "Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.setSpacing(14)
        title = QLabel(tr("留下一句话", "Leave a note"))
        title.setObjectName("dialogTitle")
        subtitle = QLabel(tr("写一句未来的你会想看到的话。", "Write something your future self will want to see."))
        subtitle.setObjectName("dialogSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.editor)
        layout.addWidget(buttons)
        self.setStyleSheet(
            """
            QDialog#noteDialog {
                background: #fffaf3;
                color: #2c2721;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QLabel#dialogTitle {
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#dialogSubtitle {
                color: #716555;
                font-size: 14px;
            }
            QTextEdit {
                background: #fbf4e8;
                border: 1px solid #ddd0bd;
                border-radius: 12px;
                padding: 12px;
                font-size: 14px;
            }
            QPushButton {
                border: none;
                border-radius: 9px;
                padding: 8px 16px;
                font-weight: 700;
                background: #f8ddb1;
                color: #c17640;
            }
            QPushButton#primaryButton {
                background: #517556;
                color: white;
            }
            """
        )

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if not self._has_faded_in:
            self._has_faded_in = True
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
            self._fade_animation = QPropertyAnimation(effect, b"opacity", self)
            self._fade_animation.setDuration(220)
            self._fade_animation.setStartValue(0)
            self._fade_animation.setEndValue(1)
            self._fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._fade_animation.start()

    def content(self) -> str:
        return self.editor.toPlainText().strip()
