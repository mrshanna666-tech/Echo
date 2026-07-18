from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from src.database.db import Database
from src.database.models import ManualNote
from src.i18n import tr
from src.utils.time_utils import display_time, today_str


logger = logging.getLogger(__name__)


class NotesPage(QWidget):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.setObjectName("content")

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 34)
        root.setSpacing(18)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel(tr("一句话", "Notes"))
        title.setObjectName("pageTitle")
        subtitle = QLabel(tr("这里会保存你主动留下的关键句子。", "The notes you choose to leave are kept here."))
        subtitle.setObjectName("storyBody")
        subtitle.setWordWrap(True)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 22, 24, 22)
        card_layout.setSpacing(12)

        section = QLabel(tr("今天留下的句子", "Today's notes"))
        section.setObjectName("sectionLabel")
        self.notes_box = QVBoxLayout()
        self.notes_box.setSpacing(10)

        card_layout.addWidget(section)
        card_layout.addLayout(self.notes_box)
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(card)
        root.addStretch()

    def refresh(self) -> None:
        try:
            notes = self.database.get_manual_notes_by_date(today_str())
            self._render_notes(notes)
        except Exception:
            logger.exception("Failed to refresh notes page.")

    def _render_notes(self, notes: list[ManualNote]) -> None:
        self._clear_layout(self.notes_box)
        if not notes:
            empty = QLabel(tr("今天还没有留下主动记录。", "You have not left a note today."))
            empty.setObjectName("storyBody")
            self.notes_box.addWidget(empty)
            return
        for note in notes:
            row = QLabel(f"{display_time(note.created_at)}  {note.content}")
            row.setObjectName("timelineTitle")
            row.setWordWrap(True)
            self.notes_box.addWidget(row)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
