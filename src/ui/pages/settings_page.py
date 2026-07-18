from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from src.config import DATA_DIR
from src.i18n import tr
from src.openai_key_store import load_openai_api_key, save_openai_api_key
from src.preferences import Preferences, load_preferences, save_preferences


logger = logging.getLogger(__name__)


class SettingsPage(QWidget):
    export_requested = Signal()
    clear_today_requested = Signal()
    settings_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("content")

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 34)
        root.setSpacing(18)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        preferences = load_preferences()
        self._initial_language = preferences.language

        title = QLabel(tr("设置", "Settings"))
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            tr(
                "管理 Echo 的本地记录、语言、AI 和隐私说明。",
                "Manage Echo's local records, language, AI, and privacy controls.",
            )
        )
        subtitle.setObjectName("storyBody")
        subtitle.setWordWrap(True)

        privacy_card = self._card()
        privacy_layout = self._card_layout(privacy_card)
        privacy_label = QLabel(tr("隐私与本地数据", "Privacy and local data"))
        privacy_label.setObjectName("sectionLabel")
        privacy_copy = QLabel(
            tr(
                "Echo 默认只在本地记录应用使用情况，不会自动上传你的数据。"
                "你可以随时查看数据位置、导出日报，或清空指定日期的本地记录。",
                "Echo records application activity locally by default and never uploads it automatically. "
                "You can inspect, export, or delete your local records at any time.",
            )
        )
        privacy_copy.setObjectName("storyBody")
        privacy_copy.setWordWrap(True)
        privacy_buttons = QHBoxLayout()
        privacy_buttons.setSpacing(10)
        open_data = QPushButton(tr("查看数据位置", "Open data folder"))
        open_data.setObjectName("secondaryButton")
        clear_today = QPushButton(tr("清空今日记录", "Clear today's records"))
        clear_today.setObjectName("secondaryButton")
        open_data.clicked.connect(self._open_data_location)
        clear_today.clicked.connect(self.clear_today_requested.emit)
        privacy_buttons.addWidget(open_data)
        privacy_buttons.addWidget(clear_today)
        privacy_buttons.addStretch()
        privacy_layout.addWidget(privacy_label)
        privacy_layout.addWidget(privacy_copy)

        exclude_label = QLabel(
            tr(
                "不记录的应用或窗口关键词（用逗号分隔）",
                "Apps or window keywords to exclude (comma-separated)",
            )
        )
        exclude_label.setObjectName("storyBody")
        self.exclude_input = QLineEdit(", ".join(preferences.excluded_keywords))
        self.exclude_input.setPlaceholderText(
            tr(
                "例如：Bitwarden, 无痕, 私人聊天",
                "Example: Bitwarden, private browsing, personal chat",
            )
        )
        idle_row = QHBoxLayout()
        idle_label = QLabel(tr("无操作多久后停止记录", "Stop recording after inactivity"))
        idle_label.setObjectName("storyBody")
        self.idle_minutes = QSpinBox()
        self.idle_minutes.setRange(1, 120)
        self.idle_minutes.setSuffix(tr(" 分钟", " min"))
        self.idle_minutes.setValue(preferences.idle_minutes)
        save_privacy = QPushButton(tr("保存隐私设置", "Save privacy settings"))
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

        experience_card = self._card("quietCard")
        experience_layout = self._card_layout(experience_card)
        experience_label = QLabel(tr("语言", "Language"))
        experience_label.setObjectName("sectionLabel")
        experience_copy = QLabel(
            tr(
                "切换后 Echo 会立即重新打开主窗口；本地记录不会受到影响。",
                "Echo will reopen the main window immediately. Local records are not affected.",
            )
        )
        experience_copy.setObjectName("storyBody")
        self.language_combo = QComboBox()
        self.language_combo.addItem("简体中文", "zh-CN")
        self.language_combo.addItem("English", "en")
        language_index = self.language_combo.findData(preferences.language)
        self.language_combo.setCurrentIndex(max(language_index, 0))
        experience_layout.addWidget(experience_label)
        experience_layout.addWidget(experience_copy)
        experience_layout.addWidget(self.language_combo, alignment=Qt.AlignmentFlag.AlignLeft)

        ai_card = self._card()
        ai_layout = self._card_layout(ai_card)
        ai_label = QLabel(tr("GPT‑5.6 深度回顾", "GPT‑5.6 reflection"))
        ai_label.setObjectName("sectionLabel")
        ai_copy = QLabel(
            tr(
                "AI 默认关闭。启用后，每次生成日报仍会先显示脱敏预览，只有你确认后才发送。"
                "窗口标题、路径、邮箱、网址和照片不会发送。",
                "AI is off by default. Each daily reflection shows a sanitized preview and sends data only after your confirmation. "
                "Window titles, paths, email addresses, URLs, and photos are excluded.",
            )
        )
        ai_copy.setObjectName("storyBody")
        ai_copy.setWordWrap(True)
        self.ai_enabled = QCheckBox(
            tr("启用可选 AI 深度回顾", "Enable optional AI reflection")
        )
        self.ai_enabled.setChecked(preferences.ai_enabled)
        self.ai_include_notes = QCheckBox(
            tr(
                "允许在每次确认后发送脱敏的手动笔记",
                "Allow sanitized manual notes after confirmation",
            )
        )
        self.ai_include_notes.setChecked(preferences.ai_include_notes)
        api_key_label = QLabel(
            tr(
                "OpenAI API Key（保存在 Windows 凭据管理器中）",
                "OpenAI API key (stored in Windows Credential Manager)",
            )
        )
        api_key_label.setObjectName("storyBody")
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText(
            tr(
                "已安全保存；留空表示不更改" if load_openai_api_key() else "输入 API Key",
                "Saved securely; leave blank to keep it" if load_openai_api_key() else "Enter API key",
            )
        )
        save_ai = QPushButton(tr("保存语言与 AI 设置", "Save language and AI settings"))
        save_ai.setObjectName("primaryButton")
        save_ai.clicked.connect(self._save_experience_settings)
        ai_layout.addWidget(ai_label)
        ai_layout.addWidget(ai_copy)
        ai_layout.addWidget(self.ai_enabled)
        ai_layout.addWidget(self.ai_include_notes)
        ai_layout.addWidget(api_key_label)
        ai_layout.addWidget(self.api_key_input)
        ai_layout.addWidget(save_ai, alignment=Qt.AlignmentFlag.AlignLeft)

        export_card = self._card("quietCard")
        export_layout = self._card_layout(export_card)
        export_label = QLabel(tr("数据导出", "Data export"))
        export_label.setObjectName("sectionLabel")
        export_copy = QLabel(
            tr(
                "导出内容包括本地 Markdown 日报、手动记录和应用使用记录。"
                "导出前 Echo 会提示保存位置，不会自动上传。",
                "Exports include local Markdown reflections, notes, and application activity. "
                "Echo asks where to save the archive and never uploads it automatically.",
            )
        )
        export_copy.setObjectName("storyBody")
        export_copy.setWordWrap(True)
        export_buttons = QHBoxLayout()
        export_buttons.setSpacing(10)
        export_markdown = QPushButton(tr("导出全部日报", "Export all data"))
        export_markdown.setObjectName("primaryButton")
        export_database = QPushButton(tr("打开数据库目录", "Open database folder"))
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
        root.addWidget(experience_card)
        root.addWidget(ai_card)
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
            QMessageBox.warning(
                self,
                "Echo Recorder",
                tr("打开数据位置失败，请查看日志。", "Could not open the data folder. Check the log."),
            )

    def _show_clear_notice(self) -> None:
        QMessageBox.information(
            self,
            "Echo Recorder",
            tr(
                "清空今日记录需要更谨慎的删除确认流程。当前版本先保留入口，不会直接删除你的本地数据。",
                "Clearing today's records requires confirmation. Echo will not delete local data without it.",
            ),
        )

    def _show_export_notice(self) -> None:
        QMessageBox.information(
            self,
            "Echo Recorder",
            tr(
                "导出全部日报会在后续版本接入。当前可以先通过“查看数据位置”访问本地 Markdown 文件。",
                "Use Open data folder to access the local Markdown files.",
            ),
        )

    def _save_privacy_settings(self) -> None:
        keywords = tuple(
            item.strip().lower()
            for item in self.exclude_input.text().replace("，", ",").split(",")
            if item.strip()
        )
        try:
            current = load_preferences()
            save_preferences(
                Preferences(
                    excluded_keywords=keywords,
                    idle_minutes=self.idle_minutes.value(),
                    language=current.language,
                    ai_enabled=current.ai_enabled,
                    ai_include_notes=current.ai_include_notes,
                )
            )
            QMessageBox.information(
                self,
                "Echo Recorder",
                tr("隐私与闲置设置已保存。", "Privacy and idle settings saved."),
            )
        except Exception:
            logger.exception("Failed to save privacy settings.")
            QMessageBox.warning(
                self,
                "Echo Recorder",
                tr("设置保存失败，请查看日志。", "Could not save settings. Check the log."),
            )

    def _save_experience_settings(self) -> None:
        try:
            current = load_preferences()
            language = str(self.language_combo.currentData())
            api_key = self.api_key_input.text().strip()
            if api_key:
                save_openai_api_key(api_key)
                self.api_key_input.clear()
            save_preferences(
                Preferences(
                    excluded_keywords=current.excluded_keywords,
                    idle_minutes=current.idle_minutes,
                    language=language,
                    ai_enabled=self.ai_enabled.isChecked(),
                    ai_include_notes=self.ai_include_notes.isChecked(),
                )
            )
            language_changed = language != self._initial_language
            self._initial_language = language
            QMessageBox.information(
                self,
                "Echo Recorder",
                tr("语言与 AI 设置已保存。", "Language and AI settings saved.", language),
            )
            self.settings_changed.emit(language_changed)
        except Exception:
            logger.exception("Failed to save language and AI settings.")
            QMessageBox.warning(
                self,
                "Echo Recorder",
                tr(
                    "语言或 API Key 保存失败，请查看日志。",
                    "Could not save the language or API key. Check the log.",
                ),
            )
