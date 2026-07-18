from __future__ import annotations

import logging
from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QTime, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractSpinBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTimeEdit, QVBoxLayout, QWidget

from src.database.db import Database
from src.database.models import AppUsage, ManualNote
from src.i18n import tr
from src.ui.pages.timeline_page import merge_activity_sessions
from src.utils.time_utils import display_time, today_str

logger = logging.getLogger(__name__)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def replay_window(app_usage: list[AppUsage], notes: list[ManualNote], center: datetime, minutes: int = 30) -> tuple[list[AppUsage], list[ManualNote]]:
    """Return records intersecting the time window around center."""
    start, end = center - timedelta(minutes=minutes), center + timedelta(minutes=minutes)
    usages = []
    for usage in app_usage:
        usage_start = _parse_datetime(usage.start_time)
        usage_end = _parse_datetime(usage.end_time) or usage_start
        if usage_start and usage_end and usage_start <= end and usage_end >= start:
            usages.append(usage)
    selected_notes = []
    for note in notes:
        created = _parse_datetime(note.created_at)
        if created and start <= created <= end:
            selected_notes.append(note)
    return usages, selected_notes


class MemoryFragmentCard(QFrame):
    clicked = Signal(str, str)

    def __init__(self, date_text: str, time_text: str, title: str, trail: str, active: bool = False) -> None:
        super().__init__()
        self.date_text, self.time_text = date_text, time_text
        self.setObjectName("memoryFragment")
        self.setProperty("active", active)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(17, 14, 17, 15)
        layout.setSpacing(7)
        meta = QHBoxLayout()
        when = QLabel(f"{date_text} · {time_text}")
        when.setObjectName("fragmentMeta")
        category = QLabel(tr("工作", "Work"))
        category.setObjectName("orangeSmall")
        meta.addWidget(when)
        meta.addStretch()
        meta.addWidget(category)
        heading = QLabel(title)
        heading.setObjectName("fragmentTitle")
        detail = QLabel(trail)
        detail.setObjectName("fragmentTrail")
        detail.setWordWrap(True)
        layout.addLayout(meta)
        layout.addWidget(heading)
        layout.addWidget(detail)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.date_text, self.time_text.split("–", 1)[0])
        super().mouseReleaseEvent(event)


