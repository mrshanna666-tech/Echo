from __future__ import annotations

import logging
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from src.config import APP_NAME, DATA_DIR
from src.i18n import tr
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
        self.tray.setToolTip(tr("Echo 正在记录...", "Echo is recording..."))
        self.tray.setIcon(self._default_icon())

        self.menu = QMenu()
        self.show_today_action = QAction(tr("查看今天", "Open Today"))
        self.add_note_action = QAction(tr("添加一句话", "Add a note"))
        self.generate_summary_action = QAction(tr("生成今天日报", "Generate today's reflection"))
        self.open_summary_action = QAction(tr("打开今天日报", "Open today's reflection"))
        self.pause_action = QAction(tr("暂停记录", "Pause recording"))
        self.resume_action = QAction(tr("恢复记录", "Resume recording"))
        self.open_data_action = QAction(tr("打开数据文件夹", "Open data folder"))
        self.quit_action = QAction(tr("退出", "Quit"))

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

    def retranslate(self) -> None:
        self.show_today_action.setText(tr("查看今天", "Open Today"))
        self.add_note_action.setText(tr("添加一句话", "Add a note"))
        self.generate_summary_action.setText(tr("生成今天日报", "Generate today's reflection"))
        self.open_summary_action.setText(tr("打开今天日报", "Open today's reflection"))
        self.pause_action.setText(tr("暂停记录", "Pause recording"))
        self.resume_action.setText(tr("恢复记录", "Resume recording"))
        self.open_data_action.setText(tr("打开数据文件夹", "Open data folder"))
        self.quit_action.setText(tr("退出", "Quit"))
        self.tray.setToolTip(tr("Echo 正在记录...", "Echo is recording..."))

    def show(self) -> None:
        try:
            self.tray.show()
            self.tray.showMessage(
                APP_NAME,
                tr("Echo 正在后台安静记录。", "Echo is recording quietly in the background."),
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
        except Exception:
            logger.exception("Failed to show tray icon.")

    def set_paused(self, paused: bool) -> None:
        try:
            if paused:
                self.tray.setToolTip(tr("Echo 已暂停记录", "Echo recording is paused"))
                self.pause_action.setVisible(False)
                self.resume_action.setVisible(True)
            else:
                self.tray.setToolTip(tr("Echo 正在记录...", "Echo is recording..."))
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
