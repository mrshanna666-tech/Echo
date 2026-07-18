from __future__ import annotations

import os
import sys
from ctypes import byref, c_int, windll

from PySide6.QtCore import QEasingCurve, Property, QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QVBoxLayout,
)


def reduced_motion_enabled() -> bool:
    if os.environ.get("ECHO_REDUCE_MOTION", "").lower() in {"1", "true", "yes", "on"}:
        return True
    if sys.platform != "win32":
        return False
    try:
        animation_enabled = c_int(1)
        spi_get_client_area_animation = 0x1042
        ok = windll.user32.SystemParametersInfoW(
            spi_get_client_area_animation,
            0,
            byref(animation_enabled),
            0,
        )
        return bool(ok) and not bool(animation_enabled.value)
    except Exception:
        return False


class AnimatedNavButton(QPushButton):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._shift = 0.0
        self._shadow = None
        if sys.platform != "win32":
            self._shadow = QGraphicsDropShadowEffect(self)
            self._shadow.setBlurRadius(0)
            self._shadow.setOffset(0, 0)
            self._shadow.setColor(QColor(64, 48, 28, 0))
            self.setGraphicsEffect(self._shadow)
        self._shift_animation = QPropertyAnimation(self, b"shift", self)
        self._shift_animation.setDuration(160)
        self._shift_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QStylePainter(self)
        painter.translate(self._shift, 0)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if sys.platform != "win32" and not reduced_motion_enabled() and not self.isChecked():
            self._animate_shift(4)
            if self._shadow is not None:
                self._shadow.setBlurRadius(14)
                self._shadow.setOffset(0, 5)
                self._shadow.setColor(QColor(64, 48, 28, 26))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if sys.platform != "win32" and not reduced_motion_enabled():
            self._animate_shift(0)
        elif self._shift:
            self.set_shift(0)
        if self._shadow is not None:
            self._shadow.setBlurRadius(0)
            self._shadow.setOffset(0, 0)
            self._shadow.setColor(QColor(64, 48, 28, 0))
        super().leaveEvent(event)

    def _animate_shift(self, value: float) -> None:
        if sys.platform == "win32":
            self.set_shift(value)
            return
        self._shift_animation.stop()
        self._shift_animation.setStartValue(self._shift)
        self._shift_animation.setEndValue(value)
        self._shift_animation.start()

    def get_shift(self) -> float:
        return self._shift

    def set_shift(self, value: float) -> None:
        self._shift = value
        self.update()

    shift = Property(float, get_shift, set_shift)


class Sidebar(QFrame):
    page_selected = Signal(str)
    mood_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(210)
        self._buttons: dict[str, QPushButton] = {}
        self._pulse_on = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 24)
        layout.setSpacing(18)

        brand = QLabel("Echo Recorder")
        brand.setObjectName("brand")
        tagline = QLabel("今天的记忆首页")
        tagline.setObjectName("mutedSmall")
        layout.addWidget(brand)
        layout.addWidget(tagline)
        layout.addSpacing(10)

        for key, label in [
            ("today", "今天"),
            ("timeline", "时间线"),
            ("diary", "日报"),
            ("notes", "一句话"),
            ("memory", "Memory"),
            ("settings", "设置"),
        ]:
            button = AnimatedNavButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page_key=key: self.set_active(page_key))
            self._buttons[key] = button
            layout.addWidget(button)

        layout.addStretch()
        self.mood_button = AnimatedNavButton("📷  记录此刻")
        self.mood_button.setObjectName("moodButton")
        self.mood_button.clicked.connect(self.mood_requested.emit)
        layout.addWidget(self.mood_button)
        layout.addSpacing(18)

        local_row = QHBoxLayout()
        local_row.setContentsMargins(0, 0, 0, 0)
        local_row.setSpacing(7)
        self.local_dot = QLabel("●")
        self.local_dot.setObjectName("localDot")
        local = QLabel("本地记录中")
        local.setObjectName("localStatus")
        path = QLabel("data")
        path.setObjectName("mutedSmall")
        local_row.addWidget(self.local_dot)
        local_row.addWidget(local)
        local_row.addStretch()
        layout.addLayout(local_row)
        layout.addWidget(path)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(1200)
        self._pulse_timer.timeout.connect(self._toggle_local_pulse)
        if sys.platform != "win32" and not reduced_motion_enabled():
            self._pulse_timer.start()

        self.set_active("today", emit=False)

    def set_active(self, key: str, emit: bool = True) -> None:
        if key not in self._buttons:
            return
        for page_key, button in self._buttons.items():
            active = page_key == key
            button.setChecked(active)
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)
        if emit:
            self.page_selected.emit(key)

    def _toggle_local_pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        self.local_dot.setProperty("pulse", self._pulse_on)
        self.local_dot.style().unpolish(self.local_dot)
        self.local_dot.style().polish(self.local_dot)
