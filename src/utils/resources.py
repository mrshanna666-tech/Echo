from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative_path: str) -> Path:
    """Resolve a bundled resource for source runs and PyInstaller builds."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    root = Path(bundle_root) if bundle_root else Path(__file__).resolve().parents[2]
    return root / relative_path


def echo_icon_path() -> Path:
    return resource_path("assets/icons/echo.ico")
