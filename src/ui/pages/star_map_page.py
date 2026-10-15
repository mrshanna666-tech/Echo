from __future__ import annotations

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from src.database.db import Database
from src.memory_star_map import MemoryAtlas, build_memory_atlas
from src.i18n import tr
from src.ui.pages.star_map_canvas import StarMapView
from src.utils.time_utils import display_time, human_duration


class StarMapPage(QWidget):
    replay_requested = Signal(str, str)
    exit_requested = Signal()

    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.setObjectName("starMapPage")
        self._usage = []
        self._notes = []
        self._truncated = False
        self._atlas = MemoryAtlas()
        self._selected_key = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.view = StarMapView()
        root.addWidget(self.view)

        # These are small sibling overlays. The entire page beneath them is
        # the canvas; no invisible full-page overlay intercepts pan or zoom.
        self.heading = QWidget(self)
        self.heading.setObjectName("atlasHeading")
        heading = QVBoxLayout(self.heading)
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(5)
        eyebrow = QLabel("ECHO  /  MEMORY ATLAS")
        eyebrow.setObjectName("atlasEyebrow")
        title = QLabel(tr("记忆星图", "Memory atlas"))
        title.setObjectName("atlasTitle")
        subtitle = QLabel(tr("让散落的日子，慢慢连成星群。", "Let the scattered days become constellations."))
        subtitle.setObjectName("atlasMuted")
        heading.addWidget(eyebrow)
        heading.addWidget(title)
        heading.addWidget(subtitle)
        self.heading.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.back_button = QPushButton(tr("←  返回 Echo", "←  Back to Echo"), self)
        self.back_button.setObjectName("atlasTool")
        self.back_button.clicked.connect(self.exit_requested.emit)
        self.back_button.setAccessibleName(tr("退出星图，返回 Echo", "Leave the atlas and return to Echo"))

        self.controls = QFrame(self)
        self.controls.setObjectName("atlasControls")
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(8, 6, 8, 6)
        controls.setSpacing(6)
        self.period_combo = QComboBox()
        for days in (7, 30, 90):
            self.period_combo.addItem(tr(f"最近 {days} 天", f"Last {days} days"), days)
        self.period_combo.setCurrentIndex(1)
        self.period_combo.setAccessibleName(tr("星图时间范围", "Atlas time span"))
        self.end_date = QDateEdit(QDate.currentDate())
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.setAccessibleName(tr("星图截止日期", "Atlas end date"))
        self.app_combo = QComboBox()
        self.app_combo.setMinimumWidth(125)
        self.app_combo.setMaximumWidth(175)
        self.app_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.app_combo.setMinimumContentsLength(8)
        self.app_combo.setAccessibleName(tr("选择应用星群或笔记", "Select an app constellation or notes"))
        self.search_input = QLineEdit()
        self.search_input.setMinimumWidth(130)
        self.search_input.setPlaceholderText(tr("寻找一段记忆…", "Find a memory…"))
        self.search_input.setAccessibleName(tr("搜索星图", "Search atlas"))
        self.list_button = QPushButton(tr("星点列表", "Star list"))
        self.list_button.setObjectName("atlasTool")
        self.list_button.clicked.connect(self._open_star_list)
        for widget in (self.period_combo, self.end_date, self.app_combo, self.search_input, self.list_button):
            controls.addWidget(widget, 1 if widget is self.search_input else 0)

        self.footer = QWidget(self)
        self.footer.setObjectName("atlasFooter")
        footer = QVBoxLayout(self.footer)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(5)
        info = QHBoxLayout()
        info.setSpacing(16)
        self.stats_label = QLabel()
        self.stats_label.setObjectName("atlasStats")
        self.range_label = QLabel()
        self.range_label.setObjectName("atlasMuted")
        info.addWidget(self.stats_label)
        info.addWidget(self.range_label)
        info.addStretch()
        footer.addLayout(info)
        self.status_label = QLabel()
        self.status_label.setObjectName("atlasMuted")
        footer.addWidget(self.status_label)

        self.tools = QFrame(self)
        self.tools.setObjectName("atlasControls")
        tools = QHBoxLayout(self.tools)
        tools.setContentsMargins(6, 5, 6, 5)
        tools.setSpacing(4)
        for label, name, action in (
            ("−", tr("缩小星图", "Zoom out"), lambda: self.view.zoom_by(1 / 1.25)),
            ("+", tr("放大星图", "Zoom in"), lambda: self.view.zoom_by(1.25)),
            (tr("全景", "Fit"), tr("查看完整星图", "Fit the complete atlas"), self._fit_all),
        ):
            button = QPushButton(label)
            button.setObjectName("atlasTool")
            button.setAccessibleName(name)
            button.setToolTip(name)
            button.clicked.connect(action)
            tools.addWidget(button)
        self.help_label = QLabel(tr("拖动探索 · 滚轮缩放 · 点击星点回看", "Drag to explore · Scroll to zoom · Click a star"), self)
        self.help_label.setObjectName("atlasMuted")
        self.help_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.detail_panel = QFrame(self)
        self.detail_panel.setObjectName("atlasDetail")
        detail_layout = QVBoxLayout(self.detail_panel)
        detail_layout.setContentsMargins(18, 17, 18, 16)
        detail_layout.setSpacing(12)
        section_row = QHBoxLayout()
        section = QLabel(tr("星点里的记忆", "Inside a memory"))
        section.setObjectName("atlasEyebrow")
        self.close_detail_button = QPushButton("×")
        self.close_detail_button.setObjectName("atlasClose")
        self.close_detail_button.setAccessibleName(tr("收起记忆详情", "Close memory details"))
        self.close_detail_button.setToolTip(tr("收起详情 · Esc", "Close details · Esc"))
        self.close_detail_button.clicked.connect(self._close_detail)
        section_row.addWidget(section, 1)
        section_row.addWidget(self.close_detail_button)
        detail_layout.addLayout(section_row)
        self.star_picker = QComboBox()
        self.star_picker.setAccessibleName(tr("从列表选择星点", "Select a star from the list"))
        self.star_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.star_picker.setMinimumContentsLength(8)
        detail_layout.addWidget(self.star_picker)
        self.detail_title = QLabel()
        self.detail_title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_title.setObjectName("atlasDetailTitle")
        self.detail_title.setWordWrap(True)
        self.detail_meta = QLabel()
        self.detail_meta.setObjectName("atlasMuted")
        self.detail_meta.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_meta)
        self.sources_scroll = QScrollArea()
        self.sources_scroll.setWidgetResizable(True)
        self.sources_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.sources_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("atlasSourceList")
        self.sources_layout = QVBoxLayout(content)
        self.sources_layout.setContentsMargins(0, 0, 5, 0)
        self.sources_layout.setSpacing(10)
        self.sources_scroll.setWidget(content)
        detail_layout.addWidget(self.sources_scroll, 1)
        self.detail_hint = QLabel()
        self.detail_hint.setObjectName("atlasMuted")
        self.detail_hint.setWordWrap(True)
        detail_layout.addWidget(self.detail_hint)
        self.detail_panel.hide()

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._redraw)
        self.search_input.textChanged.connect(lambda: self._search_timer.start())
        self.period_combo.currentIndexChanged.connect(self.refresh)
        self.end_date.dateChanged.connect(self.refresh)
        self.app_combo.currentIndexChanged.connect(self._redraw)
        self.star_picker.currentIndexChanged.connect(self._pick_star)
        self.view.star_selected.connect(self._show_star)
        self.view.star_activated.connect(self._activate_star)
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._escape.activated.connect(self._escape_pressed)
        self._apply_styles()
        self.refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "detail_panel"):
            self._position_overlays()

    def _position_overlays(self) -> None:
        w, h = self.width(), self.height()
        margin = 32 if w >= 1100 else 24
        self.heading.setGeometry(margin, 24, min(470, w - 220), 80)
        self.back_button.adjustSize()
        self.back_button.move(w - margin - self.back_button.width(), 28)
        self.controls.setGeometry(margin, 119, min(w - margin * 2, 850), 48)
        self.tools.adjustSize()
        self.tools.move(w - margin - self.tools.width(), h - 66)
        self.footer.setGeometry(margin, h - 66, max(180, w - margin * 2 - self.tools.width() - 20), 44)
        self.help_label.adjustSize()
        self.help_label.move(margin, h - 96)
        self.detail_panel.setGeometry(w - margin - 330, 183, 330, max(260, h - 270))
        for widget in (self.heading, self.back_button, self.controls, self.tools, self.footer,
                       self.help_label, self.detail_panel):
            widget.raise_()

    def _activate_star(self, key: str) -> None:
        if not key:
            return
        self.detail_panel.show()
        self._position_overlays()
        self.view.focus_star(key, self.detail_panel.width() + 32)

    def _open_star_list(self) -> None:
        if self._atlas.stars and not self._selected_key:
            self.view.select_star(self._atlas.stars[0].key)
        self.detail_panel.show()
        self._position_overlays()
        self.star_picker.setFocus(Qt.FocusReason.OtherFocusReason)

    def _close_detail(self) -> None:
        self.detail_panel.hide()
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)

    def _fit_all(self) -> None:
        self._close_detail()
        self.view.fit_all()

    def _escape_pressed(self) -> None:
        if self.detail_panel.isVisible():
            self._close_detail()
        else:
            self.exit_requested.emit()

    def refresh(self, *_args) -> None:
        self._search_timer.stop()
        end = self.end_date.date()
        start = end.addDays(1 - int(self.period_combo.currentData()))
        self.range_label.setText(f"{start.toString('MM.dd')} — {end.toString('MM.dd')}")
        self._usage, self._notes, self._truncated = self.database.get_star_map_records(
            start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd"),
        )
        selected = self.app_combo.currentData()
        self.app_combo.blockSignals(True)
        self.app_combo.clear()
        self.app_combo.addItem(tr("所有星群", "All constellations"), ("all", ""))
        self.app_combo.addItem(tr("只看笔记", "Notes only"), ("notes", ""))
        apps = {row.app_name.casefold(): row.app_name for row in self._usage}
        for key in sorted(apps):
            self.app_combo.addItem(apps[key] or "Unknown", ("app", key))
        index = self.app_combo.findData(selected)
        self.app_combo.setCurrentIndex(max(index, 0))
        self.app_combo.blockSignals(False)
        self._redraw()

    def _redraw(self, *_args) -> None:
        scope, app = self.app_combo.currentData() or ("all", "")
        self._atlas = build_memory_atlas(self._usage, self._notes, query=self.search_input.text(),
                                         app_filter=app if scope == "app" else None, notes_only=scope == "notes")
        self.stats_label.setText(tr(
            f"{self._atlas.app_count} 个星群   ·   {len(self._atlas.stars)} 个星点   ·   {self._atlas.day_count} 天",
            f"{self._atlas.app_count} constellations   ·   {len(self._atlas.stars)} stars   ·   {self._atlas.day_count} days",
        ))
        self.star_picker.blockSignals(True)
        self.star_picker.clear()
        for star in self._atlas.stars:
            label = tr("笔记", "Note") + " · " + star.label.replace("\n", " ")[:24] if star.kind == "note" else (
                star.app_name + " · " + star.label[5:] if star.kind == "day" else star.label)
            self.star_picker.addItem(label, star.key)
        self.star_picker.blockSignals(False)
        parts = [tr(f"可追溯到 {self._atlas.source_count} 条本地记录。",
                    f"Linked to {self._atlas.source_count} local records.")]
        if self._atlas.hidden_apps or self._atlas.hidden_days:
            parts.append(tr("全景展示最活跃的 8 个应用，每个应用最近 12 天；选择应用可展开整个时段。",
                            "Overview shows the 8 most active apps and their latest 12 days; select an app to expand the period."))
        if self._atlas.hidden_notes:
            parts.append(tr("笔记展示最近 40 条，可搜索更早的笔记。", "Showing the latest 40 notes; search to find earlier ones."))
        if self._truncated:
            parts.append(tr("记录较多，每类已加载最近 20,000 条；缩短时段可查看其余记录。",
                            "Loaded the latest 20,000 records per type; shorten the period to see other records."))
        self.status_label.setText(tr(
            f"仅本机 · {self._atlas.source_count} 条来源" + (" · 部分记录已折叠 ⓘ" if len(parts) > 1 else ""),
            f"On-device · {self._atlas.source_count} sources" + (" · Some records folded ⓘ" if len(parts) > 1 else ""),
        ))
        explanation = tr(
            "连线表示同一应用的跨日记录，或相隔 30 分钟内的笔记。暖白亮星是应用，蓝白星点是活动，琥珀星点是笔记。",
            "Links connect days in the same app, or notes within 30 minutes of activity. Warm stars are apps, blue-white stars are activity, and amber stars are notes.",
        )
        self.status_label.setToolTip(" ".join(parts) + "\n" + explanation)
        self.status_label.setAccessibleDescription(" ".join(parts) + " " + explanation)
        self.view.set_atlas(self._atlas)

    def _pick_star(self, *_args) -> None:
        key = self.star_picker.currentData()
        if key:
            self.view.select_star(key, reveal=True)

    def _show_star(self, key: str) -> None:
        self._selected_key = key
        while self.sources_layout.count():
            item = self.sources_layout.takeAt(0)
            if item.widget():
                for label in item.widget().findChildren(QLabel):
                    label.clear()
                for button in item.widget().findChildren(QPushButton):
                    button.clicked.disconnect()
                    button.hide()
                item.widget().hide()
                item.widget().deleteLater()
        star = next((star for star in self._atlas.stars if star.key == key), None)
        if star is None:
            self.detail_panel.hide()
            self.detail_title.setText(tr("等待下一颗星", "Waiting for a star"))
            self.detail_meta.setText(tr("选择星点，查看这段记忆的来源。", "Choose a star to inspect its recorded sources."))
            self.detail_hint.clear()
            return
        self.star_picker.blockSignals(True)
        self.star_picker.setCurrentIndex(self.star_picker.findData(key))
        self.star_picker.blockSignals(False)
        self.detail_title.setText(tr("你留下的一句话", "A note you left") if star.kind == "note" else star.label)
        days = len({source.date for source in star.sources})
        duration = sum(source.duration_seconds for source in star.sources)
        self.detail_meta.setText(tr(
            f"{days} 天 · {len(star.sources)} 条来源" + (f" · {human_duration(duration)}" if duration else ""),
            f"{days} days · {len(star.sources)} sources" + (f" · {human_duration(duration)}" if duration else ""),
        ))
        for source in sorted(star.sources, key=lambda item: (item.timestamp, item.record_id), reverse=True)[:20]:
            card = QFrame()
            card.setObjectName("atlasSource")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(7)
            try:
                time = display_time(source.timestamp)
            except ValueError:
                time = "--:--"
            when = QLabel(f"{source.date} · {time}")
            when.setObjectName("atlasSourceTime")
            body = QLabel(source.detail or source.title)
            body.setTextFormat(Qt.TextFormat.PlainText)
            body.setWordWrap(True)
            body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(when)
            layout.addWidget(body)
            if source.kind == "activity":
                meta = QLabel(f"{source.title} · {human_duration(source.duration_seconds)}")
                meta.setObjectName("atlasMuted")
                meta.setWordWrap(True)
                layout.addWidget(meta)
            replay = QPushButton(tr("回到这一刻  ↗", "Return to this moment  ↗"))
            replay.setObjectName("atlasReplay")
            replay.clicked.connect(lambda checked=False, evidence=source: self.replay_requested.emit(evidence.date, evidence.timestamp))
            layout.addWidget(replay)
            self.sources_layout.addWidget(card)
        self.sources_layout.addStretch()
        self.sources_scroll.verticalScrollBar().setValue(0)
        self.detail_hint.setText(tr(
            f"共 {len(star.sources)} 条来源，展示最近 20 条。" if len(star.sources) > 20 else "每个星点，都有一段可回看的来源。",
            f"{len(star.sources)} sources; showing the latest 20." if len(star.sources) > 20 else "Every star leads back to a recorded moment.",
        ))

    def clear_private_content(self) -> None:
        self._search_timer.stop()
        self.detail_panel.hide()
        self._usage.clear()
        self._notes.clear()
        self._atlas = MemoryAtlas()
        for widget in (self.search_input, self.app_combo, self.star_picker):
            widget.blockSignals(True)
            widget.clear()
            widget.blockSignals(False)
        self.stats_label.clear()
        self.status_label.clear()
        self.status_label.setToolTip("")
        self.status_label.setAccessibleDescription("")
        self.range_label.clear()
        self.detail_hint.clear()
        self.view.clear_private_content()
        self.detail_title.clear()
        self.detail_meta.clear()

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget#starMapPage, QGraphicsView#starCanvas { background: #070d1c; border: none; }
            QWidget#atlasHeading, QWidget#atlasFooter { background: transparent; }
            QWidget { color: #cdd7ea; }
            QLabel { background: transparent; }
            QLabel#atlasEyebrow { color: #a6b3cc; font-size: 10px; font-weight: 600; letter-spacing: 2px; }
            QLabel#atlasTitle { color: #f0f2fa; font-size: 27px; font-weight: 600; }
            QLabel#atlasMuted { color: #8c9bb7; font-size: 11px; background: transparent; }
            QLabel#atlasStats { color: #c6d0e3; font-size: 12px; }
            QFrame#atlasControls { background: rgba(12, 21, 39, 220); border: 1px solid #29344d; border-radius: 10px; }
            QComboBox, QDateEdit, QLineEdit { background: #111c31; color: #cbd6eb; border: 1px solid transparent; border-radius: 6px; padding: 5px 8px; font-size: 12px; min-height: 20px; }
            QComboBox:hover, QDateEdit:hover, QLineEdit:focus { border-color: #465575; }
            QComboBox::drop-down, QDateEdit::drop-down { border: none; width: 18px; }
            QComboBox QAbstractItemView { background: #142138; color: #d6e0f1; selection-background-color: #2a3b5b; border: 1px solid #334461; padding: 6px; }
            QCalendarWidget QWidget { background: #142138; color: #d6e0f1; }
            QCalendarWidget QAbstractItemView { background: #142138; color: #d6e0f1; selection-background-color: #2a3b5b; alternate-background-color: #1b2b43; }
            QPushButton#atlasTool { background: transparent; color: #c6d1e6; border: 1px solid transparent; border-radius: 6px; padding: 6px 10px; font-size: 12px; min-width: 16px; }
            QPushButton#atlasTool:hover, QPushButton#atlasTool:focus { background: #253451; border-color: #435372; }
            QFrame#atlasDetail { background: rgba(13, 23, 41, 245); border: 1px solid #33415c; border-radius: 14px; }
            QFrame#atlasDetail QLabel, QWidget#atlasSourceList, QScrollArea { background: transparent; }
            QLabel#atlasDetailTitle { color: #e7edf9; font-size: 19px; font-weight: 600; }
            QFrame#atlasSource { background: #14223a; border: 1px solid #253651; border-radius: 9px; }
            QFrame#atlasSource QLabel { font-size: 12px; color: #c8d4e8; }
            QLabel#atlasSourceTime { color: #b6a588; font-size: 10px; }
            QPushButton#atlasReplay { background: #26334a; color: #e1ccaa; border: 1px solid #3c4659; border-radius: 6px; padding: 7px 9px; font-size: 11px; text-align: left; }
            QPushButton#atlasReplay:hover, QPushButton#atlasReplay:focus { background: #36445d; }
            QPushButton#atlasClose { background: transparent; color: #a9b7cf; border: none; border-radius: 5px; font-size: 20px; padding: 0; min-width: 25px; min-height: 25px; }
            QPushButton#atlasClose:hover, QPushButton#atlasClose:focus { background: #2a3953; }
            QScrollBar:vertical { background: transparent; width: 5px; margin: 0; }
            QScrollBar::handle:vertical { background: #3c4b66; border-radius: 2px; min-height: 24px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)
