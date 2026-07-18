from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtMultimedia import QCamera, QImageCapture, QMediaCaptureSession, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.mood.local_mood_journal import append_mood_entry, create_mood_image_path


logger = logging.getLogger(__name__)


class MoodDrawer(QFrame):
    closed = Signal()
    saved = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("moodDrawer")
        self.setFixedWidth(330)
        self._camera: QCamera | None = None
        self._image_capture: QImageCapture | None = None
        self._pending_image_path: Path | None = None
        self._capture_session = QMediaCaptureSession(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("记录此刻")
        title.setObjectName("drawerTitle")
        close_button = QPushButton("×")
        close_button.setObjectName("drawerCloseButton")
        close_button.setFixedSize(32, 28)
        close_button.clicked.connect(self.close_drawer)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_button)

        privacy = QLabel("摄像头只会在你主动记录时开启，照片仅保存在本地。关闭抽屉时会立即关闭摄像头。")
        privacy.setObjectName("moodPrivacy")
        privacy.setWordWrap(True)

        preview_label = QLabel("摄像头预览")
        preview_label.setObjectName("sectionLabel")

        self.preview_stack = QStackedWidget()
        self.preview_stack.setObjectName("cameraPreview")
        self.preview_stack.setFixedHeight(212)
        self.enable_camera_button = QPushButton("点击开启摄像头")
        self.enable_camera_button.setObjectName("cameraStartButton")
        self.enable_camera_button.clicked.connect(self.start_camera)
        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("cameraVideo")
        self.preview_stack.addWidget(self.enable_camera_button)
        self.preview_stack.addWidget(self.video_widget)

        mood_label = QLabel("心情标签")
        mood_label.setObjectName("sectionLabel")
        mood_row = QHBoxLayout()
        mood_row.setSpacing(8)
        self.mood_group = QButtonGroup(self)
        self.mood_group.setExclusive(True)
        for index, mood in enumerate(["开心", "平静", "低落", "疲惫", "焦虑"]):
            button = QPushButton(mood)
            button.setObjectName("moodPill")
            button.setCheckable(True)
            button.setMinimumHeight(28)
            self.mood_group.addButton(button)
            mood_row.addWidget(button)
            if index == 0:
                button.setChecked(True)
        mood_row.addStretch()

        note_label = QLabel("可选备注")
        note_label.setObjectName("sectionLabel")
        self.note_edit = QTextEdit()
        self.note_edit.setObjectName("moodNote")
        self.note_edit.setPlaceholderText("写一句此刻想留给未来自己的话……")
        self.note_edit.setFixedHeight(82)

        layout.addLayout(header)
        layout.addWidget(privacy)
        layout.addSpacing(6)
        layout.addWidget(preview_label)
        layout.addWidget(self.preview_stack)
        layout.addSpacing(12)
        layout.addWidget(mood_label)
        layout.addLayout(mood_row)
        layout.addSpacing(10)
        layout.addWidget(note_label)
        layout.addWidget(self.note_edit)
        layout.addStretch()

        self.status_label = QLabel("")
        self.status_label.setObjectName("moodStatus")
        self.status_label.setWordWrap(True)
        self.save_button = QPushButton("拍照保存")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setFixedHeight(36)
        self.save_button.clicked.connect(self.save_current_moment)
        layout.addWidget(self.status_label)
        layout.addWidget(self.save_button)

        self._apply_styles()

    def start_camera(self) -> None:
        try:
            if self._camera is not None:
                return
            devices = QMediaDevices.videoInputs()
            if not devices:
                self._show_status("无法访问摄像头，请检查系统权限。", error=True)
                return
            self._camera = QCamera(devices[0], self)
            self._camera.errorOccurred.connect(self._handle_camera_error)
            self._image_capture = QImageCapture(self)
            self._image_capture.imageSaved.connect(self._handle_image_saved)
            self._image_capture.errorOccurred.connect(self._handle_capture_error)
            self._capture_session.setCamera(self._camera)
            self._capture_session.setVideoOutput(self.video_widget)
            self._capture_session.setImageCapture(self._image_capture)
            self._camera.start()
            self.preview_stack.setCurrentWidget(self.video_widget)
            self._show_status("摄像头已开启。")
        except Exception:
            logger.exception("Failed to start camera.")
            self._show_status("无法访问摄像头，请检查系统权限。", error=True)
            self.stop_camera()

    def save_current_moment(self) -> None:
        try:
            if self._camera is None or self._image_capture is None:
                self._show_status("请先点击开启摄像头。", error=True)
                return
            self._pending_image_path = create_mood_image_path()
            self.save_button.setEnabled(False)
            self.save_button.setText("正在保存...")
            self._image_capture.captureToFile(str(self._pending_image_path))
        except Exception:
            logger.exception("Failed to capture mood image.")
            self._show_status("保存失败，请查看日志。", error=True)
            self.save_button.setEnabled(True)
            self.save_button.setText("拍照保存")

    def stop_camera(self) -> None:
        try:
            if self._camera is not None:
                self._camera.stop()
                self._capture_session.setCamera(None)
                self._camera.deleteLater()
                self._camera = None
            if self._image_capture is not None:
                self._capture_session.setImageCapture(None)
                self._image_capture.deleteLater()
                self._image_capture = None
            self._capture_session.setVideoOutput(None)
            self.preview_stack.setCurrentWidget(self.enable_camera_button)
        except Exception:
            logger.exception("Failed to stop camera.")

    def close_drawer(self) -> None:
        self.stop_camera()
        self.closed.emit()

    def reset_for_open(self) -> None:
        self.status_label.setText("")
        self.save_button.setEnabled(True)
        self.save_button.setText("拍照保存")
        self.preview_stack.setCurrentWidget(self.enable_camera_button)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.stop_camera()
        super().hideEvent(event)

    def _handle_image_saved(self, _id: int, file_name: str) -> None:
        try:
            image_path = Path(file_name)
            if self._pending_image_path is not None:
                image_path = self._pending_image_path
            selected = self.mood_group.checkedButton()
            mood = selected.text() if selected is not None else "平静"
            append_mood_entry(image_path, mood, self.note_edit.toPlainText())
            self.note_edit.clear()
            self._show_status("已记录此刻。")
            self.saved.emit(str(image_path))
        except Exception:
            logger.exception("Failed to save mood journal entry.")
            self._show_status("保存失败，请查看日志。", error=True)
        finally:
            self._pending_image_path = None
            self.save_button.setEnabled(True)
            self.save_button.setText("拍照保存")

    def _handle_camera_error(self, _error, error_string: str) -> None:
        logger.error("Camera error: %s", error_string)
        self._show_status("无法访问摄像头，请检查系统权限。", error=True)
        self.stop_camera()

    def _handle_capture_error(self, _id: int, _error, error_string: str) -> None:
        logger.error("Mood image capture error: %s", error_string)
        self._show_status("保存失败，请查看日志。", error=True)
        self.save_button.setEnabled(True)
        self.save_button.setText("拍照保存")

    def _show_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("error", error)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#moodDrawer {
                background: #fffaf3;
                border-left: 1px solid rgba(81, 117, 86, 55);
            }
            QLabel#drawerTitle {
                color: #2c2721;
                font-size: 22px;
                font-weight: 800;
            }
            QLabel#sectionLabel {
                color: #517556;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#moodPrivacy {
                background: #f8f2e6;
                color: #716555;
                border-radius: 12px;
                padding: 12px;
                line-height: 145%;
            }
            QStackedWidget#cameraPreview,
            QPushButton#cameraStartButton,
            QVideoWidget#cameraVideo {
                background: #f8f2e6;
                border: 1px solid rgba(193, 118, 64, 45);
                border-radius: 14px;
            }
            QPushButton#cameraStartButton {
                color: #716555;
                font-weight: 700;
            }
            QPushButton#moodPill {
                background: #f8f2e6;
                color: #716555;
                border: none;
                border-radius: 14px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton#moodPill:checked {
                background: #517556;
                color: white;
            }
            QTextEdit#moodNote {
                background: #f8f2e6;
                color: #2c2721;
                border: none;
                border-radius: 12px;
                padding: 12px;
            }
            QLabel#moodStatus {
                color: #517556;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#moodStatus[error="true"] {
                color: #c17640;
            }
            QPushButton#drawerCloseButton {
                background: #f8f2e6;
                color: #716555;
                border-radius: 14px;
                padding: 5px 10px;
                font-weight: 800;
            }
            QPushButton#drawerCloseButton:hover {
                background: #f8ddb1;
                color: #c17640;
            }
            QPushButton#primaryButton {
                background: #517556;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 8px 16px;
                font-weight: 700;
            }
            QPushButton#primaryButton:disabled {
                background: #d6e4cf;
                color: #517556;
            }
            """
        )
