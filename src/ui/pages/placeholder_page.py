from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class PlaceholderPage(QWidget):
    def __init__(self, title: str, copy: str) -> None:
        super().__init__()
        self.setObjectName("content")
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 34)
        root.setSpacing(18)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        label = QLabel(title)
        label.setObjectName("pageTitle")
        label.setWordWrap(True)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 26, 28, 26)
        card_layout.setSpacing(10)

        body = QLabel(copy)
        body.setObjectName("storyBody")
        body.setWordWrap(True)

        card_layout.addWidget(body)
        root.addWidget(label)
        root.addWidget(card)
        root.addStretch()
