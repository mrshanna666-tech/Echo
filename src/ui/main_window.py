from __future__ import annotations

from src.ui.today_window import TodayWindow


class MainWindow(TodayWindow):
    """Main Echo desktop window.

    TodayWindow remains as the app-facing name for compatibility with the
    current tray wiring. New code can import MainWindow.
    """
