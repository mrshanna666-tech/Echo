from __future__ import annotations

import hashlib
import math
import random
from html import escape

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QTransform
from PySide6.QtWidgets import QFrame, QGraphicsItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QSizePolicy

from src.i18n import tr
from src.memory_star_map import MemoryAtlas, MemoryStar
from src.ui.sidebar import reduced_motion_enabled


class MemoryStarItem(QGraphicsItem):
    """A small luminous core, with a screen-sized hit target and caption."""

    def __init__(self, star: MemoryStar, hover_changed) -> None:
        super().__init__()
        self.star = star
        self.hovered = False
        self._hover_changed = hover_changed
        self.detail_visible = False
        seed = int.from_bytes(hashlib.sha256(star.key.encode()).digest()[:4], "big")
        variation = random.Random(seed).random()
        self.radius = (3.7 + variation if star.kind == "app" else
                       2.6 if star.kind == "note" else 1.6 + variation * 1.1)
        self.color = QColor("#ffe3b5" if star.kind == "app" else
                            "#ffc77e" if star.kind == "note" else "#c4d9ff")
        self.setPos(*star.position)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(3 if star.kind == "app" else 2)
        title = (star.label if star.kind == "app" else star.label[5:] if star.kind == "day"
                 else tr("笔记 · ", "Note · ") + star.sources[0].date[5:])
        self.caption = QGraphicsSimpleTextItem(title[:23] + ("…" if len(title) > 23 else ""), self)
        font = QFont("Microsoft YaHei", 10 if star.kind == "app" else 8)
        font.setBold(star.kind == "app")
        self.caption.setFont(font)
        self.caption.setBrush(QColor("#e5e9f4" if star.kind == "app" else "#aebbd3"))
        self.caption.setPos(16, -12)
        self.caption.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.caption.setVisible(star.kind == "app")
        if star.kind == "app":
            days = len({source.date for source in star.sources})
            self.meta = QGraphicsSimpleTextItem(tr(f"{days} 天的足迹", f"{days} days of activity"), self)
            self.meta.setFont(QFont("Microsoft YaHei", 8))
            self.meta.setBrush(QColor("#8593af"))
            self.meta.setPos(16, 8)
            self.meta.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        tooltip = tr("手动笔记", "Manual note") if star.kind == "note" else star.app_name
        self.setToolTip("<qt>" + escape(f"{tooltip}\n{star.label[:160]}\n" +
                                      tr("点击查看来源", "Click to see sources")).replace("\n", "<br>") + "</qt>")

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-44, -44, 88, 88)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(QPointF(), 12, 12)
        return path

    def update_caption(self, detail_visible: bool) -> None:
        self.detail_visible = detail_visible
        self.caption.setVisible(self.star.kind == "app" or self.hovered or self.isSelected() or
                                (detail_visible and self.star.kind == "day"))

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isSelected() or self.hovered
        spread = 40 if self.star.kind == "app" else 26 if active else 20
        glow = QRadialGradient(0, 0, spread)
        r, g, b = self.color.red(), self.color.green(), self.color.blue()
        glow.setColorAt(0, QColor(r, g, b, 175 if active else 120))
        glow.setColorAt(0.15, QColor(r, g, b, 80 if active else 44))
        glow.setColorAt(0.5, QColor(r, g, b, 18 if active else 9))
        glow.setColorAt(1, QColor(r, g, b, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(), spread, spread)
        if self.star.kind == "app" or active:
            # Fine diffraction rays leave the core luminous, never hollow.
            length = 20 if self.star.kind == "app" else 12
            for dx, dy in ((length, 0), (0, length * 0.7)):
                ray = QLinearGradient(-dx, -dy, dx, dy)
                ray.setColorAt(0, QColor(r, g, b, 0))
                ray.setColorAt(0.5, QColor(r, g, b, 150))
                ray.setColorAt(1, QColor(r, g, b, 0))
                painter.setPen(QPen(ray, 0.8))
                painter.drawLine(QPointF(-dx, -dy), QPointF(dx, dy))
        core = QRadialGradient(0, 0, self.radius * 1.8)
        core.setColorAt(0, QColor("#ffffff"))
        core.setColorAt(0.35, QColor("#fff9ee"))
        core.setColorAt(0.7, self.color)
        core.setColorAt(1, QColor(r, g, b, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(core)
        painter.drawEllipse(QPointF(), self.radius * 1.8, self.radius * 1.8)
        if active:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(r, g, b, 100), 0.75))
            painter.drawArc(QRectF(-12, -12, 24, 24), 25 * 16, 100 * 16)
            painter.drawArc(QRectF(-12, -12, 24, 24), 205 * 16, 100 * 16)

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        self.hovered = True
        self.update_caption(self.detail_visible)
        self._hover_changed(self.star.key)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        self.hovered = False
        self.update_caption(self.detail_visible)
        self._hover_changed("")
        self.update()
        super().hoverLeaveEvent(event)


class StarMapView(QGraphicsView):
    star_selected = Signal(str)
    star_activated = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("starCanvas")
        self.setAccessibleName(tr("记忆星图画布", "Memory atlas canvas"))
        self.setAccessibleDescription(tr(
            "拖动探索，滚轮缩放，方向键选择星点。星点列表也可以选择记忆。",
            "Drag to explore, scroll to zoom, or use arrow keys or the star list to select memories.",
        ))
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumSize(290, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._items: dict[str, MemoryStarItem] = {}
        self._edges = []
        self._fit_scale = 1.0
        self._was_shown = False
        self._content_bounds = QRectF(-400, -240, 800, 480)
        self._sky = QPixmap()
        self._press_position = None
        self._hover_key = ""
        self.atlas = MemoryAtlas()
        self._flight = QVariantAnimation(self)
        self._flight.setDuration(380)
        self._flight.setStartValue(0.0)
        self._flight.setEndValue(1.0)
        self._flight.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._flight.valueChanged.connect(self._animate_camera)
        self.scene().selectionChanged.connect(self._selection_changed)

    def set_atlas(self, atlas: MemoryAtlas) -> None:
        self._flight.stop()
        selected = self.selected_key()
        same_positions = {star.key: star.position for star in atlas.stars} == {
            star.key: star.position for star in self.atlas.stars}
        self.scene().blockSignals(True)
        self._items.clear()
        self._edges.clear()
        self._hover_key = ""
        self.scene().clear()
        self.atlas = atlas
        positions = {star.key: QPointF(*star.position) for star in atlas.stars}
        for link in atlas.links:
            path = QPainterPath(positions[link.source])
            path.lineTo(positions[link.target])
            item = self.scene().addPath(path)
            item.setZValue(-1)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._edges.append((item, link))
        for star in atlas.stars:
            item = MemoryStarItem(star, self._hover_changed)
            self.scene().addItem(item)
            self._items[star.key] = item
        if atlas.stars:
            xs, ys = zip(*(star.position for star in atlas.stars))
            self._content_bounds = QRectF(min(xs) - 65, min(ys) - 45,
                                         max(max(xs) - min(xs), 220) + 190,
                                         max(max(ys) - min(ys), 140) + 100)
        else:
            self._content_bounds = QRectF(-400, -240, 800, 480)
        self.scene().setSceneRect(self._content_bounds.adjusted(-2200, -1600, 2200, 1600))
        if selected in self._items:
            self._items[selected].setSelected(True)
        self.scene().blockSignals(False)
        if not same_positions:
            self.fit_all()
        self._selection_changed()
        self.viewport().update()

    def selected_key(self) -> str:
        return next((item.star.key for item in self.scene().selectedItems()
                     if isinstance(item, MemoryStarItem)), "")

    def clear_private_content(self) -> None:
        self._flight.stop()
        self.set_atlas(MemoryAtlas())

    def select_star(self, key: str, *, reveal: bool = False) -> None:
        if key not in self._items:
            return
        if self._items[key].isSelected():
            if reveal:
                self.star_activated.emit(key)
            return
        self.scene().blockSignals(True)
        self.scene().clearSelection()
        self._items[key].setSelected(True)
        self.scene().blockSignals(False)
        self._selection_changed()
        if reveal:
            self.star_activated.emit(key)

    def _selection_changed(self) -> None:
        self._style_edges()
        self._update_captions()
        self.star_selected.emit(self.selected_key())

    def _hover_changed(self, key: str) -> None:
        self._hover_key = key
        self._style_edges()

    def _style_edges(self) -> None:
        key = self._hover_key or self.selected_key()
        for item, link in self._edges:
            active = key in (link.source, link.target)
            color = QColor("#e8bc7f" if link.kind == "nearby" else "#9bb9eb")
            color.setAlpha(150 if active else 45 if link.kind == "chronology" else 20)
            pen = QPen(color, 1.0 if active else 0.7)
            pen.setCosmetic(True)
            if link.kind == "nearby":
                pen.setStyle(Qt.PenStyle.DotLine)
            item.setPen(pen)

    def _update_captions(self) -> None:
        # Local density matters more than the relative overview zoom level.
        detailed = self.transform().m11() >= 1.35
        for item in self._items.values():
            item.update_caption(detailed)
        self._place_captions()

    def _place_captions(self) -> None:
        # Captions keep their pixel size during zoom. Choose their side in
        # screen space so a neighboring star does not sit inside an app name.
        occupied = []
        centers = {key: QPointF(self.mapFromScene(item.pos())) for key, item in self._items.items()}
        viewport = QRectF(self.viewport().rect()).adjusted(16, 16, -16, -16)
        items = sorted(self._items.values(), key=lambda item: item.star.kind != "app")
        for item in items:
            if not item.caption.isVisible():
                continue
            meta = getattr(item, "meta", None)
            width = max(item.caption.boundingRect().width(), meta.boundingRect().width() if meta else 0)
            height = 38 if meta else item.caption.boundingRect().height()
            center = centers[item.star.key]
            candidates = ((16, -12), (-width - 16, -12), (-width / 2, 19), (-width / 2, -height - 18))
            def penalty(offset):
                box = QRectF(center.x() + offset[0], center.y() + offset[1], width, height)
                score = 10000 if not viewport.contains(box) else 0
                for key, point in centers.items():
                    if key != item.star.key and box.adjusted(-8, -6, 8, 6).contains(point):
                        score += 500
                for other in occupied:
                    overlap = box.intersected(other)
                    score += overlap.width() * overlap.height()
                return score
            x, y = min(candidates, key=penalty)
            item.caption.setPos(x, y)
            if meta:
                meta.setPos(x, y + 21)
            occupied.append(QRectF(center.x() + x, center.y() + y, width, height).adjusted(-6, -4, 6, 4))

    def fit_all(self) -> None:
        self._flight.stop()
        width, height = self.viewport().width(), self.viewport().height()
        available = QRectF(55, 170, max(180, width - 110), max(160, height - 255))
        bounds = self._content_bounds
        scale = min(available.width() / bounds.width(), available.height() / bounds.height(), 1.35)
        self.setTransform(QTransform.fromScale(scale, scale))
        viewport_center = QPointF(width / 2, height / 2)
        self.centerOn(bounds.center() + (viewport_center - available.center()) / scale)
        self._fit_scale = scale
        self._update_captions()

    def focus_star(self, key: str, right_inset: int = 0) -> None:
        if key not in self._items:
            return
        self._flight.stop()
        current = self.transform().m11()
        scale = max(current, min(1.7, self._fit_scale * 1.6))
        center = self._items[key].pos() + QPointF(right_inset / (2 * scale), -35 / scale)
        self._flight_start = (self.mapToScene(self.viewport().rect().center()), current)
        self._flight_end = (center, scale)
        if reduced_motion_enabled() or not self.isVisible():
            self._animate_camera(1.0)
        else:
            self._flight.start()

    def _animate_camera(self, progress) -> None:
        start, scale0 = self._flight_start
        end, scale1 = self._flight_end
        scale = scale0 + (scale1 - scale0) * float(progress)
        self.setTransform(QTransform.fromScale(scale, scale))
        self.centerOn(start + (end - start) * float(progress))
        self._update_captions()

    def zoom_by(self, factor: float, *, at_mouse: bool = False) -> None:
        self._flight.stop()
        current = self.transform().m11()
        target = max(self._fit_scale * 0.65, min(current * factor, max(3, self._fit_scale * 2)))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse if at_mouse
                                     else QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.scale(target / current, target / current)
        self._update_captions()

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta:
            self.zoom_by(1.18 if delta > 0 else 1 / 1.18, at_mouse=True)
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._flight.stop()
        self._press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if (event.button() == Qt.MouseButton.LeftButton and self._press_position is not None and
                (event.position().toPoint() - self._press_position).manhattanLength() < 6):
            item = self.itemAt(event.position().toPoint())
            while item is not None and not isinstance(item, MemoryStarItem):
                item = item.parentItem()
            if isinstance(item, MemoryStarItem):
                self.select_star(item.star.key, reveal=True)
        self._press_position = None

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus):
            self.zoom_by(1 / 1.25 if event.key() == Qt.Key.Key_Minus else 1.25)
        elif event.key() == Qt.Key.Key_Home:
            self.fit_all()
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down) and self._items:
            keys = list(self._items)
            selected = self.selected_key()
            direction = -1 if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up) else 1
            index = keys.index(selected) if selected else (-1 if direction == 1 else 0)
            self.select_star(keys[(index + direction) % len(keys)], reveal=True)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._was_shown:
            self._was_shown = True
            QTimer.singleShot(0, self.fit_all)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._flight.stop()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_fit_scale"):
            self._sky = QPixmap()
            if math.isclose(self.transform().m11(), self._fit_scale, rel_tol=0.02):
                self.fit_all()

    def _paint_sky(self) -> None:
        size = self.viewport().size()
        self._sky = QPixmap(size)
        self._sky.fill(QColor("#070d1c"))
        painter = QPainter(self._sky)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = size.width(), size.height()
        # Cached translucent nebula layers, painted once per viewport size.
        for x, y, rx, ry, color in (
            (0.35, 0.52, 0.65, 0.42, QColor(25, 45, 88, 95)),
            (0.68, 0.47, 0.45, 0.40, QColor(51, 32, 79, 65)),
            (0.46, 0.75, 0.48, 0.20, QColor(25, 61, 89, 65)),
            (0.21, 0.32, 0.30, 0.25, QColor(24, 48, 80, 55)),
        ):
            painter.save()
            painter.translate(w * x, h * y)
            painter.scale(w * rx, h * ry)
            cloud = QRadialGradient(0, 0, 1)
            cloud.setColorAt(0, color)
            cloud.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(cloud)
            painter.drawEllipse(QPointF(), 1, 1)
            painter.restore()
        rng = random.Random(127)
        for _ in range(max(300, w * h // 1200)):
            x, y = rng.random() * w, rng.random() * h
            radius = rng.choices((0.45, 0.65, 0.9, 1.15), (45, 35, 17, 3))[0]
            alpha = rng.randint(35, 125)
            color = QColor(191, 208, 241, alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            if radius > 1:
                glow = QRadialGradient(x, y, 5)
                glow.setColorAt(0, QColor(169, 195, 255, 50))
                glow.setColorAt(1, QColor(169, 195, 255, 0))
                painter.setBrush(glow)
                painter.drawEllipse(QPointF(x, y), 5, 5)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, y), radius, radius)
        # Keep controls legible while the lower sky remains unobstructed.
        shade = QLinearGradient(0, 0, 0, h)
        shade.setColorAt(0, QColor(3, 7, 17, 165))
        shade.setColorAt(0.25, QColor(3, 7, 17, 0))
        shade.setColorAt(0.8, QColor(3, 7, 17, 0))
        shade.setColorAt(1, QColor(3, 7, 17, 120))
        painter.fillRect(self._sky.rect(), shade)
        painter.end()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        if self._sky.isNull() or self._sky.size() != self.viewport().size():
            self._paint_sky()
        painter.save()
        painter.resetTransform()
        painter.drawPixmap(0, 0, self._sky)
        if not self.atlas.stars:
            painter.setPen(QColor("#b8c6df"))
            painter.setFont(QFont("Microsoft YaHei", 13))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                             tr("这里还没有星点\n换个日期或筛选，寻找留下的足迹。",
                                "No stars here yet\nTry another date or filter to find your traces."))
        painter.restore()
