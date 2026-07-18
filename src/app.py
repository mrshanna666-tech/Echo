from __future__ import annotations

import logging
import os
import sys
import traceback
import ctypes
import shutil
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QLockFile, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QSystemTrayIcon

from src.config import (
    APP_NAME,
    DB_PATH,
    INSTANCE_LOCK_PATH,
    POLL_INTERVAL_MS,
    ensure_app_dirs,
)
from src.database.db import Database
from src.data_export import backup_database_connection, export_all_data
from src.demo_data import seed_demo_database
from src.i18n import tr
from src.openai_key_store import load_openai_api_key
from src.preferences import load_preferences
from src.recorder.activity_recorder import ActivityRecorder
from src.recorder.window_tracker import WindowTracker
from src.summary.ai_summary_generator import (
    build_preview,
    build_sanitized_payload,
    generate_ai_summary_from_payload,
)
from src.summary.local_summary_generator import SummaryResult
from src.summary.local_summary_generator import generate_summary_for_date, get_today_summary_path
from src.ui.main_window import MainWindow
from src.ui.note_dialog import NoteDialog
from src.ui.summary_mode_dialog import SummaryModeDialog
from src.ui.tray import TrayController
from src.utils.logging_setup import setup_logging
from src.utils.resources import echo_icon_path
from src.utils.time_utils import now, today_str, to_db_datetime


logger = logging.getLogger(__name__)


class SummaryWorker(QObject):
    finished = Signal(object)
    failed = Signal()

    def __init__(self, task: Callable[[], SummaryResult]) -> None:
        super().__init__()
        self._task = task

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self._task())
        except Exception:
            logger.exception("Background GPT-5.6 reflection failed.")
            self.failed.emit()


def _install_application_font(app: QApplication) -> None:
    """Choose an installed CJK font so Chinese text never falls back to tofu."""
    available = set(QFontDatabase.families())
    preferred = (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "DengXian",
        "Noto Sans CJK SC",
        "SimSun",
    )
    family = next((name for name in preferred if name in available), app.font().family())
    font = QFont(family)
    font.setPointSize(10)
    app.setFont(font)


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Echo.Recorder.Desktop"
        )
    except Exception:
        logger.exception("Failed to set Windows AppUserModelID.")


