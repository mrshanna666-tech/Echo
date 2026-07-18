from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict
from datetime import date

import shiboken6
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.config import DATA_DIR
from src.database.db import Database
from src.database.models import AppUsage, ManualNote
from src.i18n import tr
from src.mood.local_mood_journal import MoodEntry, get_mood_entries_by_date
from src.summary.local_summary_generator import get_today_summary_path
from src.ui.mood_drawer import MoodDrawer
from src.ui.pages.diary_page import DiaryPage
from src.ui.pages.memory_page import MemoryPage
from src.ui.pages.notes_page import NotesPage
from src.ui.pages.settings_page import SettingsPage
from src.ui.pages.timeline_page import TimelinePage
from src.ui.sidebar import Sidebar, reduced_motion_enabled
from src.ui.smooth_scroll_area import SmoothScrollArea
from src.utils.time_utils import display_time, human_duration, today_str
from src.utils.resources import echo_icon_path


logger = logging.getLogger(__name__)


class TimelineRow(QFrame):
    clicked = Signal(str, object)

    def __init__(self, kind: str, payload: AppUsage | ManualNote | MoodEntry) -> None:
        super().__init__()
        self.kind = kind
        self.payload = payload
        self.setObjectName("timelineRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.kind, self.payload)
        super().mousePressEvent(event)


class DrawerOverlay(QFrame):
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("drawerOverlay")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TodayReviewDialog(QDialog):
    def __init__(self, app_usage: list[AppUsage], notes: list[ManualNote], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reviewDialog")
        self.setWindowTitle(tr("回顾今天", "Review today"))
        self.setModal(True)
        self.resize(520, 420)
        self._cards = self._build_cards(app_usage, notes)
        self._index = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(16)
        self.eyebrow = QLabel()
        self.eyebrow.setObjectName("sectionLabel")
        self.title = QLabel()
        self.title.setObjectName("reviewTitle")
        self.title.setWordWrap(True)
        self.body = QLabel()
        self.body.setObjectName("storyBody")
        self.body.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.prev_button = QPushButton(tr("上一张", "Previous"))
        self.prev_button.setObjectName("secondaryButton")
        self.next_button = QPushButton(tr("下一张", "Next"))
        self.next_button.setObjectName("primaryButton")
        close_button = QPushButton(tr("关闭", "Close"))
        close_button.setObjectName("secondaryButton")
        self.prev_button.clicked.connect(self._previous)
        self.next_button.clicked.connect(self._next)
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.prev_button)
        buttons.addWidget(self.next_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        layout.addWidget(self.eyebrow)
        layout.addWidget(self.title)
        layout.addWidget(self.body, 1)
        layout.addLayout(buttons)
        self._apply_styles()
        self._render()

    def _build_cards(self, app_usage: list[AppUsage], notes: list[ManualNote]) -> list[tuple[str, str]]:
        total = sum(max(usage.duration_seconds or 0, 0) for usage in app_usage)
        software_count = len({usage.app_name for usage in app_usage if usage.app_name})
        top_app = self._top_app(app_usage) or tr("暂无", "None")
        latest_note = notes[-1].content if notes else tr("今天还没有留下主动记录。", "No manual note was left today.")
        story = (
            tr("今天还在积累记录。", "Today is still accumulating records.")
            if not app_usage and not notes
            else tr("今天的记录已经开始形成一条可以回看的主线。", "Today's records are beginning to form a story you can revisit.")
        )
        return [
            (
                tr("今日记录概览", "Today's overview"),
                tr(
                    f"今日记录 {human_duration(total)}，涉及 {software_count} 个软件，留下 {len(notes)} 条手动记录。",
                    f"Recorded {human_duration(total)} across {software_count} apps, with {len(notes)} manual notes.",
                ),
            ),
            (
                tr("最长使用的应用", "Most-used app"),
                tr(
                    f"今天最明显的线索是 {top_app}。这不一定代表结论，但它说明今天的注意力主要停留在哪里。",
                    f"The clearest clue today is {top_app}. It is not a conclusion, but it shows where your attention spent the most time.",
                ),
            ),
            (
                tr("今天值得记住", "Worth remembering"),
                tr(
                    f"一句话：{latest_note}\n\n今日主线：{story}",
                    f"Note: {latest_note}\n\nToday's thread: {story}",
                ),
            ),
        ]

    def _top_app(self, app_usage: list[AppUsage]) -> str | None:
        usage_by_app: dict[str, int] = defaultdict(int)
        for usage in app_usage:
            usage_by_app[usage.app_name or "Unknown"] += max(usage.duration_seconds or 0, 0)
        if not usage_by_app:
            return None
        return max(usage_by_app.items(), key=lambda item: item[1])[0]

    def _previous(self) -> None:
        self._index = max(self._index - 1, 0)
        self._render()

    def _next(self) -> None:
        self._index = min(self._index + 1, len(self._cards) - 1)
        self._render()

    def _render(self) -> None:
        title, body = self._cards[self._index]
        self.eyebrow.setText(
            tr(
                f"回顾今天 · {self._index + 1} / {len(self._cards)}",
                f"Review today · {self._index + 1} / {len(self._cards)}",
            )
        )
        self.title.setText(title)
        self.body.setText(body)
        self.prev_button.setEnabled(self._index > 0)
        self.next_button.setEnabled(self._index < len(self._cards) - 1)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QDialog#reviewDialog {
                background: #fffaf3;
                color: #2c2721;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QLabel#sectionLabel {
                color: #517556;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#reviewTitle {
                font-size: 26px;
                font-weight: 800;
            }
            QLabel#storyBody {
                color: #716555;
                font-size: 15px;
                line-height: 150%;
            }
            QPushButton {
                border: none;
                border-radius: 10px;
                padding: 9px 16px;
                font-weight: 700;
            }
            QPushButton#primaryButton {
                background: #517556;
                color: white;
            }
            QPushButton#primaryButton:disabled {
                background: #d6e4cf;
                color: #517556;
            }
            QPushButton#secondaryButton {
                background: #f8ddb1;
                color: #c17640;
            }
            QPushButton#secondaryButton:disabled {
                color: #bfa98a;
            }
            """
        )


class SummaryDetailDialog(QDialog):
    def __init__(self, summary_path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.summary_path = summary_path
        self.setObjectName("summaryDialog")
        self.setWindowTitle(tr("Echo 日报", "Echo reflection"))
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        date_label = QLabel(today_str())
        date_label.setObjectName("sectionLabel")
        title = QLabel(tr("Echo 日报", "Echo reflection"))
        title.setObjectName("reviewTitle")
        title_box.addWidget(date_label)
        title_box.addWidget(title)
        markdown_tag = QLabel(tr("本地 Markdown", "Local Markdown"))
        markdown_tag.setObjectName("categoryTag")
        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(markdown_tag)

        self.editor = QTextEdit()
        self.editor.setObjectName("summaryViewer")
        self.editor.setReadOnly(True)
        try:
            self.editor.setPlainText(summary_path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            self.editor.setPlainText(summary_path.read_text(encoding="utf-8-sig"))

        buttons = QHBoxLayout()
        open_file_button = QPushButton(tr("用默认编辑器打开", "Open in default editor"))
        open_file_button.setObjectName("primaryButton")
        close_button = QPushButton(tr("关闭", "Close"))
        close_button.setObjectName("secondaryButton")
        open_file_button.clicked.connect(self._open_with_default_app)
        close_button.clicked.connect(self.accept)
        buttons.addWidget(open_file_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        layout.addLayout(header)
        layout.addWidget(self.editor, 1)
        layout.addLayout(buttons)
        self._apply_styles()

    def _open_with_default_app(self) -> None:
        try:
            os.startfile(str(self.summary_path))
        except Exception:
            logger.exception("Failed to open summary with default app.")
            QMessageBox.warning(self, "Echo Recorder", tr("打开默认编辑器失败，请查看日志。", "Could not open the default editor. Check the log."))

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QDialog#summaryDialog {
                background: #f7f3ec;
                color: #2c2721;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QLabel#sectionLabel {
                color: #517556;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#reviewTitle {
                font-size: 28px;
                font-weight: 800;
            }
            QLabel#categoryTag {
                background: #d6e4cf;
                color: #517556;
                border-radius: 11px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#photoPreview {
                background: #f8f2e6;
                color: #716555;
                border: 1px solid rgba(193, 118, 64, 45);
                border-radius: 14px;
                padding: 10px;
                font-weight: 700;
            }
            QTextEdit#summaryViewer {
                background: #fffaf3;
                color: #2c2721;
                border: none;
                border-radius: 14px;
                padding: 18px;
                font-size: 14px;
                line-height: 150%;
            }
            QPushButton {
                border: none;
                border-radius: 10px;
                padding: 9px 16px;
                font-weight: 700;
            }
            QPushButton#primaryButton {
                background: #517556;
                color: white;
            }
            QPushButton#secondaryButton {
                background: #f8ddb1;
                color: #c17640;
            }
            """
        )


