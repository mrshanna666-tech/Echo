from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from src.config import DATA_DIR
from src.preferences import Preferences, load_preferences, save_preferences


logger = logging.getLogger(__name__)


class SettingsPage(QWidget):
    export_requested = Signal()
    clear_today_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("content")

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 34)
        root.setSpacing(18)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("设置")
        title.setObjectName("pageTitle")
        subtitle = QLabel("管理 Echo 的本地记录、导出和隐私说明。")
        subtitle.setObjectName("storyBody")
        subtitle.setWordWrap(True)

        privacy_card = self._card()
        privacy_layout = self._card_layout(privacy_card)
        privacy_label = QLabel("隐私与本地数据")
        privacy_label.setObjectName("sectionLabel")
        privacy_copy = QLabel(
            "Echo 默认只在本地记录应用使用情况，不会自动上传你的数据。"
            "你可以随时查看数据位置、导出日报，或清空指定日期的本地记录。"
        )
        privacy_copy.setObjectName("storyBody")
        privacy_copy.setWordWrap(True)
        privacy_buttons = QHBoxLayout()
        privacy_buttons.setSpacing(10)
        open_data = QPushButton("查看数据位置")
        open_data.setObjectName("secondaryButton")
        clear_today = QPushButton("清空今日记录")
        clear_today.setObjectName("secondaryButton")
        open_data.clicked.connect(self._open_data_location)
        clear_today.clicked.connect(self.clear_today_requested.emit)
        privacy_buttons.addWidget(open_data)
        privacy_buttons.addWidget(clear_today)
        privacy_buttons.addStretch()
        privacy_layout.addWidget(privacy_label)
        privacy_layout.addWidget(privacy_copy)

        preferences = load_preferences()
        exclude_label = QLabel("不记录的应用或窗口关键词（用逗号分隔）")
        exclude_label.setObjectName("storyBody")
        self.exclude_input = QLineEdit(", ".join(preferences.excluded_keywords))
        self.exclude_input.setPlaceholderText("例如：Bitwarden, 无痕, 私人聊天")
        idle_row = QHBoxLayout()
        idle_label = QLabel("无操作多久后停止记录")
        idle_label.setObjectName("storyBody")
        self.idle_minutes = QSpinBox()
        self.idle_minutes.setRange(1, 120)
        self.idle_minutes.setSuffix(" 分钟")
        self.idle_minutes.setValue(preferences.idle_minutes)
        save_privacy = QPushButton("保存隐私设置")
        save_privacy.setObjectName("primaryButton")
        save_privacy.clicked.connect(self._save_privacy_settings)
        idle_row.addWidget(idle_label)
        idle_row.addWidget(self.idle_minutes)
        idle_row.addStretch()
        privacy_layout.addWidget(exclude_label)
        privacy_layout.addWidget(self.exclude_input)
        privacy_layout.addLayout(idle_row)
        privacy_layout.addWidget(save_privacy, alignment=Qt.AlignmentFlag.AlignLeft)
        privacy_layout.addLayout(privacy_buttons)

        export_card = self._card("quietCard")
        export_layout = self._card_layout(export_card)
        export_label = QLabel("数据导出")
        export_label.setObjectName("sectionLabel")
        export_copy = QLabel(
            "导出内容包括本地 Markdown 日报、手动记录和应用使用记录。"
            "导出前 Echo 会提示保存位置，不会自动上传。"
        )
        export_copy.setObjectName("storyBody")
        export_copy.setWordWrap(True)
        export_buttons = QHBoxLayout()
        export_buttons.setSpacing(10)
        export_markdown = QPushButton("导出全部日报")
        export_markdown.setObjectName("primaryButton")
        export_database = QPushButton("打开数据库目录")
        export_database.setObjectName("secondaryButton")
        export_markdown.clicked.connect(self.export_requested.emit)
        export_database.clicked.connect(self._open_data_location)
        export_buttons.addWidget(export_markdown)
        export_buttons.addWidget(export_database)
        export_buttons.addStretch()
        export_layout.addWidget(export_label)
        export_layout.addWidget(export_copy)
        export_layout.addLayout(export_buttons)

        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(privacy_card)
        root.addWidget(export_card)
        root.addStretch()

    def _card(self, object_name: str = "card") -> QFrame:
        card = QFrame()
        card.setObjectName(object_name)
        return card

    def _card_layout(self, card: QFrame) -> QVBoxLayout:
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        return layout

    def _open_data_location(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(DATA_DIR))
        except Exception:
            logger.exception("Failed to open data location.")
            QMessageBox.warning(self, "Echo Recorder", "打开数据位置失败，请查看日志。")

    def _show_clear_notice(self) -> None:
        QMessageBox.information(
            self,
            "Echo Recorder",
            "清空今日记录需要更谨慎的删除确认流程。当前版本先保留入口，不会直接删除你的本地数据。",
        )

    def _show_export_notice(self) -> None:
        QMessageBox.information(
            self,
            "Echo Recorder",
            "导出全部日报会在后续版本接入。当前可以先通过“查看数据位置”访问本地 Markdown 文件。",
        )

    def _save_privacy_settings(self) -> None:
        keywords = tuple(
            item.strip().lower()
            for item in self.exclude_input.text().replace("，", ",").split(",")
            if item.strip()
        )
        try:
            save_preferences(Preferences(keywords, self.idle_minutes.value()))
            QMessageBox.information(self, "Echo Recorder", "隐私与闲置设置已保存。")
        except Exception:
            logger.exception("Failed to save privacy settings.")
            QMessageBox.warning(self, "Echo Recorder", "设置保存失败，请查看日志。")
