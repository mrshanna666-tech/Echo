from __future__ import annotations

import logging
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from src.config import APP_NAME, DATA_DIR
from src.utils.resources import echo_icon_path


logger = logging.getLogger(__name__)


class TrayController(QObject):
    show_today_requested = Signal()
    add_note_requested = Signal()
    generate_summary_requested = Signal()
    open_summary_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.tray = QSystemTrayIcon()
        self.tray.setToolTip("Echo 正在记录...")
        self.tray.setIcon(self._default_icon())

        self.menu = QMenu()
        self.show_today_action = QAction("查看今天")
        self.add_note_action = QAction("添加一句话")
        self.generate_summary_action = QAction("生成今天日报")
        self.open_summary_action = QAction("打开今天日报")
        self.pause_action = QAction("暂停记录")
        self.resume_action = QAction("恢复记录")
        self.open_data_action = QAction("打开数据文件夹")
        self.quit_action = QAction("退出")

        self.menu.addAction(self.show_today_action)
        self.menu.addAction(self.add_note_action)
        self.menu.addAction(self.generate_summary_action)
        self.menu.addAction(self.open_summary_action)
        self.menu.addSeparator()
        self.menu.addAction(self.pause_action)
        self.menu.addAction(self.resume_action)
        self.menu.addSeparator()
        self.menu.addAction(self.open_data_action)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.resume_action.setVisible(False)

        self.show_today_action.triggered.connect(self.show_today_requested.emit)
        self.add_note_action.triggered.connect(self.add_note_requested.emit)
        self.generate_summary_action.triggered.connect(self.generate_summary_requested.emit)
        self.open_summary_action.triggered.connect(self.open_summary_requested.emit)
        self.pause_action.triggered.connect(self.pause_requested.emit)
        self.resume_action.triggered.connect(self.resume_requested.emit)
        self.open_data_action.triggered.connect(self.open_data_folder)
        self.quit_action.triggered.connect(self.quit_requested.emit)
        self.tray.activated.connect(self._on_activated)

    def show(self) -> None:
        try:
            self.tray.show()
            self.tray.showMessage(
                APP_NAME,
                "Echo 正在后台安静记录。",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
        except Exception:
            logger.exception("Failed to show tray icon.")

    def set_paused(self, paused: bool) -> None:
        try:
            if paused:
                self.tray.setToolTip("Echo 已暂停记录")
                self.pause_action.setVisible(False)
                self.resume_action.setVisible(True)
            else:
                self.tray.setToolTip("Echo 正在记录...")
                self.pause_action.setVisible(True)
                self.resume_action.setVisible(False)
        except Exception:
            logger.exception("Failed to update tray paused state.")

    def open_data_folder(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(DATA_DIR))
            logger.info("Opened data folder: %s", DATA_DIR)
        except Exception:
            logger.exception("Failed to open data folder.")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        try:
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                self.show_today_requested.emit()
        except Exception:
            logger.exception("Failed to handle tray activation.")

    def _default_icon(self) -> QIcon:
        icon = QIcon(str(echo_icon_path()))
        if not icon.isNull():
            return icon
        app = QApplication.instance()
        if app is None:
            return QIcon()
        return app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
