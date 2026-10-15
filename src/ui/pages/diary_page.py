from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from src.config import DATA_DIR
from src.i18n import tr
from src.security import protected_path, read_protected_text, write_protected_text
from src.utils.time_utils import today_str


logger = logging.getLogger(__name__)


class DiaryPage(QWidget):
    generate_summary_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("content")
        self._loading = False
        self.selected_date = today_str()

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 34)
        root.setSpacing(18)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        self.date_label = QLabel()
        self.date_label.setObjectName("dateLabel")
        title = QLabel(tr("今天被整理成了什么？", "What did today become?"))
        title.setObjectName("pageTitle")
        title_box.addWidget(self.date_label)
        title_box.addWidget(title)
        self.status_label = QLabel()
        self.status_label.setObjectName("recordingStatus")
        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(self.status_label)

        self.article_card = QFrame()
        self.article_card.setObjectName("card")
        article = QVBoxLayout(self.article_card)
        article.setContentsMargins(30, 28, 30, 28)
        article.setSpacing(16)

        self.article_label = QLabel(tr("今日回顾", "Daily reflection"))
        self.article_label.setObjectName("sectionLabel")
        self.article_title = QLabel()
        self.article_title.setObjectName("storyTitle")
        self.article_title.setWordWrap(True)
        self.article_body = QLabel()
        self.article_body.setObjectName("storyBody")
        self.article_body.setWordWrap(True)
        self.editor = QPlainTextEdit()
        self.editor.setVisible(False)
        self.editor.setMinimumHeight(280)
        self.generate_button = QPushButton(tr("生成今日日报", "Generate today's reflection"))
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.clicked.connect(self._request_generation)
        self.edit_button = QPushButton(tr("编辑日报", "Edit reflection"))
        self.edit_button.setObjectName("secondaryButton")
        self.edit_button.clicked.connect(self._start_editing)
        self.save_button = QPushButton(tr("保存修改", "Save changes"))
        self.save_button.setObjectName("primaryButton")
        self.save_button.setVisible(False)
        self.save_button.clicked.connect(self._save_edit)
        self.week_button = QPushButton(tr("生成本周周报", "Generate weekly reflection"))
        self.week_button.setObjectName("secondaryButton")
        self.week_button.clicked.connect(self._generate_weekly_report)
        article_buttons = QHBoxLayout()
        article_buttons.setSpacing(10)
        article_buttons.addWidget(self.generate_button)
        article_buttons.addWidget(self.edit_button)
        article_buttons.addWidget(self.save_button)
        article_buttons.addWidget(self.week_button)
        article_buttons.addStretch()

        article.addWidget(self.article_label)
        article.addWidget(self.article_title)
        article.addWidget(self.article_body)
        article.addWidget(self.editor)
        article.addLayout(article_buttons)

        lower = QHBoxLayout()
        lower.setSpacing(18)
        self.state_card = self._small_card(tr("状态分析", "State overview"))
        self.moments_card = self._small_card(tr("关键瞬间", "Key moments"))
        self.raw_card = self._small_card(tr("原始记录折叠区", "Local evidence"))
        lower.addWidget(self.state_card, 1)
        lower.addWidget(self.moments_card, 1)
        lower.addWidget(self.raw_card, 1)

        root.addLayout(header)
        root.addWidget(self.article_card)
        root.addLayout(lower)
        root.addStretch()
        self.refresh()

    def refresh(self) -> None:
        self.set_date(self.selected_date)

    def set_date(self, date_text: str) -> None:
        self.selected_date = date_text
        self.date_label.setText(
            tr(f"{date_text} · Echo 日报", f"{date_text} · Echo reflection")
        )
        summary_path = self._summary_path(date_text)
        exists = summary_path.exists()
        self.edit_button.setVisible(exists and not self.editor.isVisible())
        self.status_label.setText(
            tr("日报已生成 · 原始记录已折叠", "Reflection ready · local evidence hidden")
            if exists
            else tr("日报尚未生成", "Reflection not generated")
        )
        self.generate_button.setVisible(not exists or self._loading)
        if not exists:
            self.article_title.setText(
                tr("今天的日报还没有生成", "Today's reflection has not been generated")
                if date_text == today_str()
                else tr("这一天的日报还没有生成", "This day's reflection has not been generated")
            )
            self.article_body.setText(
                tr(
                    "生成时可以选择完全本地总结，或在确认脱敏预览后使用 GPT‑5.6 深度回顾。",
                    "Choose a fully local summary, or use GPT‑5.6 after reviewing the sanitized preview.",
                )
            )
            self.generate_button.setText(
                tr("生成今日日报", "Generate today's reflection")
                if date_text == today_str()
                else tr("生成该日日报", "Generate this day's reflection")
            )
            self._set_card_body(
                self.state_card,
                tr("等待生成后分析今天的专注度、切换节奏和情绪线索。", "Generate a reflection to review focus and rhythm."),
            )
            self._set_card_body(
                self.moments_card,
                tr("等待生成后提取今天值得回看的关键瞬间。", "Generate a reflection to surface moments worth revisiting."),
            )
            self._set_card_body(
                self.raw_card,
                tr("原始记录始终保留在本地，并默认折叠。", "Raw records stay local and hidden by default."),
            )
            return

        text = self._read_summary(summary_path)
        self.article_title.setText(self._extract_title(text))
        self.article_body.setText(self._extract_body(text))
        self._set_card_body(self.state_card, self._build_status_text(text))
        self._set_card_body(self.moments_card, self._build_moments_text(text))
        self._set_card_body(
            self.raw_card,
            tr(
                "窗口记录、心情记录和一句话仍保留在本地；这里只展示整理后的结果。",
                "Window activity, moods, and notes remain local; this page shows only the reflection.",
            ),
        )

    def set_loading(self, loading: bool) -> None:
        self._loading = loading
        self.generate_button.setEnabled(not loading)
        if loading:
            self.generate_button.setText(tr("正在整理今天...", "Reflecting on today..."))
        else:
            self.generate_button.setText(
                tr("生成今日日报", "Generate today's reflection")
                if self.selected_date == today_str()
                else tr("生成该日日报", "Generate this day's reflection")
            )

    def set_result(self, success: bool) -> None:
        self._loading = False
        self.generate_button.setEnabled(True)
        self.generate_button.setText(
            tr("生成今日日报", "Generate today's reflection")
            if self.selected_date == today_str()
            else tr("生成该日日报", "Generate this day's reflection")
        )
        self.refresh()
        if not success:
            self.article_title.setText(tr("日报生成失败", "Reflection failed"))
            self.article_body.setText(
                tr("日报生成失败，请查看日志。", "The reflection failed. Check the log.")
            )

    def _request_generation(self) -> None:
        self.set_loading(True)
        self.generate_summary_requested.emit(self.selected_date)

    def _start_editing(self) -> None:
        path = self._summary_path(self.selected_date)
        if not path.exists():
            return
        self.editor.setPlainText(self._read_summary(path))
        self.editor.setVisible(True)
        self.article_title.setVisible(False)
        self.article_body.setVisible(False)
        self.edit_button.setVisible(False)
        self.save_button.setVisible(True)

    def _save_edit(self) -> None:
        path = self._summary_path(self.selected_date)
        try:
            write_protected_text(path, self.editor.toPlainText().rstrip() + "\n")
            self.editor.setVisible(False)
            self.article_title.setVisible(True)
            self.article_body.setVisible(True)
            self.save_button.setVisible(False)
            self.set_date(self.selected_date)
            QMessageBox.information(
                self, "Echo Recorder", tr("日报修改已保存在本机。", "Changes were saved locally.")
            )
        except Exception:
            logger.exception("Failed to save edited summary: %s", path)
            QMessageBox.warning(
                self, "Echo Recorder", tr("日报保存失败，请查看日志。", "Could not save the reflection. Check the log.")
            )

    def _generate_weekly_report(self) -> None:
        end = datetime.strptime(self.selected_date, "%Y-%m-%d").date()
        start = end - timedelta(days=6)
        sections = [f"# {start} 至 {end} Echo 周报", ""]
        included = 0
        for offset in range(7):
            day = (start + timedelta(days=offset)).isoformat()
            path = self._summary_path(day)
            if not path.exists():
                continue
            included += 1
            text = self._read_summary(path)
            sections.extend([f"## {day}", "", self._extract_body(text), ""])
        if not included:
            QMessageBox.information(
                self, "Echo Recorder", tr("最近七天还没有可汇总的日报。", "There are no reflections to combine from the last seven days.")
            )
            return
        week_dir = DATA_DIR / "weekly"
        week_dir.mkdir(parents=True, exist_ok=True)
        output = week_dir / f"{start}_{end}.md"
        output = write_protected_text(output, "\n".join(sections).rstrip() + "\n")
        QMessageBox.information(
            self,
            "Echo Recorder",
            tr(f"周报已生成：\n{output}", f"Weekly reflection created:\n{output}"),
        )

    def _summary_path(self, date_text: str) -> Path:
        year, month, day = date_text.split("-")
        return protected_path(DATA_DIR / year / month / day / "summary.md")

    def _small_card(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("quietCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        label = QLabel(title)
        label.setObjectName("sectionLabel")
        body = QLabel()
        body.setObjectName("storyBody")
        body.setWordWrap(True)
        frame._echo_body = body
        layout.addWidget(label)
        layout.addWidget(body)
        layout.addStretch()
        return frame

    def _set_card_body(self, card: QFrame, body: str) -> None:
        label = getattr(card, "_echo_body", None)
        if label is not None:
            label.setText(body)

    def _read_summary(self, summary_path) -> str:
        try:
            return read_protected_text(summary_path, encoding="utf-8")
        except UnicodeDecodeError:
            return read_protected_text(summary_path, encoding="utf-8-sig")
        except Exception:
            logger.exception("Failed to read summary: %s", summary_path)
            return ""

    def _extract_title(self, text: str) -> str:
        for line in text.splitlines():
            if line.startswith("# "):
                return line.lstrip("# ").strip()
        return tr("今日回顾", "Daily reflection")

    def _extract_body(self, text: str) -> str:
        lines = [line.strip("#- ") for line in text.splitlines() if line.strip()]
        body = "\n".join(line for line in lines[1:8] if not line.startswith("##"))
        return body or tr(
            "今天的记录已经生成，Echo 会把它作为未来回顾的素材。",
            "Today's record is ready for future reflection.",
        )

    def _build_status_text(self, text: str) -> str:
        if "VS Code" in text or "Code" in text:
            return tr("今天的注意力偏向项目开发。", "Today's attention leaned toward project development.")
        return tr("今天的状态根据日报内容整理。", "Today's state is summarized from the reflection.")

    def _build_moments_text(self, text: str) -> str:
        lines = [line for line in text.splitlines() if line.startswith("- ")]
        if not lines:
            return tr("今天的关键瞬间还不够明确。", "Today's key moments are not clear yet.")
        return "\n".join(lines[:3])
