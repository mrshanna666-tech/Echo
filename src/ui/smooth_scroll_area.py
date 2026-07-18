from __future__ import annotations

import sys

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt
from PySide6.QtWidgets import QFrame, QScrollArea

from src.ui.sidebar import reduced_motion_enabled


class SmoothScrollArea(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self._target_value = 0
        self._shadow_height = 18
        self._scroll_animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_animation.setDuration(170)
        self._scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.verticalScrollBar().setSingleStep(28)
        self.viewport().installEventFilter(self)

        self._top_shadow = QFrame(self.viewport())
        self._top_shadow.setObjectName("scrollTopShadow")
        self._top_shadow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._bottom_shadow = QFrame(self.viewport())
        self._bottom_shadow.setObjectName("scrollBottomShadow")
        self._bottom_shadow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.verticalScrollBar().valueChanged.connect(self._update_scroll_shadows)
        self.verticalScrollBar().rangeChanged.connect(self._update_scroll_shadows)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt override
        if watched is self.viewport() and event.type() == QEvent.Type.Wheel:
            return self._handle_wheel(event)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._layout_scroll_shadows()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._layout_scroll_shadows()
        self._update_scroll_shadows()

    def _handle_wheel(self, event) -> bool:
        bar = self.verticalScrollBar()
        if bar.maximum() <= 0:
            return False

        pixel_delta = event.pixelDelta().y()
        if pixel_delta:
            delta = -pixel_delta
        else:
            delta = int(-(event.angleDelta().y() / 120) * 92)
        if delta == 0:
            return False

        base = self._target_value if self._scroll_animation.state() == QPropertyAnimation.State.Running else bar.value()
        self._target_value = max(bar.minimum(), min(bar.maximum(), base + delta))

        if sys.platform == "win32" or reduced_motion_enabled():
            bar.setValue(self._target_value)
        else:
            self._scroll_animation.stop()
            self._scroll_animation.setStartValue(bar.value())
            self._scroll_animation.setEndValue(self._target_value)
            self._scroll_animation.start()
        event.accept()
        return True

    def _layout_scroll_shadows(self) -> None:
        width = self.viewport().width()
        height = self.viewport().height()
        self._top_shadow.setGeometry(0, 0, width, self._shadow_height)
        self._bottom_shadow.setGeometry(0, max(0, height - self._shadow_height), width, self._shadow_height)
        self._top_shadow.raise_()
        self._bottom_shadow.raise_()
        self._update_scroll_shadows()

    def _update_scroll_shadows(self) -> None:
        bar = self.verticalScrollBar()
        has_scroll = bar.maximum() > 0
        self._top_shadow.setVisible(has_scroll and bar.value() > bar.minimum())
        self._bottom_shadow.setVisible(has_scroll and bar.value() < bar.maximum())