class HoverCard(QFrame):
    def __init__(self, object_name: str = "card") -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setMouseTracking(True)
        self._shadow = None
        self._shadow_animation = None
        if sys.platform != "win32":
            self._shadow = QGraphicsDropShadowEffect(self)
            self._shadow.setBlurRadius(24)
            self._shadow.setOffset(0, 10)
            self._shadow.setColor(QColor(64, 48, 28, 24))
            self.setGraphicsEffect(self._shadow)
            self._shadow_animation = QPropertyAnimation(self._shadow, b"blurRadius", self)
            self._shadow_animation.setDuration(160)
            self._shadow_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._shadow is not None and not reduced_motion_enabled():
            self._animate_shadow(30, 14, QColor(64, 48, 28, 38))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._shadow is not None and not reduced_motion_enabled():
            self._animate_shadow(24, 10, QColor(64, 48, 28, 24))
        super().leaveEvent(event)

    def _animate_shadow(self, blur_radius: int, offset_y: int, color: QColor) -> None:
        if self._shadow is None or self._shadow_animation is None:
            return
        self._shadow_animation.stop()
        self._shadow_animation.setStartValue(self._shadow.blurRadius())
        self._shadow_animation.setEndValue(blur_radius)
        self._shadow.setOffset(0, offset_y)
        self._shadow.setColor(color)
        self._shadow_animation.start()