class EchoApp:
    def __init__(self) -> None:
        self.demo_mode = os.environ.get("ECHO_DEMO_MODE") == "1"
        ensure_app_dirs()
        setup_logging()
        logger.info("Echo Recorder starting.")

        _set_windows_app_user_model_id()
        self.qt_app = QApplication(sys.argv)
        self.qt_app.setApplicationName(APP_NAME)
        self.qt_app.setWindowIcon(QIcon(str(echo_icon_path())))
        _install_application_font(self.qt_app)
        self.qt_app.setQuitOnLastWindowClosed(False)

        self.instance_lock = QLockFile(str(INSTANCE_LOCK_PATH))
        if not self.instance_lock.tryLock(100):
            QMessageBox.information(
                None,
                APP_NAME,
                tr("Echo 已经在运行，请从系统托盘打开。", "Echo is already running. Open it from the system tray."),
            )
            raise SystemExit(0)

        self.database = Database(DB_PATH)
        self.database.initialize()
        if self.demo_mode:
            seed_demo_database(self.database)
        else:
            self.database.recover_unfinished_app_usage(end_time=to_db_datetime(now()))

        self.recorder = ActivityRecorder(self.database, WindowTracker())
        self.recorder.paused = self.demo_mode
        self.tray = TrayController()
        self.today_window: MainWindow | None = None
        self._recording_error_shown = False
        self._summary_thread: QThread | None = None
        self._summary_worker: SummaryWorker | None = None
        self._background_summary_date: str | None = None

        self.timer = QTimer()
        self.timer.setInterval(POLL_INTERVAL_MS)
        self.timer.timeout.connect(self._safe_tick)

        self.tray.show_today_requested.connect(self.show_today)
        self.tray.add_note_requested.connect(self.add_note)
        self.tray.generate_summary_requested.connect(self.generate_summary)
        self.tray.open_summary_requested.connect(self.open_summary)
        self.tray.pause_requested.connect(self.pause_recording)
        self.tray.resume_requested.connect(self.resume_recording)
        self.tray.quit_requested.connect(self.quit)

    def run(self) -> int:
        try:
            self.tray.show()
            if self.demo_mode:
                self.tray.set_paused(True)
                QTimer.singleShot(0, self.show_today)
            else:
                self.timer.start()
                self._safe_tick()
            logger.info("Echo Recorder started.")
            return self.qt_app.exec()
        except Exception:
            logger.exception("Application run failed.")
            return 1

    def show_today(self) -> None:
        try:
            self.recorder.refresh_current_duration()
            if self.today_window is None:
                self.today_window = MainWindow(self.database)
                self.today_window.generate_summary_requested.connect(self.generate_summary)
                self.today_window.generate_summary_for_date_requested.connect(self.generate_summary_for_date)
                self.today_window.open_summary_requested.connect(self.open_summary)
                self.today_window.add_note_requested.connect(self.add_note)
                self.today_window.export_requested.connect(self.export_data)
                self.today_window.clear_today_requested.connect(self.clear_today_records)
                self.today_window.language_change_requested.connect(self._rebuild_main_window)
            self.today_window.refresh()
            if self.demo_mode:
                self.today_window.setWindowTitle(
                    tr("Echo Recorder — 虚构数据演示", "Echo Recorder — Synthetic Demo")
                )
            self.today_window.show()
            self.today_window.raise_()
            self.today_window.activateWindow()
        except Exception:
            logger.exception("Failed to show today window.")

    def add_note(self) -> None:
        try:
            dialog = NoteDialog(self.today_window)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            content = dialog.content()
            if not content:
                return

            created_at = to_db_datetime(now())
            note_id = self.database.add_manual_note(
                date=today_str(), content=content, created_at=created_at
            )
            if note_id is None:
                logger.error("Manual note was not saved.")
                return
            logger.info("Manual note saved. id=%s", note_id)
            if self.today_window is not None:
                self.today_window.refresh()
            self.tray.tray.showMessage(
                APP_NAME,
                tr("这一句话已经留在今天。", "Your note was saved for today."),
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
        except Exception:
            logger.exception("Failed to add manual note.")

    def export_data(self) -> None:
        """Create a portable local archive containing records, reports and photos."""
        try:
            default_name = f"echo-export-{today_str()}.zip"
            target, _ = QFileDialog.getSaveFileName(
                self.today_window,
                tr("导出 Echo 数据", "Export Echo data"),
                str(DATA_DIR / default_name),
                tr("ZIP 文件 (*.zip)", "ZIP files (*.zip)"),
            )
            if not target:
                return
            output = export_all_data(self.database, Path(target))
            self._show_message(
                "Echo Recorder",
                tr(f"数据已导出到：\n{output}", f"Data exported to:\n{output}"),
                QSystemTrayIcon.MessageIcon.Information,
            )
        except Exception:
            logger.exception("Data export failed.")
            self._show_message("Echo Recorder", tr("导出失败，请查看日志。", "Export failed. Check the log."), QSystemTrayIcon.MessageIcon.Warning)

    def clear_today_records(self) -> None:
        """Back up, then remove today's database and diary records."""
        try:
            usage_count, note_count = self.database.count_records_by_date(today_str())
            mood_dir = DATA_DIR / "moods" / today_str()
            day_dir = DATA_DIR / today_str().replace("-", "/")
            if not usage_count and not note_count and not mood_dir.exists() and not day_dir.exists():
                QMessageBox.information(self.today_window, "Echo Recorder", tr("今天没有可清空的记录。", "There are no records to clear today."))
                return
            answer = QMessageBox.question(
                self.today_window,
                tr("确认清空今天的记录", "Clear today's records?"),
                tr(
                    f"将删除 {usage_count} 条应用记录、{note_count} 条手动记录，以及今天的照片和日报。\n\n删除前会自动备份数据库，是否继续？",
                    f"This will delete {usage_count} application records, {note_count} notes, and today's photos and reflection.\n\nEcho will back up the database first. Continue?",
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.recorder.reset_after_data_clear()
            backup = backup_database_connection(self.database, DB_PATH)
            self.database.delete_records_by_date(today_str())
            shutil.rmtree(mood_dir, ignore_errors=True)
            shutil.rmtree(day_dir, ignore_errors=True)
            if self.today_window is not None:
                self.today_window.refresh()
            self._show_message("Echo Recorder", tr(f"今天的记录已清空。\n备份：{backup}", f"Today's records were cleared.\nBackup: {backup}"), QSystemTrayIcon.MessageIcon.Information)
        except Exception:
            logger.exception("Clear today records failed.")
            self._show_message("Echo Recorder", tr("清空失败，原始数据仍会保留，请查看日志。", "Clear failed. Original data was preserved; check the log."), QSystemTrayIcon.MessageIcon.Warning)

    def generate_summary(self) -> None:
        self.generate_summary_for_date(today_str())

    def generate_summary_for_date(self, date_text: str) -> None:
        try:
            if self._summary_thread is not None and self._summary_thread.isRunning():
                QMessageBox.information(
                    self.today_window,
                    "Echo Recorder",
                    tr("GPT‑5.6 回顾正在后台生成。", "A GPT‑5.6 reflection is already running in the background."),
                )
                return
            self.recorder.refresh_current_duration()
            preferences = load_preferences()
            result = None
            used_ai = False
            if preferences.ai_enabled:
                app_usage = self.database.get_app_usage_by_date(date_text)
                manual_notes = self.database.get_manual_notes_by_date(date_text)
                payload = build_sanitized_payload(
                    date_text,
                    app_usage,
                    manual_notes,
                    preferences.ai_include_notes,
                )
                api_key = load_openai_api_key()
                dialog = SummaryModeDialog(
                    build_preview(payload, preferences.language),
                    ai_available=bool(api_key),
                    parent=self.today_window,
                )
                dialog.exec()
                if dialog.choice == SummaryModeDialog.CANCEL:
                    if self.today_window is not None:
                        self.today_window.set_summary_loading(False)
                    return
                if dialog.choice == SummaryModeDialog.AI:
                    self._start_ai_summary(
                        payload,
                        api_key=api_key,
                        language=preferences.language,
                    )
                    return
                else:
                    result = generate_summary_for_date(self.database, date_text)
            else:
                result = generate_summary_for_date(self.database, date_text)
            if result is None:
                if self.today_window is not None:
                    self.today_window.set_summary_result(False)
                self._show_message(
                    tr("日报生成失败", "Reflection failed"),
                    tr("日报生成失败，请查看日志。", "The reflection failed. Check the log."),
                    QSystemTrayIcon.MessageIcon.Warning,
                )
                return
            logger.info("Summary generated from UI action: %s", result.path)
            if self.today_window is not None:
                self.today_window.set_summary_result(True)
            self._show_message(
                "Echo Recorder",
                tr(
                    "GPT‑5.6 深度回顾已生成。" if used_ai else "本地日报已生成。",
                    "GPT‑5.6 reflection generated." if used_ai else "Local reflection generated.",
                ),
                QSystemTrayIcon.MessageIcon.Information,
            )
        except Exception:
            logger.exception("Generate summary action failed.")
            if self.today_window is not None:
                self.today_window.set_summary_result(False)
            self._show_message(
                tr("日报生成失败", "Reflection failed"),
                tr("日报生成失败，请查看日志。", "The reflection failed. Check the log."),
                QSystemTrayIcon.MessageIcon.Warning,
            )

    def _start_ai_summary(self, payload, *, api_key: str, language: str) -> None:
        self._background_summary_date = payload.date
        thread = QThread()
        worker = SummaryWorker(
            lambda: generate_ai_summary_from_payload(
                payload,
                api_key=api_key,
                language=language,
            )
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._ai_summary_finished)
        worker.failed.connect(self._ai_summary_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_summary_thread)
        self._summary_thread = thread
        self._summary_worker = worker
        thread.start()
        self._show_message(
            "Echo Recorder",
            tr(
                "GPT‑5.6 正在后台整理回顾，你可以继续使用 Echo。",
                "GPT‑5.6 is preparing the reflection in the background. You can keep using Echo.",
            ),
            QSystemTrayIcon.MessageIcon.Information,
        )

    @Slot(object)
    def _ai_summary_finished(self, result: SummaryResult) -> None:
        logger.info("GPT-5.6 reflection generated in background: %s", result.path)
        if self.today_window is not None:
            self.today_window.set_summary_result(True)
        self._show_message(
            "Echo Recorder",
            tr("GPT‑5.6 深度回顾已生成。", "GPT‑5.6 reflection generated."),
            QSystemTrayIcon.MessageIcon.Information,
        )

    @Slot()
    def _ai_summary_failed(self) -> None:
        date_text = self._background_summary_date
        result = generate_summary_for_date(self.database, date_text) if date_text else None
        if self.today_window is not None:
            self.today_window.set_summary_result(result is not None)
        QMessageBox.warning(
            self.today_window,
            "Echo Recorder",
            tr(
                "GPT‑5.6 暂时不可用，已改用完全本地总结；没有继续上传其他数据。",
                "GPT‑5.6 was unavailable, so Echo used the fully local summary. No additional data was sent.",
            ),
        )

    @Slot()
    def _clear_summary_thread(self) -> None:
        self._summary_thread = None
        self._summary_worker = None
        self._background_summary_date = None

    def open_summary(self) -> None:
        try:
            summary_path = get_today_summary_path()
            if not summary_path.exists():
                QMessageBox.information(
                    self.today_window,
                    "Echo Recorder",
                    tr("今天还没有生成日报，请先点击“生成今天日报”。", "Generate today's reflection before opening it."),
                )
                return
            if self.today_window is None:
                self.show_today()
            if self.today_window is not None:
                self.today_window.show_summary_detail(summary_path)
            else:
                os.startfile(str(summary_path))
            logger.info("Opened today summary: %s", summary_path)
        except Exception:
            logger.exception("Open summary action failed.")
            QMessageBox.warning(self.today_window, "Echo Recorder", tr("打开今天日报失败，请查看日志。", "Could not open today's reflection. Check the log."))

    def pause_recording(self) -> None:
        try:
            self.recorder.pause()
            self.tray.set_paused(True)
        except Exception:
            logger.exception("Pause action failed.")

    def resume_recording(self) -> None:
        try:
            self.recorder.resume()
            self.tray.set_paused(False)
        except Exception:
            logger.exception("Resume action failed.")

    def _rebuild_main_window(self) -> None:
        try:
            previous = self.today_window
            self.today_window = None
            if previous is not None:
                previous.hide()
                previous.deleteLater()
            self.tray.retranslate()
            QTimer.singleShot(0, self.show_today)
        except Exception:
            logger.exception("Failed to rebuild UI after language change.")

    def quit(self) -> None:
        logger.info("Echo Recorder exiting.")
        try:
            self.timer.stop()
        except Exception:
            logger.exception("Failed to stop timer.")
        try:
            self.recorder.shutdown()
            self.database.close()
            logger.info("Echo Recorder exited.")
        except Exception:
            logger.exception("Quit cleanup failed.")
        finally:
            self.qt_app.quit()

    def _safe_tick(self) -> None:
        try:
            self.recorder.tick()
        except Exception as exc:
            logger.exception("Activity recorder tick failed.")
            if not self._recording_error_shown:
                self._recording_error_shown = True
                self.tray.tray.showMessage(
                    APP_NAME,
                    tr(f"记录暂时遇到问题：{exc}", f"Recording encountered a problem: {exc}"),
                    QSystemTrayIcon.MessageIcon.Warning,
                    3000,
                )

    def _show_message(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon,
    ) -> None:
        try:
            self.tray.tray.showMessage(title, message, icon, 2500)
        except Exception:
            logger.exception("Failed to show tray message.")
            QMessageBox.information(self.today_window, title, message)


def _install_exception_hook() -> None:
    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        logger.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        message = "".join(traceback.format_exception_only(exc_type, exc_value)).strip()
        QMessageBox.critical(None, "Echo Recorder", tr(f"程序遇到错误：\n{message}", f"The application encountered an error:\n{message}"))

    sys.excepthook = handle_exception


def main() -> None:
    app = EchoApp()
    _install_exception_hook()
    sys.exit(app.run())
