from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from src.database.db import Database
from src.database.models import AppUsage
from src.i18n import tr
from src.utils.time_utils import display_time, human_duration, parse_db_datetime, today_str


CATEGORY_LABELS = {
    "all": ("全部分类", "All categories"),
    "work": ("工作", "Work"),
    "study": ("学习", "Study"),
    "communication": ("沟通", "Communication"),
    "entertainment": ("娱乐", "Entertainment"),
    "other": ("其他", "Other"),
}


def activity_category(app_name: str, title: str = "") -> str:
    text = f"{app_name} {title}".lower()
    rules = {
        "work": ("code", "visual studio", "pycharm", "word", "wps", "excel"),
        "study": ("pdf", "kindle", "学习", "课程", "docs"),
        "communication": ("wechat", "weixin", "微信", "teams", "slack", "qq"),
        "entertainment": ("game", "steam", "bilibili", "youtube", "netflix", "音乐"),
    }
    return next((category for category, keys in rules.items() if any(key in text for key in keys)), "other")


@dataclass
class ActivitySession:
    date: str
    app_name: str
    title: str
    start_time: str
    end_time: str | None
    duration_seconds: int
    category: str


def merge_activity_sessions(rows: list[AppUsage], max_gap_seconds: int = 120) -> list[ActivitySession]:
    sessions: list[ActivitySession] = []
    for row in rows:
        if sessions and sessions[-1].app_name == row.app_name and sessions[-1].date == row.date and sessions[-1].end_time:
            gap = (parse_db_datetime(row.start_time) - parse_db_datetime(sessions[-1].end_time)).total_seconds()
            if 0 <= gap <= max_gap_seconds:
                sessions[-1].end_time = row.end_time
                sessions[-1].duration_seconds += max(row.duration_seconds, 0)
                sessions[-1].title = row.window_title or sessions[-1].title
                continue
        sessions.append(ActivitySession(row.date, row.app_name, row.window_title, row.start_time, row.end_time, max(row.duration_seconds, 0), activity_category(row.app_name, row.window_title)))
    return sessions


class TimelinePage(QWidget):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.setObjectName("content")
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 34)
        root.setSpacing(18)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)
        title = QLabel(tr("时间线", "Timeline"))
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            tr(
                "连续活动会自动合并；可以按应用、窗口标题或分类搜索最近记录。",
                "Continuous activity is merged automatically. Search recent records by app, title, or category.",
            )
        )
        subtitle.setObjectName("storyBody")
        controls = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("搜索应用或窗口标题", "Search apps or window titles"))
        self.category_filter = QComboBox()
        for key, labels in CATEGORY_LABELS.items():
            self.category_filter.addItem(tr(*labels), key)
        controls.addWidget(self.search_input, 1)
        controls.addWidget(self.category_filter)
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 18, 22, 18)
        self.rows_layout = QVBoxLayout()
        card_layout.addLayout(self.rows_layout)
        root.addWidget(title)
        root.addWidget(subtitle)
        self.stats_label = QLabel()
        self.stats_label.setObjectName("recordingStatus")
        root.addWidget(self.stats_label)
        root.addLayout(controls)
        root.addWidget(card)
        root.addStretch()
        self.search_input.textChanged.connect(self.refresh)
        self.category_filter.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args) -> None:
        self._clear_rows()
        query = self.search_input.text().strip().lower()
        category = self.category_filter.currentData()
        today_usage = self.database.get_app_usage_by_date(today_str())
        total_seconds = sum(max(item.duration_seconds, 0) for item in today_usage)
        today_apps = len({item.app_name for item in today_usage})
        today_notes = len(self.database.get_manual_notes_by_date(today_str()))
        self.stats_label.setText(
            tr(
                f"今日：{human_duration(total_seconds)} · {today_apps} 个应用 · {today_notes} 条手动记录",
                f"Today: {human_duration(total_seconds)} · {today_apps} apps · {today_notes} notes",
            )
        )
        sessions = [item for item in merge_activity_sessions(self.database.get_recent_app_usage(limit=5000)) if (not query or query in f"{item.app_name} {item.title}".lower()) and (category == "all" or item.category == category)]
        matching_notes = self.database.search_manual_notes(query) if query else []
        if not sessions and not matching_notes:
            self.rows_layout.addWidget(QLabel(tr("没有符合条件的活动记录。", "No matching activity.")))
            return
        # Keep the live widget tree bounded. The full history remains queryable,
        # while only the most relevant recent matches need to be painted.
        for session in reversed(sessions[-40:]):
            row = QFrame()
            row.setObjectName("quietCard")
            layout = QHBoxLayout(row)
            when = QLabel(f"{session.date}\n{display_time(session.start_time)}")
            text = QLabel(session.app_name + (f"\n{session.title}" if session.title else ""))
            text.setWordWrap(True)
            badge = QLabel(tr(*CATEGORY_LABELS[session.category]))
            badge.setObjectName("recordingStatus")
            layout.addWidget(when)
            layout.addWidget(text, 1)
            layout.addWidget(badge)
            layout.addWidget(QLabel(human_duration(session.duration_seconds)))
            self.rows_layout.addWidget(row)
        for note in matching_notes[:40]:
            row = QFrame()
            row.setObjectName("quietCard")
            layout = QHBoxLayout(row)
            when = QLabel(f"{note.date}\n{display_time(note.created_at)}")
            text = QLabel(tr(f"手动记录\n{note.content}", f"Manual note\n{note.content}"))
            text.setWordWrap(True)
            badge = QLabel(tr("笔记", "Note"))
            badge.setObjectName("recordingStatus")
            layout.addWidget(when)
            layout.addWidget(text, 1)
            layout.addWidget(badge)
            self.rows_layout.addWidget(row)

    def _clear_rows(self) -> None:
        while self.rows_layout.count():
            widget = self.rows_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
