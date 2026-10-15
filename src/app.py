from __future__ import annotations

import logging
import os
import sys
import traceback
import ctypes
import shutil
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QLockFile, QObject, QStandardPaths, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QLineEdit, QMessageBox, QSystemTrayIcon

from src.config import (
    APP_NAME,
    DATA_DIR,
    DB_PATH,
    INSTANCE_LOCK_PATH,
    POLL_INTERVAL_MS,
    ensure_app_dirs,
)
from src.database.db import Database, migrate_plaintext_database
from src.data_export import backup_database_connection, decrypt_portable_export, export_all_data
from src.demo_data import seed_demo_database
from src.i18n import tr
from src.openai_key_store import load_openai_api_key
from src.preferences import load_preferences
from src.recorder.activity_recorder import ActivityRecorder
from src.recorder.window_tracker import WindowTracker
from src.security import SecurityError, get_security_manager
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

        self.security = get_security_manager()
        if self.security.enabled:
            self.security.unlock()
        database_key = self.security.database_key() if self.security.enabled else None
        self.database = Database(DB_PATH, database_key)
        if not self.database.is_open:
            raise SecurityError("Echo could not unlock the local database.")
        self.database.initialize()
        if self.demo_mode:
            seed_demo_database(self.database)
        else:
            self.database.recover_unfinished_app_usage(end_time=to_db_datetime(now()))

        self.window_tracker = WindowTracker()
        self.recorder = ActivityRecorder(self.database, self.window_tracker)
        self.recorder.paused = self.demo_mode
        self.tray = TrayController()
        self.today_window: MainWindow | None = None
        self._recording_error_shown = False
        self._summary_thread: QThread | None = None
        self._summary_worker: SummaryWorker | None = None
        self._background_summary_date: str | None = None
        self._locked_previous_paused = self.recorder.paused

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
            if not self.security.locked:
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
                self.today_window.enable_data_protection_requested.connect(self.enable_data_protection)
                self.today_window.lock_data_requested.connect(self.lock_data)
                self.today_window.unlock_data_requested.connect(self.unlock_data)
                self.today_window.recovery_key_requested.connect(self.save_recovery_key)
                self.today_window.recover_data_requested.connect(self.recover_data)
                self.today_window.encrypted_export_requested.connect(self.export_encrypted_data)
                self.today_window.decrypt_export_requested.connect(self.decrypt_export_file)
            self.today_window.set_security_state(
                self.security.enabled,
                self.security.locked,
                demo=self.demo_mode,
            )
            if not self.security.locked:
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

    def enable_data_protection(self) -> None:
        if self.demo_mode or self.security.enabled:
            return
        answer = QMessageBox.question(
            self.today_window,
            tr("启用数据保护？", "Enable data protection?"),
            tr(
                "Echo 将先备份数据库，再加密数据库、搜索索引、照片、日记和日报。主密钥由当前 Windows 用户保护；迁移期间会暂停记录。此操作不能在设置中直接撤销。",
                "Echo will back up first, then encrypt the database, search index, photos, journals, and reflections. The current Windows account protects the master key, and recording pauses during migration. This cannot be undone from Settings.",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        previous_paused = self.recorder.paused
        backup: Path | None = None
        database_migrated = False
        try:
            self.recorder.pause()
            self.timer.stop()
            backup = backup_database_connection(self.database, DB_PATH)
            self.security.provision()
            database_key = self.security.database_key()
            self.database.close()
            migrate_plaintext_database(DB_PATH, database_key)
            database_migrated = True
            self.database.set_encryption_key(database_key)
            self.database.reopen()
            self.database.initialize()
            self.security.activate()
            migrated = self.security.migrate_attachments()
            if backup.exists():
                backup = self.security.encrypt_file(backup)
            logger.info("Data protection enabled; migrated %s attachments.", len(migrated))
            self._locked_previous_paused = previous_paused
            if not previous_paused:
                self.recorder.resume()
            self.timer.start()
            if self.today_window is not None:
                self.today_window.set_security_state(True, False)
                self.today_window.refresh()
            save_recovery = QMessageBox.question(
                self.today_window,
                tr("数据保护已启用", "Data protection enabled"),
                tr(
                    f"数据库和本地附件已加密。迁移备份：\n{backup}\n\n现在保存离线恢复密钥吗？",
                    f"The database and local attachments are encrypted. Migration backup:\n{backup}\n\nSave an offline recovery key now?",
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if save_recovery == QMessageBox.StandardButton.Yes:
                self.save_recovery_key(confirmed=True)
        except Exception:
            logger.exception("Failed to enable data protection.")
            if database_migrated:
                try:
                    if not self.database.is_open:
                        self.database.set_encryption_key(self.security.database_key())
                        self.database.reopen()
                    self.security.activate()
                except Exception:
                    logger.exception("Encrypted database recovery after migration failed.")
            else:
                self.security.abort_provision()
                self.database.close()
                self.database.set_encryption_key(None)
                self.database.reopen()
            if not previous_paused:
                self.recorder.resume()
            self.timer.start()
            QMessageBox.critical(
                self.today_window,
                tr("启用失败", "Could not enable protection"),
                tr("迁移没有完成。原始数据库或迁移备份仍保留，请查看日志。", "Migration did not complete. The original database or migration backup is still available; check the log."),
            )

    def lock_data(self, auto: bool = False) -> None:
        if not self.security.enabled or self.security.locked:
            return
        try:
            self._locked_previous_paused = self.recorder.paused
            self.recorder.pause()
            self.timer.stop()
            self.database.close()
            self.security.lock()
            self.tray.set_paused(True)
            self._discard_main_window()
            self.show_today()
            if auto:
                self._show_message(
                    "Echo Recorder",
                    tr("离开时间较长，数据已自动锁定。", "Your data was locked automatically while you were away."),
                    QSystemTrayIcon.MessageIcon.Information,
                )
        except Exception:
            logger.exception("Failed to lock protected data.")

    def unlock_data(self) -> None:
        if not self.security.enabled or not self.security.locked:
            return
        try:
            self.security.unlock()
            self.database.set_encryption_key(self.security.database_key())
            self.database.reopen()
            self.database.initialize()
            self._finish_unlock()
        except Exception:
            logger.exception("Failed to unlock protected data.")
            QMessageBox.critical(self.today_window, "Echo Recorder", tr("无法解锁数据，请查看日志。", "Could not unlock the data. Check the log."))

    def recover_data(self) -> None:
        if not self.security.enabled or not self.security.locked:
            return
        recovery_key, accepted = QInputDialog.getMultiLineText(
            self.today_window,
            tr("使用恢复密钥", "Use recovery key"),
            tr("粘贴完整的 Echo 恢复密钥：", "Paste the complete Echo recovery key:"),
        )
        if not accepted or not recovery_key.strip():
            return
        try:
            self.security.use_recovery_key(recovery_key)
            self.database.close()
            self.database.set_encryption_key(self.security.database_key())
            self.database.reopen()
            self.database.initialize()
            self.security.persist_recovered_key()
            self._finish_unlock()
            QMessageBox.information(self.today_window, "Echo Recorder", tr("恢复密钥验证成功，已为当前 Windows 用户重新保护主密钥。", "Recovery succeeded. The master key is now protected for the current Windows user."))
        except Exception:
            logger.exception("Recovery key unlock failed.")
            self.database.close()
            self.security.lock()
            QMessageBox.critical(self.today_window, "Echo Recorder", tr("恢复密钥无效或与此数据库不匹配。", "The recovery key is invalid or does not match this database."))

    def _finish_unlock(self) -> None:
        if not self._locked_previous_paused:
            self.recorder.resume()
            self.tray.set_paused(False)
        else:
            self.tray.set_paused(True)
        if not self.demo_mode:
            self.timer.start()
        self._discard_main_window()
        self.show_today()

    def _discard_main_window(self) -> None:
        previous = self.today_window
        self.today_window = None
        if previous is not None:
            previous.purge_sensitive_content()
            previous.hide()
            previous.deleteLater()

    def save_recovery_key(self, confirmed: bool = False) -> None:
        if not self.security.enabled or self.security.locked:
            return
        if not confirmed:
            answer = QMessageBox.question(
                self.today_window,
                tr("保存恢复密钥？", "Save recovery key?"),
                tr("任何获得此密钥的人都可以解密你的 Echo 数据。请保存到离线、安全的位置，并且不要发送到聊天或邮件。", "Anyone with this key can decrypt your Echo data. Store it offline in a secure place and do not send it through chat or email."),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        target, _ = QFileDialog.getSaveFileName(
            self.today_window,
            tr("保存 Echo 恢复密钥", "Save Echo recovery key"),
            str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)) / "echo-recovery-key.txt"),
            tr("文本文件 (*.txt)", "Text files (*.txt)"),
        )
        if not target:
            return
        try:
            Path(target).write_text(
                "Echo Recorder recovery key\n\n" + self.security.recovery_key() + "\n",
                encoding="utf-8",
            )
            QMessageBox.information(self.today_window, "Echo Recorder", tr("恢复密钥已保存。请确认备份后关闭此文件。", "Recovery key saved. Verify the backup, then close the file."))
        except Exception:
            logger.exception("Could not save recovery key.")
            QMessageBox.warning(self.today_window, "Echo Recorder", tr("恢复密钥保存失败。", "Could not save the recovery key."))

    def add_note(self) -> None:
        if not self._require_unlocked():
            return
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
        if not self._require_unlocked():
            return
        try:
            if self.security.enabled:
                answer = QMessageBox.question(
                    self.today_window,
                    tr("导出可读副本？", "Export a readable copy?"),
                    tr(
                        "为便于迁移，ZIP 中的记录和附件会解密为可读文件。请将导出文件保存在安全位置。继续吗？",
                        "For portability, records and attachments in the ZIP are decrypted into readable files. Store the export securely. Continue?",
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
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

    def export_encrypted_data(self) -> None:
        if not self._require_unlocked():
            return
        password, accepted = QInputDialog.getText(
            self.today_window,
            tr("密码加密导出", "Password-encrypted export"),
            tr("设置导出密码（至少 10 个字符）：", "Set an export password (at least 10 characters):"),
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        confirmation, accepted = QInputDialog.getText(
            self.today_window,
            tr("确认导出密码", "Confirm export password"),
            tr("再次输入密码：", "Enter the password again:"),
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        if len(password) < 10 or password != confirmation:
            QMessageBox.warning(self.today_window, "Echo Recorder", tr("密码不足 10 个字符，或两次输入不一致。", "The password is shorter than 10 characters or the entries do not match."))
            return
        target, _ = QFileDialog.getSaveFileName(
            self.today_window,
            tr("导出加密 Echo 数据", "Export encrypted Echo data"),
            str(DATA_DIR / f"echo-export-{today_str()}.echoexport"),
            tr("Echo 加密导出 (*.echoexport)", "Echo encrypted export (*.echoexport)"),
        )
        if not target:
            return
        try:
            output = export_all_data(self.database, Path(target), password=password)
            self._show_message("Echo Recorder", tr(f"加密导出已保存到：\n{output}", f"Encrypted export saved to:\n{output}"), QSystemTrayIcon.MessageIcon.Information)
        except Exception:
            logger.exception("Password-encrypted export failed.")
            QMessageBox.warning(self.today_window, "Echo Recorder", tr("加密导出失败，请查看日志。", "Encrypted export failed. Check the log."))

    def decrypt_export_file(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self.today_window,
            tr("选择 Echo 加密导出", "Choose an Echo encrypted export"),
            "",
            tr("Echo 加密导出 (*.echoexport)", "Echo encrypted export (*.echoexport)"),
        )
        if not source:
            return
        password, accepted = QInputDialog.getText(
            self.today_window,
            tr("解密导出文件", "Decrypt export file"),
            tr("输入导出密码：", "Enter the export password:"),
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        target, _ = QFileDialog.getSaveFileName(
            self.today_window,
            tr("保存可读 ZIP", "Save readable ZIP"),
            str(Path(source).with_suffix(".zip")),
            tr("ZIP 文件 (*.zip)", "ZIP files (*.zip)"),
        )
        if not target:
            return
        try:
            output = decrypt_portable_export(Path(source), Path(target), password)
            QMessageBox.information(self.today_window, "Echo Recorder", tr(f"导出文件已解密到：\n{output}", f"Export decrypted to:\n{output}"))
        except Exception:
            logger.exception("Could not decrypt portable export.")
            QMessageBox.critical(self.today_window, "Echo Recorder", tr("密码错误，或导出文件已损坏。", "The password is incorrect or the export is damaged."))

    def clear_today_records(self) -> None:
        """Back up, then remove today's database and diary records."""
        if not self._require_unlocked():
            return
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
        if not self._require_unlocked():
            return
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
                using_local_ai = preferences.ai_provider == "local"
                dialog = SummaryModeDialog(
                    build_preview(payload, preferences.language, provider=preferences.ai_provider),
                    ai_available=bool(preferences.local_ai_model) if using_local_ai else bool(api_key),
                    ai_is_local=using_local_ai,
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
                        provider=preferences.ai_provider,
                        local_base_url=preferences.local_ai_base_url,
                        local_model=preferences.local_ai_model,
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

    def _start_ai_summary(
        self,
        payload,
        *,
        api_key: str,
        language: str,
        provider: str = "openai",
        local_base_url: str = "",
        local_model: str = "",
    ) -> None:
        self._background_summary_date = payload.date
        thread = QThread()
        worker = SummaryWorker(
            lambda: generate_ai_summary_from_payload(
                payload,
                api_key=api_key,
                language=language,
                provider=provider,
                local_base_url=local_base_url,
                local_model=local_model,
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
        if self.security.locked:
            logger.info("Discarded background reflection UI result because data is locked.")
            return
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
        if self.security.locked:
            logger.info("Skipped local reflection fallback because data is locked.")
            return
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
        if not self._require_unlocked():
            return
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
        if not self._require_unlocked():
            return
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
            preferences = load_preferences()
            if (
                self.security.enabled
                and not self.security.locked
                and preferences.auto_lock_enabled
                and self.window_tracker.idle_seconds() >= preferences.auto_lock_minutes * 60
            ):
                self.lock_data(auto=True)
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

    def _require_unlocked(self) -> bool:
        if not self.security.locked:
            return True
        self.show_today()
        QMessageBox.information(
            self.today_window,
            tr("数据已锁定", "Data locked"),
            tr("请先在设置中解锁数据。", "Unlock your data in Settings first."),
        )
        return False

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