class TodayWindow(QWidget):
    generate_summary_requested = Signal()
    generate_summary_for_date_requested = Signal(str)
    open_summary_requested = Signal()
    add_note_requested = Signal()
    export_requested = Signal()
    clear_today_requested = Signal()
    language_change_requested = Signal()

    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self._has_faded_in = False
        self._summary_loading = False
        self._summary_loading_step = 0
        self._timeline_generation = 0
        self._displayed_date = today_str()
        self._page_titles = {
            "today": tr("今天", "Today"),
            "timeline": tr("时间线", "Timeline"),
            "diary": tr("日报", "Reflection"),
            "notes": tr("一句话", "Notes"),
            "memory": "Memory",
            "settings": tr("设置", "Settings"),
        }

        self.setWindowTitle(tr("Echo - 今天", "Echo - Today"))
        self.setWindowIcon(QIcon(str(echo_icon_path())))
        # Keep a complete opaque backing store while Windows runs its native
        # move/resize loop; otherwise child-only painting can expose blanks.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        window_palette = self.palette()
        window_palette.setColor(QPalette.ColorRole.Window, QColor("#f7f3ec"))
        self.setPalette(window_palette)
        self.resize(1120, 760)
        self.setMinimumSize(980, 660)

        self._summary_loading_timer = QTimer(self)
        self._summary_loading_timer.setInterval(260)
        self._summary_loading_timer.timeout.connect(self._tick_summary_loading)

        self._date_rollover_timer = QTimer(self)
        self._date_rollover_timer.setInterval(30_000)
        self._date_rollover_timer.timeout.connect(self._check_date_rollover)
        self._date_rollover_timer.start()

        self._build_ui()
        self._apply_styles()
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if not self._has_faded_in:
            self._has_faded_in = True
            self._run_entry_animation()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if hasattr(self, "detail_panel"):
            self._position_drawer_overlay()
            self._position_detail_panel(visible=self.detail_panel.isVisible(), animated=False)
        if hasattr(self, "mood_drawer"):
            self._position_mood_overlay()
            self._position_mood_drawer(visible=self.mood_drawer.isVisible(), animated=False)

    def refresh(self) -> None:
        try:
            current_date = today_str()
            self._displayed_date = current_date
            app_usage = self.database.get_app_usage_by_date(current_date)
            notes = self.database.get_manual_notes_by_date(current_date)
            moods = get_mood_entries_by_date(current_date)
            self._render(app_usage, notes, moods)
            if hasattr(self, "notes_page"):
                self.notes_page.refresh()
            if hasattr(self, "diary_page"):
                self.diary_page.refresh()
            if hasattr(self, "memory_page"):
                self.memory_page.refresh()
        except Exception:
            logger.exception("Failed to refresh today window.")
            self.today_status_body.setText(
                tr(
                    "今天的记录暂时无法显示，但 Echo 会继续尝试记录。",
                    "Today's records cannot be displayed right now, but Echo will keep recording.",
                )
            )

    def _check_date_rollover(self) -> None:
        current_date = today_str()
        if current_date == self._displayed_date:
            return
        logger.info("Date rollover detected in UI: %s", current_date)
        self.refresh()
        if self.stack.currentIndex() == self._page_indexes.get("diary"):
            self.diary_page.set_date(current_date)

    def set_summary_loading(self, loading: bool) -> None:
        self._summary_loading = loading
        if hasattr(self, "diary_page"):
            self.diary_page.set_loading(loading)

    def set_summary_result(self, success: bool) -> None:
        self._summary_loading = False
        self._summary_loading_timer.stop()
        self.summary_status.setText(
            tr("今天日报已生成", "Today's reflection is ready")
            if success
            else tr("尚未生成", "Not generated")
        )
        if hasattr(self, "diary_page"):
            self.diary_page.set_result(success)

    def _switch_page(self, key: str) -> None:
        try:
            if key not in self._page_indexes:
                return
            self.sidebar.set_active(key, emit=False)
            self.stack.setCurrentIndex(self._page_indexes[key])
            self.setWindowTitle(
                f"Echo - {self._page_titles.get(key, tr('今天', 'Today'))}"
            )
            if key == "notes":
                self.notes_page.refresh()
            if key == "timeline":
                self.timeline_page.refresh()
            if key == "diary":
                self.diary_page.set_date(today_str())
            if key == "memory":
                self.memory_page.refresh()
            self._fade_page(self.stack.currentWidget())
            if sys.platform == "win32":
                self._commit_page_surface(self.stack.currentWidget())
        except Exception:
            logger.exception("Failed to switch page: %s", key)

    def _commit_page_surface(self, widget: QWidget) -> None:
        """Commit a complete backing-store frame after a page switch on Windows."""
        if not self._is_qobject_alive(widget):
            return
        widget.setGraphicsEffect(None)
        widget.setAutoFillBackground(True)
        page_palette = widget.palette()
        page_palette.setColor(QPalette.ColorRole.Window, QColor("#f7f3ec"))
        widget.setPalette(page_palette)
        widget.updateGeometry()
        widget.repaint()
        self.stack.repaint()
        self.repaint()
        QTimer.singleShot(0, self._repaint_switched_page)

    def _repaint_switched_page(self) -> None:
        widget = self.stack.currentWidget()
        if self._is_qobject_alive(widget):
            widget.repaint()
            self.stack.repaint()
            self.repaint()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.page_selected.connect(self._switch_page)
        self.sidebar.mood_requested.connect(self._show_mood_drawer)
        root.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("stack")
        root.addWidget(self.stack, 1)

        self.scroll = SmoothScrollArea()
        self.scroll.setObjectName("scroll")
        self.content = QWidget()
        self.content.setObjectName("content")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(34, 28, 34, 34)
        self.content_layout.setSpacing(22)
        self.scroll.setWidget(self.content)
        self.stack.addWidget(self.scroll)

        self.timeline_page = TimelinePage(self.database)
        self.diary_page = DiaryPage()
        self.diary_page.generate_summary_requested.connect(self._request_summary_generation_for_date)
        self.notes_page = NotesPage(self.database)
        self.memory_page = MemoryPage(self.database)
        self.memory_page.report_requested.connect(self._open_diary_for_date)
        self.settings_page = SettingsPage()
        self.settings_page.export_requested.connect(self.export_requested.emit)
        self.settings_page.clear_today_requested.connect(self.clear_today_requested.emit)
        self.settings_page.settings_changed.connect(self._settings_changed)
        self.timeline_scroll = self._wrap_page(self.timeline_page)
        self.diary_scroll = self._wrap_page(self.diary_page)
        self.notes_scroll = self._wrap_page(self.notes_page)
        self.memory_scroll = self._wrap_page(self.memory_page)
        self.settings_scroll = self._wrap_page(self.settings_page)
        self._page_indexes = {
            "today": self.stack.indexOf(self.scroll),
            "timeline": self.stack.addWidget(self.timeline_scroll),
            "diary": self.stack.addWidget(self.diary_scroll),
            "notes": self.stack.addWidget(self.notes_scroll),
            "memory": self.stack.addWidget(self.memory_scroll),
            "settings": self.stack.addWidget(self.settings_scroll),
        }

        self.header_widget = QWidget()
        header = QHBoxLayout(self.header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header_text = QVBoxLayout()
        header_text.setSpacing(4)
        self.date_label = QLabel()
        self.date_label.setObjectName("dateLabel")
        title = QLabel(tr("今天发生了什么？", "What happened today?"))
        title.setObjectName("pageTitle")
        header_text.addWidget(self.date_label)
        header_text.addWidget(title)
        header.addLayout(header_text)
        header.addStretch()
        self.recording_status = QLabel()
        self.recording_status.setObjectName("recordingStatus")
        header.addWidget(self.recording_status)
        self.summary_status = QLabel()
        self.summary_status.setObjectName("statusPill")
        header.addWidget(self.summary_status)
        self.content_layout.addWidget(self.header_widget)

        main = QHBoxLayout()
        main.setSpacing(22)
        self.timeline_card = self._card(hover=False)
        self.timeline_card.setObjectName("timelineCard")
        timeline_layout = self._card_layout(self.timeline_card, 20)
        timeline_label = QLabel(tr("今日时间线", "Today's timeline"))
        timeline_label.setObjectName("sectionLabel")
        self.timeline_overview = QFrame()
        self.timeline_overview.setObjectName("timelineOverview")
        overview_layout = QHBoxLayout(self.timeline_overview)
        overview_layout.setContentsMargins(16, 14, 16, 14)
        overview_layout.setSpacing(16)
        self.overview_window = self._overview_item(tr("记录窗口", "Recorded window"))
        self.overview_count = self._overview_item(tr("记录条数", "Entries"))
        self.overview_main_app = self._overview_item(tr("主要应用", "Top app"))
        self.overview_status = self._overview_item(tr("今日状态", "Today's state"))
        for item in [
            self.overview_window,
            self.overview_count,
            self.overview_main_app,
            self.overview_status,
        ]:
            overview_layout.addWidget(item, 1)

        timeline_hint = QLabel(
            tr(
                "提示：今天页只保存原始记录，意义留给日报慢慢整理。",
                "Today keeps the raw evidence local; Reflection helps make sense of it.",
            )
        )
        timeline_hint.setObjectName("timelineHint")
        timeline_hint.setWordWrap(True)
        self.timeline_box = QVBoxLayout()
        self.timeline_box.setSpacing(10)
        timeline_layout.addWidget(timeline_label)
        timeline_layout.addWidget(self.timeline_overview)
        timeline_layout.addWidget(timeline_hint)
        timeline_layout.addLayout(self.timeline_box)
        main.addWidget(self.timeline_card, 5)

        side = QVBoxLayout()
        side.setSpacing(18)
        self.memory_card = self._card()
        memory_layout = self._card_layout(self.memory_card, 22)
        memory_label = QLabel(tr("今日一句话", "Today's note"))
        memory_label.setObjectName("orangeLabel")
        self.memory_quote = QLabel()
        self.memory_quote.setObjectName("memoryQuote")
        self.memory_quote.setWordWrap(True)
        self.memory_reason = QLabel()
        self.memory_reason.setObjectName("memoryReason")
        self.memory_reason.setWordWrap(True)
        self.add_note_button = QPushButton(tr("添加一句话", "Add a note"))
        self.add_note_button.setObjectName("smallButton")
        self.add_note_button.clicked.connect(self.add_note_requested.emit)
        memory_layout.addWidget(memory_label)
        memory_layout.addWidget(self.memory_quote)
        memory_layout.addWidget(self.memory_reason)
        memory_layout.addWidget(self.add_note_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.status_card = self._card()
        status_layout = self._card_layout(self.status_card, 22)
        status_label = QLabel(tr("今日状态", "Today's state"))
        status_label.setObjectName("sectionLabel")
        self.today_status_body = QLabel()
        self.today_status_body.setObjectName("storyBody")
        self.today_status_body.setWordWrap(True)
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.today_status_body)

        side.addWidget(self.memory_card)
        side.addWidget(self.status_card)
        side.addStretch()
        main.addLayout(side, 2)
        self.content_layout.addLayout(main)

        self._build_detail_panel()
        self._build_mood_drawer()

        self._entry_widgets = [
            self.header_widget,
            self.timeline_card,
            self.memory_card,
            self.status_card,
        ]

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #f7f3ec;
                color: #2c2721;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 14px;
            }
            QFrame#sidebar {
                background: #ece4d6;
            }
            QStackedWidget#stack, QScrollArea#scroll, QWidget#content {
                background: #f7f3ec;
            }
            QScrollArea#scroll, QScrollArea#pageScroll {
                border: none;
            }
            QScrollArea#scroll QScrollBar:vertical,
            QScrollArea#pageScroll QScrollBar:vertical {
                background: rgba(236, 228, 214, 95);
                width: 8px;
                margin: 8px 4px 8px 0;
                border-radius: 4px;
            }
            QScrollArea#scroll QScrollBar::handle:vertical,
            QScrollArea#pageScroll QScrollBar::handle:vertical {
                background: rgba(81, 117, 86, 105);
                min-height: 42px;
                border-radius: 4px;
            }
            QScrollArea#scroll QScrollBar::handle:vertical:hover,
            QScrollArea#pageScroll QScrollBar::handle:vertical:hover {
                background: rgba(81, 117, 86, 155);
            }
            QScrollArea#scroll QScrollBar::add-line:vertical,
            QScrollArea#scroll QScrollBar::sub-line:vertical,
            QScrollArea#pageScroll QScrollBar::add-line:vertical,
            QScrollArea#pageScroll QScrollBar::sub-line:vertical {
                height: 0;
                border: none;
                background: transparent;
            }
            QScrollArea#scroll QScrollBar::add-page:vertical,
            QScrollArea#scroll QScrollBar::sub-page:vertical,
            QScrollArea#pageScroll QScrollBar::add-page:vertical,
            QScrollArea#pageScroll QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QFrame#scrollTopShadow {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(247, 243, 236, 230),
                    stop: 1 rgba(247, 243, 236, 0)
                );
            }
            QFrame#scrollBottomShadow {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(247, 243, 236, 0),
                    stop: 1 rgba(247, 243, 236, 230)
                );
            }
            QFrame#drawerOverlay {
                background: transparent;
            }
            QLabel#brand {
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#pageTitle {
                font-size: 28px;
                font-weight: 700;
            }
            QLabel#dateLabel, QLabel#sectionLabel {
                color: #517556;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#orangeLabel, QLabel#orangeSmall {
                color: #c17640;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#mutedSmall {
                color: #877b6b;
                font-size: 11px;
            }
            QLabel#localStatus {
                color: #517556;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#localDot {
                color: #517556;
                font-size: 10px;
                font-weight: 900;
            }
            QLabel#localDot[pulse="true"] {
                color: #7fae78;
            }
            QLabel#recordingStatus {
                background: rgba(255, 250, 243, 185);
                color: #716555;
                border-radius: 14px;
                padding: 7px 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#statusPill {
                background: #d6e4cf;
                color: #517556;
                border-radius: 14px;
                padding: 7px 13px;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#storyTitle {
                font-size: 26px;
                font-weight: 800;
                line-height: 130%;
            }
            QLabel#storyBody, QLabel#memoryReason, QLabel#evidenceLine {
                color: #716555;
                line-height: 150%;
            }
            QLabel#timelineHint {
                background: rgba(248, 242, 230, 165);
                color: #877b6b;
                border-radius: 10px;
                padding: 8px 11px;
                font-size: 12px;
            }
            QLabel#overviewValue {
                color: #2c2721;
                font-size: 15px;
                font-weight: 800;
            }
            QLabel#memoryQuote {
                background: #f8ddb1;
                border-radius: 12px;
                padding: 16px;
                font-size: 17px;
                font-weight: 700;
                line-height: 145%;
            }
            QLabel#reportTitle {
                font-size: 22px;
                font-weight: 800;
            }
            QLabel#detailTitle {
                font-size: 22px;
                font-weight: 800;
            }
            QLabel#categoryTag {
                background: #d6e4cf;
                color: #517556;
                border-radius: 11px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#hourGroup {
                color: #517556;
                font-size: 12px;
                font-weight: 800;
                padding-top: 8px;
            }
            QFrame#timelineRow {
                border-radius: 10px;
                padding: 4px;
            }
            QFrame#timelineRow:hover {
                background: rgba(248, 242, 230, 145);
            }
            QFrame#timelineOverview {
                background: #f8f2e6;
                border-radius: 13px;
            }
            QFrame#overviewItem {
                background: transparent;
            }
            QFrame#timelineLane {
                background: transparent;
            }
            QFrame#timelineVerticalLine {
                background: rgba(81, 117, 86, 38);
                border-radius: 1px;
            }
            QLabel#timelineDot {
                color: #517556;
                font-size: 16px;
                font-weight: 900;
                background: transparent;
            }
            HoverCard#card, QFrame#card, HoverCard#quietCard, QFrame#timelineCard {
                background: #fffaf3;
                border-radius: 14px;
            }
            HoverCard#quietCard, QFrame#quietCard {
                background: #f8f2e6;
                border-radius: 14px;
            }
            QFrame#timelineCard {
                background: #fffaf3;
            }
            QFrame#detailPanel {
                background: #f7f3ec;
                border-radius: 0;
                border: none;
            }
            QPushButton {
                border: none;
                border-radius: 10px;
                padding: 9px 16px;
                font-weight: 700;
            }
            QPushButton#primaryButton {
                background: #517556;
                color: white;
            }
            QPushButton#primaryButton:hover {
                background: #46664b;
            }
            QPushButton#primaryButton:pressed {
                background: #35573d;
            }
            QPushButton#primaryButton:disabled {
                background: #d6e4cf;
                color: #517556;
            }
            QPushButton#secondaryButton {
                background: #f8ddb1;
                color: #c17640;
            }
            QPushButton#secondaryButton:hover {
                background: #f3d19b;
            }
            QPushButton#secondaryButton:pressed {
                background: #e8c184;
            }
            QPushButton#smallButton {
                background: #f8f2e6;
                color: #517556;
                border-radius: 9px;
                padding: 6px 11px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton#smallButton:hover {
                background: #d6e4cf;
            }
            QPushButton#drawerCloseButton {
                background: #f8f2e6;
                color: #716555;
                border-radius: 14px;
                padding: 5px 10px;
                font-weight: 800;
            }
            QPushButton#drawerCloseButton:hover {
                background: #f8ddb1;
                color: #c17640;
            }
            QPushButton#navButton {
                background: #fbf8f1;
                color: #726858;
                border-radius: 10px;
                padding: 10px 14px;
                text-align: left;
                font-weight: 700;
            }
            QPushButton#navButton:hover {
                background: #f6efe3;
            }
            QPushButton#navButton:pressed {
                background: #eee6d9;
            }
            QPushButton#navButton[active="true"] {
                background: #517556;
                color: white;
            }
            QPushButton#moodButton {
                background: rgba(255, 250, 243, 185);
                color: #517556;
                border-radius: 10px;
                padding: 9px 13px;
                text-align: left;
                font-weight: 800;
            }
            QPushButton#moodButton:hover {
                background: #fbf8f1;
            }
            QPushButton#moodButton:pressed {
                background: #f3d19b;
            }
            QFrame#navItem {
                border-radius: 10px;
                padding: 0;
            }
            QLabel#navText {
                color: #726858;
                font-weight: 600;
            }
            QFrame#navActive {
                background: #517556;
                border-radius: 10px;
            }
            QLabel#navActiveText {
                color: white;
                font-weight: 700;
            }
            QCalendarWidget#memoryCalendar {
                background: #fffaf3;
                color: #2c2721;
                border: none;
            }
            QCalendarWidget#memoryCalendar QWidget {
                background: #fffaf3;
                color: #2c2721;
            }
            QCalendarWidget#memoryCalendar QToolButton {
                background: #f8f2e6;
                color: #517556;
                border: none;
                border-radius: 8px;
                padding: 5px;
                font-weight: 700;
            }
            QWidget#memoryPage { background: #f7f3ec; }
            QLabel#memorySubtitle { color: #877b6b; font-size: 13px; }
            QLabel#memoryPrivacy { background: #e4eddf; color: #517556; border-radius: 15px; padding: 8px 13px; font-size: 11px; font-weight: 700; }
            QFrame#replayPicker, QFrame#memoryReplayPanel { background: #fffaf3; border: 1px solid #e3d5c0; border-radius: 14px; }
            QDateEdit#memoryDateEdit, QTimeEdit#memoryTimeEdit { background: #f8f4ec; color: #2c2721; border: 1px solid #ded2c1; border-radius: 10px; padding: 8px 12px; min-width: 94px; selection-background-color: #d6e4cf; selection-color: #2c2721; }
            QDateEdit#memoryDateEdit::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 28px; border: none; border-left: 1px solid #e6dac9; background: transparent; }
            QDateEdit#memoryDateEdit::drop-down:hover { background: #eee8dc; }
            QPushButton#memoryReplayButton {
                background: #2f5538;
                color: #fffaf3;
                border: 1px solid #2f5538;
                border-radius: 12px;
                padding: 9px 18px;
                min-width: 118px;
                font-size: 13px;
                font-weight: 800;
            }
            QPushButton#memoryReplayButton:hover {
                background: #3f6848;
                border-color: #3f6848;
            }
            QPushButton#memoryReplayButton:pressed {
                background: #25462e;
                padding-top: 10px;
                padding-bottom: 8px;
            }
            QFrame#memoryFragment { background: #fffaf3; border: 1px solid #e3d5c0; border-radius: 13px; }
            QFrame#memoryFragment:hover { background: #fdf6eb; border-color: #cdbb9f; }
            QFrame#memoryFragment[active="true"] { background: #fdf7ef; border: 2px solid #9caf94; }
            QLabel#fragmentMeta { color: #517556; font-size: 11px; }
            QLabel#fragmentTitle { color: #2c2721; font-size: 17px; font-weight: 800; }
            QLabel#fragmentTrail { color: #877b6b; font-size: 11px; }
            QScrollArea#memoryFragmentScroll, QScrollArea#memoryFragmentScroll QWidget#qt_scrollarea_viewport { background: transparent; border: none; }
            QPushButton#memoryLinkButton { background: transparent; color: #716555; padding: 3px 0; font-size: 11px; }
            QFrame#memoryStoryCard { background: #e4eddf; border-radius: 13px; }
            QLabel#memoryStoryTitle { color: #35573d; font-size: 19px; font-weight: 800; }
            QLabel#memoryTrailTag { background: #f8f4ec; color: #517556; border: 1px solid #ded2c1; border-radius: 12px; padding: 7px 10px; font-size: 11px; }
            QFrame#memoryNoteCard { background: #f8f4ec; border-radius: 12px; }
            QPushButton#memoryOutlineButton { background: #f8f4ec; color: #514a41; border: 1px solid #ded2c1; }
            QPushButton#memoryOutlineButton:hover { background: #eee6d9; }
            QPushButton#primaryButton[saved="true"] { background: #35573d; }
            """
        )

    def _render(
        self,
        app_usage: list[AppUsage],
        notes: list[ManualNote],
        moods: list[MoodEntry],
    ) -> None:
        self.date_label.setText(f"{today_str()} · {self._day_count_text()}")
        summary_exists = get_today_summary_path().exists()
        self.summary_status.setText(
            tr("今天日报已生成", "Today's reflection is ready")
            if summary_exists
            else tr("尚未生成", "Not generated")
        )
        self.recording_status.setText(self._recording_status_text(app_usage, notes, moods))

        latest_note = notes[-1].content if notes else tr("今天还没有留下主动记录。", "No note has been left today.")
        self.memory_quote.setText(f"“{latest_note}”" if notes else latest_note)
        self.memory_reason.setText(self._memory_reason(notes))
        self.today_status_body.setText(self._today_status_text(app_usage, notes, moods))
        self._render_timeline_overview(app_usage, notes, moods)
        self._current_app_usage = app_usage
        self._current_notes = notes
        self._current_moods = moods

        self._render_timeline(app_usage, notes, moods)

    def _render_timeline_overview(
        self,
        app_usage: list[AppUsage],
        notes: list[ManualNote],
        moods: list[MoodEntry],
    ) -> None:
        entries_count = len(app_usage) + len(notes) + len(moods)
        self._set_overview_value(self.overview_window, self._record_window_text(app_usage, notes, moods))
        self._set_overview_value(
            self.overview_count,
            tr(f"{entries_count} 条", f"{entries_count} entries"),
        )
        self._set_overview_value(
            self.overview_main_app,
            self._top_app(app_usage) or tr("暂无", "None"),
        )
        if not entries_count:
            status = tr("等待记录", "Waiting")
        elif moods:
            status = tr("有心情记录", "Mood captured")
        elif notes:
            status = tr("有一句话", "Note added")
        else:
            status = tr("记录中", "Recording")
        self._set_overview_value(self.overview_status, status)

    def _set_overview_value(self, frame: QFrame, value: str) -> None:
        label = getattr(frame, "_echo_value", None)
        if label is not None:
            label.setText(value)

    def _record_window_text(
        self,
        app_usage: list[AppUsage],
        notes: list[ManualNote],
        moods: list[MoodEntry],
    ) -> str:
        values: list[str] = []
        for usage in app_usage:
            values.append(usage.start_time)
            if usage.end_time:
                values.append(usage.end_time)
        for note in notes:
            values.append(note.created_at)
        for mood in moods:
            values.append(mood.created_at)
        if not values:
            return tr("暂无", "None")
        values.sort()
        return f"{display_time(values[0])} - {display_time(values[-1])}"

    def _render_outcomes(self, app_usage: list[AppUsage], notes: list[ManualNote]) -> None:
        self._clear_layout(self.outcome_box)
        outcomes = self._outcomes(app_usage, notes)
        for outcome in outcomes:
            row = QHBoxLayout()
            row.setSpacing(10)
            dot = QLabel("•")
            dot.setObjectName("sectionLabel")
            label = QLabel(outcome)
            label.setWordWrap(True)
            row.addWidget(dot)
            row.addWidget(label, 1)
            self.outcome_box.addLayout(row)

    def _render_timeline(
        self,
        app_usage: list[AppUsage],
        notes: list[ManualNote],
        moods: list[MoodEntry],
    ) -> None:
        self._timeline_generation += 1
        generation = self._timeline_generation
        self._clear_layout(self.timeline_box)
        entries = []
        for usage in app_usage:
            entries.append(("app", usage.start_time, usage))
        for note in notes:
            entries.append(("note", note.created_at, note))
        for mood in moods:
            entries.append(("mood", mood.created_at, mood))
        entries.sort(key=lambda item: item[1])
        if not entries:
            empty = QLabel(tr("今天还没有记录。Echo 会在后台安静地记录这一天。", "No records yet. Echo will quietly record this day in the background."))
            empty.setObjectName("storyBody")
            empty.setWordWrap(True)
            self.timeline_box.addWidget(empty)
            return
        last_hour = None
        animated_index = 0
        for kind, _, payload in entries[-8:]:
            hour = self._entry_hour(payload)
            if hour and hour != last_hour:
                hour_label = QLabel(hour)
                hour_label.setObjectName("hourGroup")
                self.timeline_box.addWidget(hour_label)
                last_hour = hour
            row = self._timeline_row(kind, payload)
            if sys.platform != "win32" and not reduced_motion_enabled():
                row.setGraphicsEffect(QGraphicsOpacityEffect(row))
                row.graphicsEffect().setOpacity(0)
            self.timeline_box.addWidget(row)
            if sys.platform != "win32" and not reduced_motion_enabled():
                QTimer.singleShot(
                    animated_index * 60,
                    lambda widget=row, row_generation=generation: self._fade_timeline_widget(
                        widget,
                        180,
                        row_generation,
                    ),
                )
            animated_index += 1

    def _timeline_row(self, kind: str, payload: AppUsage | ManualNote | MoodEntry) -> QWidget:
        row = TimelineRow(kind, payload)
        row.clicked.connect(self._show_timeline_detail)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)
        if kind == "app":
            usage = payload
            time_text = f"{display_time(usage.start_time)} - {display_time(usage.end_time)}"
            title = usage.app_name
            detail = usage.window_title or tr("窗口活动", "Window activity")
            category = self._category_for_usage(usage)
        elif kind == "note":
            note = payload
            time_text = display_time(note.created_at)
            title = tr("一句话", "Note")
            detail = note.content
            category = tr("记录", "Note")
        else:
            mood = payload
            time_text = display_time(mood.created_at)
            title = tr(f"心情记录 · {mood.mood}", f"Mood · {mood.mood}")
            detail = mood.note or tr("此刻没有留下备注。", "No note was left for this moment.")
            category = tr("照片", "Photo") if mood.image_path else ""
        time = QLabel(time_text)
        time.setObjectName("mutedSmall")
        time.setFixedWidth(104)
        lane = QFrame()
        lane.setObjectName("timelineLane")
        lane.setFixedWidth(18)
        lane_layout = QVBoxLayout(lane)
        lane_layout.setContentsMargins(8, 0, 8, 0)
        lane_layout.setSpacing(0)
        line_top = QFrame()
        line_top.setObjectName("timelineVerticalLine")
        line_top.setFixedWidth(2)
        line_bottom = QFrame()
        line_bottom.setObjectName("timelineVerticalLine")
        line_bottom.setFixedWidth(2)
        dot = QLabel("•")
        dot.setObjectName("timelineDot")
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lane_layout.addWidget(line_top, 1, alignment=Qt.AlignmentFlag.AlignHCenter)
        lane_layout.addWidget(dot, alignment=Qt.AlignmentFlag.AlignHCenter)
        lane_layout.addWidget(line_bottom, 1, alignment=Qt.AlignmentFlag.AlignHCenter)
        row._echo_dot = dot
        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 700;")
        detail_label = QLabel(detail)
        detail_label.setObjectName("mutedSmall")
        detail_label.setWordWrap(True)
        text_box.addWidget(title_label)
        text_box.addWidget(detail_label)
        tag = QLabel(category)
        tag.setObjectName("categoryTag")
        layout.addWidget(time)
        layout.addWidget(lane)
        layout.addLayout(text_box, 1)
        if category:
            layout.addWidget(tag)
        return row

    def _request_summary_generation(self) -> None:
        self.set_summary_loading(True)
        self.generate_summary_requested.emit()

    def _request_summary_generation_for_date(self, date_text: str) -> None:
        self.set_summary_loading(True)
        self.generate_summary_for_date_requested.emit(date_text)

    def _open_diary_for_date(self, date_text: str) -> None:
        try:
            self.diary_page.set_date(date_text)
            self.sidebar.set_active("diary", emit=False)
            self.stack.setCurrentIndex(self._page_indexes["diary"])
            self.setWindowTitle(tr("Echo - 日报", "Echo - Reflection"))
            self._fade_page(self.stack.currentWidget())
        except Exception:
            logger.exception("Failed to open diary for date: %s", date_text)

    def _settings_changed(self, language_changed: bool) -> None:
        if language_changed:
            self.language_change_requested.emit()

    def _build_detail_panel(self) -> None:
        self.drawer_overlay = DrawerOverlay(self)
        self.drawer_overlay.clicked.connect(self._hide_detail_panel)
        self.drawer_overlay.hide()

        self.detail_panel = QFrame(self)
        self.detail_panel.setObjectName("detailPanel")
        self.detail_panel.setFixedWidth(340)

        layout = QVBoxLayout(self.detail_panel)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title_label = QLabel(tr("时间线详情", "Timeline details"))
        title_label.setObjectName("sectionLabel")
        close_button = QPushButton("×")
        close_button.setObjectName("drawerCloseButton")
        close_button.setFixedSize(32, 28)
        close_button.clicked.connect(self._hide_detail_panel)
        header.addWidget(title_label)
        header.addStretch()
        header.addWidget(close_button)

        self.detail_title = QLabel(tr("选择一条记录", "Select a record"))
        self.detail_title.setObjectName("detailTitle")
        self.detail_title.setWordWrap(True)
        self.detail_body = QLabel(
            tr(
                "点击时间线中的记录后，这里会显示应用名称、时间、持续时长、类型标签和备注。",
                "Select a timeline record to see its app, time, duration, category, and note.",
            )
        )
        self.detail_body.setObjectName("storyBody")
        self.detail_body.setWordWrap(True)
        self.detail_tag = QLabel(tr("等待选择", "Waiting"))
        self.detail_tag.setObjectName("categoryTag")
        note_label = QLabel(tr("备注", "Note"))
        note_label.setObjectName("sectionLabel")
        self.detail_note = QLabel(tr("暂无额外备注。", "No additional note."))
        self.detail_note.setObjectName("storyBody")
        self.detail_note.setWordWrap(True)
        self.detail_photo_label = QLabel(tr("照片状态", "Photo status"))
        self.detail_photo_label.setObjectName("sectionLabel")
        self.detail_photo = QLabel(tr("暂无照片", "No photo"))
        self.detail_photo.setObjectName("photoPreview")
        self.detail_photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_photo.setFixedHeight(150)
        path_label = QLabel(tr("本地路径", "Local path"))
        path_label.setObjectName("sectionLabel")
        self.detail_path = QLabel(tr("无", "None"))
        self.detail_path.setObjectName("mutedSmall")
        self.detail_path.setWordWrap(True)
        detail_buttons = QHBoxLayout()
        detail_buttons.setSpacing(10)
        self.view_photo_button = QPushButton(tr("查看大图", "View photo"))
        self.view_photo_button.setObjectName("primaryButton")
        self.view_photo_button.clicked.connect(self._open_detail_photo)
        self.open_photo_folder_button = QPushButton(tr("打开所在文件夹", "Open folder"))
        self.open_photo_folder_button.setObjectName("secondaryButton")
        self.open_photo_folder_button.clicked.connect(self._open_detail_photo_folder)
        detail_buttons.addWidget(self.view_photo_button)
        detail_buttons.addWidget(self.open_photo_folder_button)

        layout.addLayout(header)
        layout.addWidget(self.detail_title)
        layout.addWidget(self.detail_tag, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.detail_body)
        layout.addSpacing(8)
        layout.addWidget(note_label)
        layout.addWidget(self.detail_note)
        layout.addWidget(self.detail_photo_label)
        layout.addWidget(self.detail_photo)
        layout.addWidget(path_label)
        layout.addWidget(self.detail_path)
        layout.addLayout(detail_buttons)
        layout.addStretch()
        self.detail_panel.hide()
        self._position_drawer_overlay()
        self._position_detail_panel(visible=False, animated=False)

    def _build_mood_drawer(self) -> None:
        self.mood_overlay = DrawerOverlay(self)
        self.mood_overlay.clicked.connect(self._hide_mood_drawer)
        self.mood_overlay.hide()

        self.mood_drawer = MoodDrawer(self)
        self.mood_drawer.closed.connect(self._hide_mood_drawer)
        self.mood_drawer.saved.connect(self._handle_mood_saved)
        self.mood_drawer.hide()
        self._position_mood_overlay()
        self._position_mood_drawer(visible=False, animated=False)

    def _position_drawer_overlay(self) -> None:
        if not hasattr(self, "drawer_overlay"):
            return
        self.drawer_overlay.setGeometry(0, 0, self.width(), self.height())

    def _position_mood_overlay(self) -> None:
        if not hasattr(self, "mood_overlay"):
            return
        self.mood_overlay.setGeometry(0, 0, self.width(), self.height())

    def _position_detail_panel(self, visible: bool, animated: bool) -> None:
        width = self.detail_panel.width()
        height = self.height()
        y = 0
        shown_x = self.width() - width
        hidden_x = self.width() + 8
        self.detail_panel.setFixedHeight(height)
        target = QPoint(shown_x if visible else hidden_x, y)
        self._set_main_scroll_enabled(not visible)
        previous_animation = getattr(self.detail_panel, "_echo_slide_animation", None)
        if previous_animation is not None:
            # Stop at the live presentation value so a reversal never jumps.
            previous_animation.stop()
        if animated and not reduced_motion_enabled():
            if visible:
                self.drawer_overlay.show()
                self.drawer_overlay.raise_()
            self.detail_panel.show()
            self.detail_panel.raise_()
            animation = QPropertyAnimation(self.detail_panel, b"pos", self.detail_panel)
            animation.setDuration(220)
            animation.setStartValue(self.detail_panel.pos())
            animation.setEndValue(target)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            if not visible:
                animation.finished.connect(self._finish_hide_detail_panel)
            self.detail_panel._echo_slide_animation = animation
            animation.start()
            return
        self.detail_panel.move(target)
        self.detail_panel.setVisible(visible)
        if visible:
            self.drawer_overlay.show()
            self.drawer_overlay.raise_()
            self.detail_panel.raise_()
        else:
            self.drawer_overlay.hide()

    def _finish_hide_detail_panel(self) -> None:
        self.detail_panel.hide()
        self.drawer_overlay.hide()

    def _position_mood_drawer(self, visible: bool, animated: bool) -> None:
        width = self.mood_drawer.width()
        height = self.height()
        y = 0
        shown_x = self.width() - width
        hidden_x = self.width() + 8
        self.mood_drawer.setFixedHeight(height)
        target = QPoint(shown_x if visible else hidden_x, y)
        self._set_main_scroll_enabled(not visible)
        previous_animation = getattr(self.mood_drawer, "_echo_slide_animation", None)
        if previous_animation is not None:
            # Stop at the live presentation value so a reversal never jumps.
            previous_animation.stop()
        if animated and not reduced_motion_enabled():
            if visible:
                self.mood_overlay.show()
                self.mood_overlay.raise_()
            self.mood_drawer.show()
            self.mood_drawer.raise_()
            animation = QPropertyAnimation(self.mood_drawer, b"pos", self.mood_drawer)
            animation.setDuration(220)
            animation.setStartValue(self.mood_drawer.pos())
            animation.setEndValue(target)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            if visible:
                animation.finished.connect(self._finish_show_mood_drawer)
            else:
                animation.finished.connect(self._finish_hide_mood_drawer)
            self.mood_drawer._echo_slide_animation = animation
            animation.start()
            return
        self.mood_drawer.move(target)
        self.mood_drawer.setVisible(visible)
        if visible:
            self.mood_overlay.show()
            self.mood_overlay.raise_()
            self.mood_drawer.raise_()
        else:
            self.mood_drawer.stop_camera()
            self.mood_overlay.hide()

    def _finish_hide_mood_drawer(self) -> None:
        self.mood_drawer.stop_camera()
        self.mood_drawer.hide()
        self.mood_overlay.hide()

    def _finish_show_mood_drawer(self) -> None:
        self.mood_overlay.show()
        self.mood_overlay.raise_()
        self.mood_drawer.show()
        self.mood_drawer.raise_()

    def _set_main_scroll_enabled(self, enabled: bool) -> None:
        policy = Qt.ScrollBarPolicy.ScrollBarAsNeeded if enabled else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        self.scroll.setVerticalScrollBarPolicy(policy)

    def _show_review_dialog(self) -> None:
        try:
            dialog = TodayReviewDialog(
                getattr(self, "_current_app_usage", []),
                getattr(self, "_current_notes", []),
                self,
            )
            dialog.exec()
        except Exception:
            logger.exception("Failed to show today review dialog.")

    def show_summary_detail(self, summary_path) -> None:
        try:
            dialog = SummaryDetailDialog(summary_path, self)
            dialog.exec()
        except Exception:
            logger.exception("Failed to show summary detail dialog.")
            QMessageBox.warning(self, "Echo Recorder", tr("打开今日日报失败，请查看日志。", "Could not open today's reflection. See the log for details."))

    def _open_data_location(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(DATA_DIR))
        except Exception:
            logger.exception("Failed to open data location.")
            QMessageBox.warning(self, "Echo Recorder", tr("打开数据位置失败，请查看日志。", "Could not open the data folder. See the log for details."))

    def _show_clear_today_notice(self) -> None:
        QMessageBox.information(
            self,
            "Echo Recorder",
            tr(
                "清空今日记录需要更谨慎的删除逻辑，第一版先保留入口，不会直接删除你的本地数据。",
                "Deleting today's records needs a safer confirmation flow. This version keeps the entry point but will not delete your local data.",
            ),
        )

    def _show_timeline_detail(self, kind: str, payload: AppUsage | ManualNote | MoodEntry) -> None:
        try:
            if hasattr(self, "mood_drawer") and self.mood_drawer.isVisible():
                self._position_mood_drawer(visible=False, animated=False)
            self._detail_photo_path = None
            if kind == "app":
                usage = payload
                category = self._category_for_usage(usage)
                self.detail_title.setText(usage.app_name or "Unknown")
                self.detail_body.setText(
                    tr(
                        "开始时间  {start}\n结束时间  {end}\n持续时长  {duration}",
                        "Started  {start}\nEnded  {end}\nDuration  {duration}",
                    ).format(
                        start=display_time(usage.start_time),
                        end=display_time(usage.end_time),
                        duration=human_duration(max(usage.duration_seconds or 0, 0)),
                    )
                )
                self.detail_tag.setText(category)
                self.detail_note.setText(usage.window_title or tr("窗口活动", "Window activity"))
                self._set_detail_photo_state("none", "")
            elif kind == "mood":
                mood = payload
                self.detail_title.setText(tr("心情记录", "Mood"))
                self.detail_body.setText(tr(f"时间  {display_time(mood.created_at)}", f"Time  {display_time(mood.created_at)}"))
                self.detail_tag.setText(mood.mood or tr("平静", "Calm"))
                self.detail_note.setText(mood.note or tr("此刻没有留下备注。", "No note was left for this moment."))
                self._set_detail_photo_state("photo" if mood.image_path else "none", mood.image_path)
            else:
                note = payload
                self.detail_title.setText(tr("手动记录", "Manual note"))
                self.detail_body.setText(
                    tr(
                        f"记录时间  {display_time(note.created_at)}\n持续时长  不适用",
                        f"Recorded  {display_time(note.created_at)}\nDuration  Not applicable",
                    )
                )
                self.detail_tag.setText(tr("记录", "Note"))
                self.detail_note.setText(note.content)
                self._set_detail_photo_state("none", "")
            self._position_detail_panel(visible=True, animated=True)
        except Exception:
            logger.exception("Failed to show timeline detail.")

    def _hide_detail_panel(self) -> None:
        self._position_detail_panel(visible=False, animated=True)

    def _set_detail_photo_state(self, state: str, image_path: str) -> None:
        self._detail_photo_path = image_path or None
        self.detail_path.setText(image_path or tr("无", "None"))
        self.view_photo_button.setEnabled(False)
        self.open_photo_folder_button.setEnabled(False)
        if not image_path:
            self.detail_photo.setPixmap(QPixmap())
            self.detail_photo.setText(tr("暂无照片", "No photo"))
            return
        if image_path.startswith("encrypted:") or image_path.lower().endswith(".enc"):
            self.detail_photo.setPixmap(QPixmap())
            self.detail_photo.setText(tr("数据已加密，请先解锁", "The data is encrypted. Unlock it first."))
            return
        if not os.path.exists(image_path):
            self.detail_photo.setPixmap(QPixmap())
            self.detail_photo.setText(tr("暂无照片", "No photo"))
            return
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.detail_photo.setText(tr("暂无照片", "No photo"))
            return
        self.detail_photo.setText("")
        self.detail_photo.setPixmap(
            pixmap.scaled(
                self.detail_photo.width(),
                self.detail_photo.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.view_photo_button.setEnabled(True)
        self.open_photo_folder_button.setEnabled(True)

    def _open_detail_photo(self) -> None:
        path = getattr(self, "_detail_photo_path", None)
        if not path:
            return
        try:
            os.startfile(path)
        except Exception:
            logger.exception("Failed to open mood photo: %s", path)
            QMessageBox.warning(self, "Echo Recorder", tr("打开照片失败，请查看日志。", "Could not open the photo. See the log for details."))

    def _open_detail_photo_folder(self) -> None:
        path = getattr(self, "_detail_photo_path", None)
        if not path:
            return
        try:
            os.startfile(os.path.dirname(path))
        except Exception:
            logger.exception("Failed to open mood photo folder: %s", path)
            QMessageBox.warning(self, "Echo Recorder", tr("打开所在文件夹失败，请查看日志。", "Could not open the folder. See the log for details."))

    def _show_mood_drawer(self) -> None:
        try:
            if hasattr(self, "detail_panel") and self.detail_panel.isVisible():
                self._position_detail_panel(visible=False, animated=False)
            self.mood_drawer.reset_for_open()
            self._position_mood_drawer(visible=True, animated=True)
        except Exception:
            logger.exception("Failed to show mood drawer.")
            QMessageBox.warning(self, "Echo Recorder", tr("打开记录此刻失败，请查看日志。", "Could not open Capture this moment. See the log for details."))

    def _hide_mood_drawer(self) -> None:
        try:
            self.mood_drawer.stop_camera()
            self._position_mood_drawer(visible=False, animated=True)
        except Exception:
            logger.exception("Failed to hide mood drawer.")

    def _handle_mood_saved(self, _image_path: str) -> None:
        logger.info("Mood moment recorded.")
        self.refresh()

    def _tick_summary_loading(self) -> None:
        if not self._summary_loading:
            self._summary_loading_timer.stop()
            return
        self._summary_loading_step = (self._summary_loading_step + 1) % 4

    def _run_entry_animation(self) -> None:
        if reduced_motion_enabled() or sys.platform == "win32":
            return
        self._fade_in()
        for index, widget in enumerate(getattr(self, "_entry_widgets", [])):
            delay = 40 + index * 65
            QTimer.singleShot(delay, lambda target=widget: self._slide_widget_once(target, 8, 260))

    def _slide_widget_once(self, widget: QWidget, distance: int, duration: int) -> None:
        if not self._is_qobject_alive(widget):
            return
        final_pos = widget.pos()
        widget.move(final_pos.x(), final_pos.y() + distance)
        animation = QPropertyAnimation(widget, b"pos", widget)
        animation.setDuration(duration)
        animation.setStartValue(widget.pos())
        animation.setEndValue(final_pos)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        widget._echo_slide_animation = animation
        animation.start()

    def _fade_in(self) -> None:
        if sys.platform == "win32":
            self.content.setGraphicsEffect(None)
            self.content.update()
            return
        effect = QGraphicsOpacityEffect(self.content)
        self.content.setGraphicsEffect(effect)
        self._fade_animation = QPropertyAnimation(effect, b"opacity", self)
        self._fade_animation.setDuration(250)
        self._fade_animation.setStartValue(0)
        self._fade_animation.setEndValue(1)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_animation.finished.connect(lambda: self._clear_graphics_effect(self.content, effect))
        self._fade_animation.start()

    def _fade_page(self, widget: QWidget) -> None:
        if not self._is_qobject_alive(widget):
            return
        if sys.platform == "win32":
            widget.setGraphicsEffect(None)
            widget.update()
            return
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", widget)
        animation.setDuration(180)
        animation.setStartValue(0)
        animation.setEndValue(1)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        widget._echo_page_fade_animation = animation
        animation.finished.connect(lambda: self._clear_graphics_effect(widget, effect))
        animation.start()

    def _fade_timeline_widget(self, widget: QWidget, duration: int, generation: int) -> None:
        if generation != self._timeline_generation:
            return
        if not self._is_qobject_alive(widget):
            return
        self._highlight_timeline_dot(widget)
        self._slide_widget_once(widget, 6, duration)
        self._fade_widget(widget, duration)

    def _highlight_timeline_dot(self, widget: QWidget) -> None:
        dot = getattr(widget, "_echo_dot", None)
        if not self._is_qobject_alive(dot):
            return
        dot.setStyleSheet("color: #c17640; font-weight: 900;")
        QTimer.singleShot(320, lambda target=dot: self._clear_timeline_dot_highlight(target))

    def _clear_timeline_dot_highlight(self, dot: QLabel) -> None:
        if self._is_qobject_alive(dot):
            dot.setStyleSheet("")

    def _fade_widget(self, widget: QWidget, duration: int) -> None:
        if not self._is_qobject_alive(widget):
            return
        if sys.platform == "win32":
            widget.setGraphicsEffect(None)
            widget.update()
            return
        effect = widget.graphicsEffect()
        if effect is None:
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", widget)
        animation.setDuration(duration)
        animation.setStartValue(0)
        animation.setEndValue(1)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        widget._echo_fade_animation = animation
        animation.start()

    def _reset_summary_button_text(self) -> None:
        if hasattr(self, "diary_page"):
            self.diary_page.set_loading(False)

    def _is_qobject_alive(self, obj) -> bool:
        try:
            return obj is not None and shiboken6.isValid(obj)
        except RuntimeError:
            return False

    def _clear_graphics_effect(self, widget: QWidget, effect: QGraphicsOpacityEffect) -> None:
        if not self._is_qobject_alive(widget) or not self._is_qobject_alive(effect):
            return
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    def _card(self, hover: bool = True) -> QFrame:
        frame = HoverCard("card") if hover else QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return frame

    def _wrap_page(self, page: QWidget) -> SmoothScrollArea:
        scroll = SmoothScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidget(page)
        return scroll

    def _card_layout(self, frame: QFrame, padding: int) -> QVBoxLayout:
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(padding, padding, padding, padding)
        layout.setSpacing(14)
        return layout

    def _overview_item(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("overviewItem")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("mutedSmall")
        value_label = QLabel("—")
        value_label.setObjectName("overviewValue")
        value_label.setWordWrap(True)
        frame._echo_value = value_label
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return frame

    def _nav_item(self, text: str, active: bool) -> QFrame:
        frame = QFrame()
        frame.setObjectName("navActive" if active else "navItem")
        frame.setFixedHeight(40)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(9)
        dot = QLabel("•")
        dot.setObjectName("navActiveText" if active else "navText")
        label = QLabel(text)
        label.setObjectName("navActiveText" if active else "navText")
        layout.addWidget(dot)
        layout.addWidget(label)
        layout.addStretch()
        return frame

    def _story_title(self, app_usage: list[AppUsage], notes: list[ManualNote]) -> str:
        if notes:
            return tr("你把今天的一句话留给了未来的自己。", "You left a note for your future self.")
        if app_usage:
            return tr("Echo 正在把今天慢慢整理成可以回看的记忆。", "Echo is turning today into a memory you can revisit.")
        return tr("今天还没有展开，Echo 正在安静等待。", "Today has not unfolded yet. Echo is waiting quietly.")

    def _story_body(self, app_usage: list[AppUsage], notes: list[ManualNote]) -> str:
        if notes:
            return tr(
                "这一天重要的不是软件使用了多久，而是你主动留下了一个线索。\n"
                "未来再回看时，这句话会比冷冰冰的统计更接近今天真正的意义。",
                "What matters is not only how long an app was open, but the clue you chose to leave.\n"
                "That note may bring you closer to what today actually meant.",
            )
        if app_usage:
            top = self._top_app(app_usage)
            return tr(
                f"今天的记录已经开始积累，{top or '一些软件'} 是目前最明显的线索。\n"
                "这些数据不是结论，只是证据。Echo 会把它们放回今天的故事里。",
                f"Today's record is taking shape, with {top or 'several apps'} as the clearest clue.\n"
                "The data is evidence, not a conclusion.",
            )
        return tr("今天还没有记录。Echo 会在后台安静地记录你把时间花在了哪里。", "There are no records yet. Echo will quietly capture where your time goes.")

    def _memory_reason(self, notes: list[ManualNote]) -> str:
        if notes:
            return tr("这句话让今天不只是一组窗口切换，而是有了可以被未来理解的原因。", "This note gives the window changes a reason your future self can understand.")
        return tr("主动写下的一句话，往往比自动记录更能说明今天为什么重要。", "A note often explains why today mattered better than automatic activity alone.")

    def _evidence_line(self, app_usage: list[AppUsage], notes: list[ManualNote]) -> str:
        total = sum(max(usage.duration_seconds or 0, 0) for usage in app_usage)
        software_count = len({usage.app_name for usage in app_usage})
        top = self._top_app(app_usage) or tr("暂无", "None")
        return tr(
            f"今日记录 {human_duration(total)} · {software_count} 个软件 · "
            f"{len(notes)} 条手动记录 · 最常用 {top}",
            f"Recorded {human_duration(total)} · {software_count} apps · "
            f"{len(notes)} notes · most used: {top}",
        )

    def _recording_status_text(
        self,
        app_usage: list[AppUsage],
        notes: list[ManualNote],
        moods: list[MoodEntry] | None = None,
    ) -> str:
        total = sum(max(usage.duration_seconds or 0, 0) for usage in app_usage)
        software_count = len({usage.app_name for usage in app_usage if usage.app_name})
        last_update = self._last_update_time(app_usage, notes, moods or [])
        return tr(
            f"正在记录 · 今日 {human_duration(total)} · "
            f"{software_count} 个软件 · 最后更新 {last_update}",
            f"Recording · {human_duration(total)} today · "
            f"{software_count} apps · updated {last_update}",
        )

    def _today_status_text(
        self,
        app_usage: list[AppUsage],
        notes: list[ManualNote],
        moods: list[MoodEntry],
    ) -> str:
        if not app_usage and not notes and not moods:
            return tr("记录还在积累。Echo 会在后台安静地保存今天的原始线索。", "Echo is quietly collecting today's local clues.")
        lines = [tr("记录正在积累。", "Records are accumulating.")]
        if moods:
            lines.append(tr("心情记录会作为时间线事件出现，照片只是附件，不是相册。", "Mood moments appear on the timeline; photos remain local attachments."))
        if notes:
            lines.append(tr("今天已经留下了一句话，可以作为日报理解今天的线索。", "Today's note can help the reflection understand the day."))
        return "\n".join(lines)

    def _last_update_time(
        self,
        app_usage: list[AppUsage],
        notes: list[ManualNote],
        moods: list[MoodEntry] | None = None,
    ) -> str:
        values: list[str] = []
        for usage in app_usage:
            values.append(usage.end_time or usage.start_time)
        for note in notes:
            values.append(note.created_at)
        for mood in moods or []:
            values.append(mood.created_at)
        if not values:
            return "--:--"
        return display_time(max(values))

    def _outcomes(self, app_usage: list[AppUsage], notes: list[ManualNote]) -> list[str]:
        outcomes: list[str] = []
        if notes:
            outcomes.append(tr("留下了主动记录，让今天有了可以回看的意义", "Left a note that gives today meaning to revisit"))
        if any("code" in usage.app_name.lower() for usage in app_usage):
            outcomes.append(tr("继续推进了项目开发，把想法落到实际功能里", "Moved project work from ideas into real features"))
        if any(name in usage.app_name.lower() for usage in app_usage for name in ["chrome", "edge"]):
            outcomes.append(tr("查找和吸收资料，为后续判断补充证据", "Researched information to support later decisions"))
        if app_usage:
            outcomes.append(tr("让 Echo 多积累了一天真实的使用轨迹", "Added another day of real activity to Echo"))
        if not outcomes:
            outcomes.append(tr("今天还没有推进记录，先让 Echo 安静等一天开始", "There is no activity yet; Echo is waiting for the day to begin"))
        return outcomes[:4]

    def _top_app(self, app_usage: list[AppUsage]) -> str | None:
        usage_by_app: dict[str, int] = defaultdict(int)
        for usage in app_usage:
            usage_by_app[usage.app_name or "Unknown"] += max(usage.duration_seconds or 0, 0)
        if not usage_by_app:
            return None
        return max(usage_by_app.items(), key=lambda item: item[1])[0]

    def _entry_hour(self, payload: AppUsage | ManualNote | MoodEntry) -> str:
        raw_time = payload.start_time if isinstance(payload, AppUsage) else payload.created_at
        shown = display_time(raw_time)
        if len(shown) >= 2 and shown[:2].isdigit():
            return f"{shown[:2]}:00"
        return tr("时间未记录", "Time unavailable")

    def _category_for_usage(self, usage: AppUsage) -> str:
        name = f"{usage.app_name} {usage.window_title}".lower()
        if any(key in name for key in ["code", "pycharm", "visual studio", "cursor", "keil", "stm32", "git"]):
            return tr("开发", "Development")
        if any(key in name for key in ["figma", "photoshop", "illustrator", "sketch"]):
            return tr("设计", "Design")
        if any(key in name for key in ["chrome", "edge", "browser", "openai", "docs", "wiki"]):
            return tr("学习", "Learning")
        if any(key in name for key in ["steam", "game", "bilibili", "youtube", "music", "video"]):
            return tr("娱乐", "Entertainment")
        if any(key in name for key in ["explorer", "system", "settings", "taskmgr", "searchhost"]):
            return tr("系统", "System")
        return tr("其他", "Other")

    def _day_count_text(self) -> str:
        first_date = self.database.get_first_record_date()
        if not first_date:
            return tr("第 1 天", "Day 1")
        try:
            first = date.fromisoformat(first_date)
            days = max((date.today() - first).days + 1, 1)
        except ValueError:
            logger.exception("Invalid first record date: %s", first_date)
            days = 1
        return tr(f"第 {days} 天", f"Day {days}")

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

