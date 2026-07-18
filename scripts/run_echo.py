import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer

from src.app import EchoApp, _install_exception_hook


if __name__ == "__main__":
    app = EchoApp()
    _install_exception_hook()
    QTimer.singleShot(0, app.show_today)
    raise SystemExit(app.run())
