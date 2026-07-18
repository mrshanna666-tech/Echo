from __future__ import annotations

import logging
import ctypes
from dataclasses import dataclass

try:
    import win32con
    import win32gui
    import win32process
    import win32api
except ImportError:  # pragma: no cover - handled at runtime in the UI
    win32con = None
    win32gui = None
    win32process = None
    win32api = None


logger = logging.getLogger(__name__)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


@dataclass(frozen=True)
class WindowInfo:
    app_name: str
    window_title: str
    process_id: int

    @property
    def identity(self) -> tuple[str, str, int]:
        return (self.app_name, self.window_title, self.process_id)


class WindowTracker:
    def get_foreground_window(self) -> WindowInfo | None:
        from src.preferences import load_preferences

        preferences = load_preferences()
        if self._idle_seconds() >= preferences.idle_minutes * 60:
            return None
        if win32con is None or win32gui is None or win32process is None or win32api is None:
            logger.error("pywin32 is required to track foreground windows.")
            return WindowInfo(app_name="Unknown", window_title="", process_id=0)

        try:
            hwnd = win32gui.GetForegroundWindow()
        except Exception:
            logger.exception("Failed to get foreground window handle.")
            return WindowInfo(app_name="Unknown", window_title="", process_id=0)

        if not hwnd:
            return None

        title = ""
        process_id = 0
        try:
            title = win32gui.GetWindowText(hwnd).strip()
        except Exception:
            logger.exception("Failed to get foreground window title.")
            return WindowInfo(app_name="Unknown", window_title="", process_id=0)

        try:
            _, process_id = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            logger.exception("Failed to get foreground window process id.")

        app_name = self._get_process_name(process_id) if process_id else "Unknown"
        info = WindowInfo(
            app_name=app_name or "Unknown",
            window_title=title or "",
            process_id=process_id,
        )
        haystack = f"{info.app_name} {info.window_title}".lower()
        if any(keyword in haystack for keyword in preferences.excluded_keywords):
            logger.info("Excluded foreground window by privacy rule: app=%s", info.app_name)
            return None
        return info

    def _idle_seconds(self) -> float:
        if not hasattr(ctypes, "windll"):
            return 0
        try:
            info = LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(info)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return 0
            elapsed_ms = ctypes.windll.kernel32.GetTickCount() - info.dwTime
            return max(elapsed_ms, 0) / 1000
        except Exception:
            logger.exception("Failed to read system idle time.")
            return 0

    def _get_process_name(self, process_id: int) -> str:
        handle = None
        try:
            access = win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ
            handle = win32api.OpenProcess(access, False, process_id)
            path = win32process.GetModuleFileNameEx(handle, 0)
            return path.rsplit("\\", 1)[-1].removesuffix(".exe")
        except Exception:
            logger.exception("Failed to get process name. process_id=%s", process_id)
            return "Unknown"
        finally:
            if handle:
                win32api.CloseHandle(handle)
