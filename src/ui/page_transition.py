"""Short native snapshot transitions without effects on OpenGL widgets.

Snapshots are transient UI state: never persisted and explicitly purged on lock.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRect, Qt, QVariantAnimation
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget


class PageTransitionOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")
        self._snapshot = QPixmap()
        self._opacity = 1.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(360)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._animation.valueChanged.connect(self._advance)
        self._animation.finished.connect(self.clear)
        self.hide()

    def prepare(self, snapshot: QPixmap) -> None:
        self.clear()
        self._snapshot = snapshot
        self._opacity = 1.0
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.repaint()

    def fade_out(self) -> None:
        if not self._snapshot.isNull():
            self._animation.start()

    def _advance(self, value) -> None:
        self._opacity = 1.0 - float(value)
        self.update()

    def clear(self) -> None:
        self._animation.stop()
        self._snapshot = QPixmap()
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._snapshot.isNull():
            return
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(self.rect(), self._snapshot)
        painter.end()


class ChromeRevealOverlay(QWidget):
    """Reveal snapshots, then restore live controls with their original visibility."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")
        self._layers: list[tuple[QWidget, QPixmap, QRect]] = []
        self._progress = 0.0
        self.hide()

    @property
    def active(self) -> bool:
        return bool(self._layers)

    def prepare(self, widgets: tuple[QWidget, ...]) -> None:
        self.clear()
        self._layers = [(widget, widget.grab(), QRect(widget.geometry()))
                        for widget in widgets if not widget.isHidden()]
        for widget, _, _ in self._layers:
            widget.hide()
        self._progress = 0.0
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()

    def advance(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def clear(self) -> None:
        layers, self._layers = self._layers, []
        for widget, _, _ in layers:
            widget.show()
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        for index, (_, pixmap, geometry) in enumerate(self._layers):
            # Headings emerge first; the navigation dock follows a little later.
            delay = 0.18 + min(index, 3) * 0.045
            t = max(0.0, min(1.0, (self._progress - delay) / 0.58))
            t = t * t * (3 - 2 * t)
            painter.setOpacity(t)
            painter.drawPixmap(geometry.translated(0, round((1 - t) * 7)), pixmap)
        painter.end()
