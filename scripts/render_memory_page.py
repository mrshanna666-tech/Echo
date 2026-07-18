"""Render the real Memory page for visual regression checks."""

import os
import sys
from pathlib import Path

if os.environ.get("ECHO_OFFSCREEN") == "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from src.config import DB_PATH
from src.database.db import Database
from src.ui.today_window import TodayWindow


def main() -> None:
    app = QApplication([])
    database = Database(DB_PATH)
    window = TodayWindow(database)
    window.resize(1440, 900)
    window.sidebar.set_active("memory", emit=False)
    window.stack.setCurrentWidget(window.memory_scroll)
    window.detail_panel.hide()
    window.detail_panel.setGraphicsEffect(None)
    window.drawer_overlay.hide()
    window.mood_drawer.hide()
    window.mood_overlay.hide()
    window.show()
    app.processEvents()
    # Rendering a visible QWidget into a second painter can invalidate its
    # backing store on Windows. Keep the interactive drag-test window clean.
    if "--hold" not in sys.argv:
        output = Path(__file__).resolve().parent.parent / "memory_replay_implementation.bmp"
        image = QImage(window.size(), QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        window.render(painter, QPoint())
        painter.end()
        if not image.save(str(output)):
            raise RuntimeError(f"Failed to save render to {output}")
    QTimer.singleShot(60_000 if "--hold" in sys.argv else 0, app.quit)
    app.exec()
    database.close()


if __name__ == "__main__":
    main()