class ReplayTimeline(QFrame):
    """A lightweight, mouse-draggable 24-hour replay scrubber."""

    time_changed = Signal(QTime)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("replayTimeline")
        self.setMinimumHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._time = QTime.currentTime()
        self._usage_ranges: list[tuple[int, int]] = []
        self._note_minutes: list[int] = []
        self._dragging = False

    def set_records(self, usage: list[AppUsage], notes: list[ManualNote]) -> None:
        self._usage_ranges = []
        for item in usage:
            start = _parse_datetime(item.start_time)
            end = _parse_datetime(item.end_time) or start
            if start and end:
                self._usage_ranges.append((start.hour * 60 + start.minute, end.hour * 60 + end.minute))
        self._note_minutes = []
        for item in notes:
            created = _parse_datetime(item.created_at)
            if created:
                self._note_minutes.append(created.hour * 60 + created.minute)
        self.update()

    def set_time(self, value: QTime) -> None:
        self._time = value
        self.update()

    def _x_for_minutes(self, minutes: int) -> float:
        left, right = 18.0, max(19.0, float(self.width() - 18))
        return left + (right - left) * max(0, min(minutes, 1439)) / 1439

    def _minutes_for_x(self, x: float) -> int:
        left, right = 18.0, max(19.0, float(self.width() - 18))
        ratio = max(0.0, min(1.0, (x - left) / (right - left)))
        return round(ratio * 1439)

    def _update_from_x(self, x: float) -> None:
        minutes = self._minutes_for_x(x)
        snap_points = [point for pair in self._usage_ranges for point in pair] + self._note_minutes
        nearest = min(snap_points, key=lambda point: abs(point - minutes), default=None)
        if nearest is not None and abs(nearest - minutes) <= 12:
            minutes = nearest
        value = QTime(minutes // 60, minutes % 60)
        self._time = value
        self.update()
        self.time_changed.emit(value)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_from_x(event.position().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._update_from_x(event.position().x())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() // 120
        if steps:
            minutes = self._time.hour() * 60 + self._time.minute() + int(steps) * 5
            minutes = max(0, min(1439, minutes))
            self._time = QTime(minutes // 60, minutes % 60)
            self.update()
            self.time_changed.emit(self._time)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        minute_steps = {
            Qt.Key.Key_Left: -5,
            Qt.Key.Key_Right: 5,
            Qt.Key.Key_PageUp: -30,
            Qt.Key.Key_PageDown: 30,
            Qt.Key.Key_Home: -1439,
            Qt.Key.Key_End: 1439,
        }
        if event.key() in minute_steps:
            minutes = self._time.hour() * 60 + self._time.minute() + minute_steps[event.key()]
            minutes = max(0, min(1439, minutes))
            self._time = QTime(minutes // 60, minutes % 60)
            self.update()
            self.time_changed.emit(self._time)
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right = 18.0, float(self.width() - 18)
        y = 30.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#eadfce"))
        painter.drawRoundedRect(left, y - 3, max(1.0, right - left), 6, 3, 3)
        painter.setBrush(QColor("#a8c4a0"))
        for start, end in self._usage_ranges:
            x1, x2 = self._x_for_minutes(start), self._x_for_minutes(max(start + 2, end))
            painter.drawRoundedRect(x1, y - 5, max(3.0, x2 - x1), 10, 5, 5)
        painter.setPen(QPen(QColor("#c17640"), 2))
        for minute in self._note_minutes:
            x = self._x_for_minutes(minute)
            painter.drawLine(x, y - 12, x, y + 12)
        knob_x = self._x_for_minutes(self._time.hour() * 60 + self._time.minute())
        painter.setPen(QPen(QColor("#517556"), 3))
        painter.setBrush(QColor("#fffaf3"))
        painter.drawEllipse(knob_x - 7, y - 7, 14, 14)
        painter.setPen(QColor("#716555"))
        painter.drawText(int(left), 60, "00:00")
        painter.drawText(int((left + right) / 2 - 18), 60, "12:00")
        painter.drawText(int(right - 36), 60, "24:00")
        painter.setPen(QColor("#517556"))
        painter.drawText(int(max(left, knob_x - 18)), 17, self._time.toString("HH:mm"))


class MemoryPage(QWidget):
    report_requested = Signal(str)

    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.selected_date = today_str()
        self._window_minutes = 30
        self._favorite = False
        self.setObjectName("memoryPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 27, 34, 32)
        root.setSpacing(18)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        title = QLabel(tr("记忆", "Memory"))
        title.setObjectName("pageTitle")
        subtitle = QLabel(tr("不是回看数据，而是重新想起那一刻。", "Not just data—return to the moment."))
        subtitle.setObjectName("memorySubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        privacy = QLabel(tr("仅本机 · 私密回放", "On-device · Private replay"))
        privacy.setObjectName("memoryPrivacy")
        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(privacy)
        root.addLayout(header)

        picker = QFrame()
        picker.setObjectName("replayPicker")
        picker_layout = QHBoxLayout(picker)
        picker_layout.setContentsMargins(20, 15, 16, 15)
        picker_layout.setSpacing(12)
        picker_copy = QVBoxLayout()
        picker_copy.setSpacing(2)
        picker_title = QLabel(tr("回到某一刻", "Return to a moment"))
        picker_title.setObjectName("sectionLabel")
        picker_hint = QLabel(tr("选择时间，重建前后 30 分钟的上下文", "Choose a time to rebuild the surrounding context"))
        picker_hint.setObjectName("mutedSmall")
        picker_copy.addWidget(picker_title)
        picker_copy.addWidget(picker_hint)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setObjectName("memoryDateEdit")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat(tr("yyyy年M月d日", "MMM d, yyyy"))
        self.time_edit = QTimeEdit(QTime.currentTime())
        self.time_edit.setObjectName("memoryTimeEdit")
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.time_edit.setToolTip(tr("点击小时或分钟后输入，也可以使用鼠标滚轮调整", "Select hours or minutes to type, or use the mouse wheel"))
        self.replay_button = QPushButton(tr("回到这一刻  →", "Return to this moment  →"))
        self.replay_button.setObjectName("memoryReplayButton")
        self.replay_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replay_button.setMinimumHeight(42)
        self.replay_button.clicked.connect(self._start_replay)
        picker_layout.addLayout(picker_copy)
        picker_layout.addStretch()
        picker_layout.addWidget(self.date_edit)
        picker_layout.addWidget(self.time_edit)
        picker_layout.addWidget(self.replay_button)
        root.addWidget(picker)

        self.replay_timeline = ReplayTimeline()
        self.replay_timeline.time_changed.connect(self._scrub_to_time)
        self.date_edit.dateChanged.connect(lambda _value: self._refresh_scrubber_records())
        root.addWidget(self.replay_timeline)

        body = QHBoxLayout()
        body.setSpacing(18)
        fragments_panel = QWidget()
        fragments_layout = QVBoxLayout(fragments_panel)
        fragments_layout.setContentsMargins(0, 0, 0, 0)
        fragments_layout.setSpacing(10)
        fragments_head = QHBoxLayout()
        fragments_title = QLabel(tr("记忆片段", "Memory fragments"))
        fragments_title.setObjectName("sectionLabel")
        fragments_hint = QLabel(tr("按日期浏览", "Browse by date"))
        fragments_hint.setObjectName("mutedSmall")
        fragments_head.addWidget(fragments_title)
        fragments_head.addStretch()
        fragments_head.addWidget(fragments_hint)
        fragments_layout.addLayout(fragments_head)
        fragment_scroll = QScrollArea()
        fragment_scroll.setObjectName("memoryFragmentScroll")
        fragment_scroll.setWidgetResizable(True)
        fragment_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.fragments_content = QWidget()
        self.fragments_box = QVBoxLayout(self.fragments_content)
        self.fragments_box.setContentsMargins(0, 0, 4, 0)
        self.fragments_box.setSpacing(10)
        self.fragments_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        fragment_scroll.setWidget(self.fragments_content)
        fragments_layout.addWidget(fragment_scroll, 1)
        more = QPushButton(tr("查看更多早期记忆 ↓", "Show earlier memories ↓"))
        more.setObjectName("memoryLinkButton")
        more.clicked.connect(lambda: self.report_requested.emit(self.selected_date))
        fragments_layout.addWidget(more, alignment=Qt.AlignmentFlag.AlignLeft)

        self.detail = QFrame()
        self.detail.setObjectName("memoryReplayPanel")
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(24, 20, 24, 22)
        detail_layout.setSpacing(13)
        detail_head = QHBoxLayout()
        detail_title = QLabel(tr("时光回放", "Memory replay"))
        detail_title.setObjectName("reportTitle")
        self.range_label = QLabel()
        self.range_label.setObjectName("fragmentMeta")
        detail_head.addWidget(detail_title)
        detail_head.addStretch()
        detail_head.addWidget(self.range_label)
        detail_layout.addLayout(detail_head)
        self.story_card = QFrame()
        self.story_card.setObjectName("memoryStoryCard")
        self.story_card.setMaximumHeight(142)
        story_layout = QVBoxLayout(self.story_card)
        story_layout.setContentsMargins(18, 16, 18, 17)
        story_layout.setSpacing(8)
        self.story_title = QLabel()
        self.story_title.setObjectName("memoryStoryTitle")
        self.story_title.setWordWrap(True)
        self.story_body = QLabel()
        self.story_body.setObjectName("storyBody")
        self.story_body.setWordWrap(True)
        story_layout.addWidget(self.story_title)
        story_layout.addWidget(self.story_body)
        detail_layout.addWidget(self.story_card)
        trail_label = QLabel(tr("应用轨迹", "Application trail"))
        trail_label.setObjectName("mutedSmall")
        detail_layout.addWidget(trail_label)
        self.trail_row = QHBoxLayout()
        self.trail_row.setSpacing(8)
        detail_layout.addLayout(self.trail_row)
        self.note_card = QFrame()
        self.note_card.setObjectName("memoryNoteCard")
        self.note_card.setMaximumHeight(96)
        note_layout = QVBoxLayout(self.note_card)
        note_layout.setContentsMargins(16, 13, 16, 14)
        note_layout.setSpacing(6)
        self.note_time = QLabel()
        self.note_time.setObjectName("orangeSmall")
        self.note_body = QLabel()
        self.note_body.setObjectName("storyBody")
        self.note_body.setWordWrap(True)
        note_layout.addWidget(self.note_time)
        note_layout.addWidget(self.note_body)
        detail_layout.addWidget(self.note_card)
        actions = QHBoxLayout()
        actions.setSpacing(9)
        self.favorite_button = QPushButton(tr("收藏这段记忆", "Favorite this memory"))
        self.favorite_button.setObjectName("primaryButton")
        self.favorite_button.clicked.connect(self._toggle_favorite)
        expand_button = QPushButton(tr("前后 30 分钟", "± 30 minutes"))
        expand_button.setObjectName("memoryOutlineButton")
        expand_button.clicked.connect(self._expand_window)
        report_button = QPushButton(tr("继续这件事", "Continue this"))
        report_button.setObjectName("memoryOutlineButton")
        report_button.clicked.connect(lambda: self.report_requested.emit(self.selected_date))
        actions.addWidget(self.favorite_button)
        actions.addWidget(expand_button)
        actions.addWidget(report_button)
        actions.addStretch()
        detail_layout.addLayout(actions)
        local_hint = QLabel(tr("所有内容都由本地活动记录、笔记与心情整理而成。", "Everything here is reconstructed from local activity, notes, and moods."))
        local_hint.setObjectName("mutedSmall")
        detail_layout.addWidget(local_hint)
        detail_layout.addStretch()
        body.addWidget(fragments_panel, 5)
        body.addWidget(self.detail, 8)
        root.addLayout(body, 1)
        self.refresh()

    def refresh(self) -> None:
        self._refresh_scrubber_records()
        self._render_fragments()
        self._render_replay()

    def _refresh_scrubber_records(self) -> None:
        date_text = self.date_edit.date().toString("yyyy-MM-dd")
        self.replay_timeline.set_records(
            self.database.get_app_usage_by_date(date_text),
            self.database.get_manual_notes_by_date(date_text),
        )
        self.replay_timeline.set_time(self.time_edit.time())

    def _scrub_to_time(self, value: QTime) -> None:
        self.time_edit.setTime(value)
        self._window_minutes = 30
        self._favorite = False
        self._render_replay()

    def _start_replay(self) -> None:
        self.selected_date = self.date_edit.date().toString("yyyy-MM-dd")
        self._window_minutes = 30
        self._favorite = False
        self._refresh_scrubber_records()
        self._render_fragments()
        self._render_replay()

    def _select_fragment(self, date_text: str, time_text: str) -> None:
        self.selected_date = date_text
        parsed_date, parsed_time = QDate.fromString(date_text, "yyyy-MM-dd"), QTime.fromString(time_text, "HH:mm")
        if parsed_date.isValid(): self.date_edit.setDate(parsed_date)
        if parsed_time.isValid(): self.time_edit.setTime(parsed_time)
        self._window_minutes = 30
        self._favorite = False
        self._render_fragments()
        self._render_replay()

    def _render_fragments(self) -> None:
        self._clear_layout(self.fragments_box)
        by_date: dict[str, list[AppUsage]] = {}
        for row in self.database.get_recent_app_usage(500):
            by_date.setdefault(row.date, []).append(row)
        dates = sorted(by_date, reverse=True)[:5]
        if self.selected_date not in dates: dates.insert(0, self.selected_date)
        for date_text in dates[:5]:
            sessions = merge_activity_sessions(by_date.get(date_text, []))
            apps = []
            for session in sessions:
                if session.app_name and session.app_name not in apps: apps.append(session.app_name)
            notes = self.database.get_manual_notes_by_date(date_text)
            if sessions:
                start, end = display_time(sessions[0].start_time), display_time(sessions[-1].end_time or sessions[-1].start_time)
                title = notes[-1].content if notes else self._fragment_title(apps)
                trail = " → ".join(apps[:3]) or tr("本地活动记录", "Local activity")
            else:
                start = end = "--:--"
                title = notes[-1].content if notes else tr("等待形成新的记忆", "Waiting for a new memory")
                trail = tr("这一刻还没有足够的上下文", "Not enough context around this moment")
            card = MemoryFragmentCard(date_text, f"{start}–{end}", title, trail, date_text == self.selected_date)
            card.clicked.connect(self._select_fragment)
            self.fragments_box.addWidget(card)

    def _render_replay(self) -> None:
        try:
            date_text = self.date_edit.date().toString("yyyy-MM-dd")
            center = datetime.combine(datetime.strptime(date_text, "%Y-%m-%d").date(), datetime.strptime(self.time_edit.time().toString("HH:mm"), "%H:%M").time())
            usages, notes = replay_window(self.database.get_app_usage_by_date(date_text), self.database.get_manual_notes_by_date(date_text), center, self._window_minutes)
            sessions = merge_activity_sessions(usages)
            apps = []
            for session in sessions:
                if session.app_name and session.app_name not in apps: apps.append(session.app_name)
            start, end = center - timedelta(minutes=self._window_minutes), center + timedelta(minutes=self._window_minutes)
            self.range_label.setText(
                tr(
                    f"{start:%H:%M}–{end:%H:%M} · {self._window_minutes * 2}分钟",
                    f"{start:%H:%M}–{end:%H:%M} · {self._window_minutes * 2} min",
                )
            )
            if usages or notes:
                focus = apps[0] if apps else tr("这件事", "this activity")
                self.story_title.setText(tr(f"你正在专注于 {focus}", f"You were focused on {focus}"))
                sequence = tr("、", ", ").join(apps[:3]) if apps else tr("手动记录", "a manual note")
                note_sentence = (
                    tr(f"期间留下了“{notes[-1].content}”。", f'You left the note “{notes[-1].content}”.')
                    if notes
                    else tr("这段时间没有留下手动备注。", "No manual note was left during this time.")
                )
                self.story_body.setText(
                    tr(
                        f"这一小时的上下文主要由 {sequence} 组成，共捕捉到 {len(sessions)} 段连续活动。{note_sentence}",
                        f"This hour was mainly made up of {sequence}, across {len(sessions)} continuous sessions. {note_sentence}",
                    )
                )
            else:
                self.story_title.setText(tr("这一刻还很安静", "This moment is still quiet"))
                self.story_body.setText(tr("所选时间附近没有足够的活动记录。换一个时间，Echo 会带你回到更清晰的一刻。", "There is not enough activity around the selected time. Try another moment."))
            self._render_trail(apps)
            self.note_time.setText(
                tr(f"{display_time(notes[-1].created_at)} · 留下一句话", f"{display_time(notes[-1].created_at)} · Note")
                if notes
                else tr("这一刻 · 上下文线索", "This moment · Context")
            )
            self.note_body.setText(
                notes[-1].content
                if notes
                else tr("没有一句话也没关系，应用切换本身已经构成了这段记忆的轨迹。", "Even without a note, application changes form a trail through this memory.")
            )
        except Exception:
            logger.exception("Failed to render memory replay: %s", self.selected_date)

    def _render_trail(self, apps: list[str]) -> None:
        self._clear_layout(self.trail_row)
        for app in apps[:5] or [tr("暂无轨迹", "No activity trail")]:
            tag = QLabel(app)
            tag.setObjectName("memoryTrailTag")
            self.trail_row.addWidget(tag)
        self.trail_row.addStretch()

    def _toggle_favorite(self) -> None:
        self._favorite = not self._favorite
        self.favorite_button.setText(
            tr("已收藏", "Favorited")
            if self._favorite
            else tr("收藏这段记忆", "Favorite this memory")
        )
        self.favorite_button.setProperty("saved", self._favorite)
        self.favorite_button.style().unpolish(self.favorite_button)
        self.favorite_button.style().polish(self.favorite_button)

    def _expand_window(self) -> None:
        self._window_minutes = 60 if self._window_minutes == 30 else 30
        self._render_replay()

    @staticmethod
    def _fragment_title(apps: list[str]) -> str:
        if not apps:
            return tr("等待形成新的记忆", "Waiting for a new memory")
        return (
            tr(f"专注使用 {apps[0]}", f"Focused on {apps[0]}")
            if len(apps) == 1
            else tr("完成一段连续的工作", "Completed a continuous work session")
        )

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            elif item.layout(): MemoryPage._clear_layout(item.layout())
