from __future__ import annotations

import math
import os
import random
import time
from dataclasses import replace

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QSizePolicy, QToolTip, QWidget

from src.i18n import tr
from src.memory_space import SpaceCamera, add, camera_between, constellation_positions, dot, scale, seed
from src.memory_star_map import MemoryAtlas
from src.ui.sidebar import reduced_motion_enabled


class _SpaceAnnotations(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setObjectName("atlasSpaceAnnotations")
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        self.owner.paint_annotations(painter)
        painter.end()


class StarMapView(QWidget):
    star_selected = Signal(str)
    star_activated = Signal(str)
    activity = Signal()
    entry_progress = Signal(float)
    entry_finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("starCanvas")
        self.setAccessibleName(tr("三维记忆星图", "3D memory universe"))
        self.setAccessibleDescription(tr(
            "拖动旋转视角，右键或 Shift 拖动平移，滚轮缩放。方向键或星点列表选择记忆。",
            "Drag to orbit, right-drag or Shift-drag to pan, scroll to zoom. Arrow keys or the star list select memories.",
        ))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(290, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.camera = SpaceCamera()
        self.atlas = MemoryAtlas()
        self.world_positions = {}
        self._selected = ""
        self._hovered = ""
        self._press = None
        self._last_position = None
        self._dragging = False
        self._fit_distance = self.camera.distance
        self._overview = True
        self._roaming = True
        self.minimal_labels = False
        self._last_activity = time.monotonic()
        self._last_frame = time.monotonic()
        self._sprites = {}
        self._clouds = {}
        self.ambient_particles = self._make_ambient()
        self._flight = QVariantAnimation(self)
        self._flight.setDuration(850)
        self._flight.setStartValue(0.0)
        self._flight.setEndValue(1.0)
        # camera_between eases the entire pose; keep the animation clock linear.
        self._flight.setEasingCurve(QEasingCurve.Type.Linear)
        self._flight.valueChanged.connect(self._animate_camera)
        self._flight.finished.connect(self._finish_flight)
        self._flight_start = self._flight_end = None
        self._flight_returns_home = False
        self._entry_active = False
        self._entry_opacity = 1.0
        self._initial_fit = QTimer(self)
        self._initial_fit.setSingleShot(True)
        self._initial_fit.timeout.connect(self._fit_if_overview)
        self._drift = QTimer(self)
        self._drift.setInterval(33)
        self._drift.timeout.connect(self._drift_frame)
        self._gl = None
        # Headless Qt has no OpenGL window surface. The fallback shares the
        # exact same 3D camera, positions, picking, and interaction semantics.
        if QApplication.platformName() != "offscreen" and os.environ.get("ECHO_ATLAS_RENDERER") != "software":
            from src.ui.pages.star_map_gl import StarGLSurface
            self._gl = StarGLSurface(self)
        self._annotations = _SpaceAnnotations(self)

    @staticmethod
    def _make_ambient():
        rng = random.Random(8024)
        points = []
        # A three-dimensional galaxy ribbon, with a dark central dust lane.
        for _ in range(5400):
            t = rng.uniform(-1.0, 1.0)
            x = t * 2200
            y = math.sin(t * 2.0) * 150 + rng.gauss(0, 78 + abs(t) * 75)
            z = math.cos(t * 2.4) * 340 + rng.gauss(0, 190)
            warmth = rng.random()
            color = (0.55 + warmth * 0.30, 0.66 + warmth * 0.13, 1.0)
            points.append((x, y, z, *color, rng.uniform(0.18, 0.65), rng.uniform(2, 7), 0.0, rng.random()))
        # Far stars fill a sphere around the navigable memory volume.
        for _ in range(1600):
            theta, v, radius = rng.uniform(0, math.tau), rng.uniform(-1, 1), rng.uniform(3200, 7600)
            u = math.sqrt(1 - v * v)
            points.append((math.cos(theta) * u * radius, v * radius, math.sin(theta) * u * radius,
                           0.76, 0.83, 1.0, rng.uniform(0.25, 0.85), rng.uniform(6, 18), 0.0, rng.random()))
        # Wisps overlap in depth. Their shader adds deterministic turbulent
        # structure; they carry no memory data or invented associations.
        for _ in range(170):
            t = rng.uniform(-1.15, 1.15)
            x = t * 1700
            y = math.sin(t * 2) * 210 + rng.gauss(0, 160)
            z = math.cos(t * 2.4) * 280 + rng.gauss(0, 230)
            violet = rng.random() > 0.56
            color = (0.35, 0.27, 0.74) if violet else (0.15, 0.39, 0.76)
            points.append((x, y, z, *color, rng.uniform(0.045, 0.11), rng.uniform(300, 750), 2.0, rng.random()))
        # Blend clouds first, then the brighter stars.
        return sorted(points, key=lambda p: -p[8])

    def use_software_renderer(self) -> None:
        if self._gl:
            self._gl.hide()
            self._gl.deleteLater()
            self._gl = None
        self.update()

    def _render(self, *, geometry=False) -> None:
        self._annotations.update()
        if self._gl:
            if geometry:
                self._gl.invalidate()
            else:
                self._gl.update()
        else:
            self.update()

    def viewport(self):
        return self

    def set_atlas(self, atlas: MemoryAtlas) -> None:
        positions = constellation_positions(atlas)
        changed = positions != self.world_positions
        if changed:
            self._stop_flight()
        self.atlas = atlas
        self.world_positions = positions
        self._hovered = ""
        if self._selected not in positions:
            self._selected = ""
        if changed:
            self.fit_all()
        self.star_selected.emit(self._selected)
        self._render(geometry=True)
        self._sync_drift()

    def clear_private_content(self) -> None:
        self._initial_fit.stop()
        self._stop_flight()
        self._flight_start = self._flight_end = None
        self._flight_returns_home = False
        self._drift.stop()
        QToolTip.hideText()
        self._selected = self._hovered = ""
        self.world_positions.clear()
        self.atlas = MemoryAtlas()
        if self._gl:
            self._gl.clear_memory_geometry()
        self.star_selected.emit("")
        self._render(geometry=True)
        self.repaint()

    def selected_key(self) -> str:
        return self._selected

    def select_star(self, key: str, *, reveal=False) -> None:
        if key not in self.world_positions:
            return
        if self._selected != key:
            self._selected = key
            self._hovered = ""
            self.star_selected.emit(key)
            self._render(geometry=True)
        self._sync_drift()
        if reveal:
            self.star_activated.emit(key)

    def clear_selection(self) -> None:
        self._selected = self._hovered = ""
        self.star_selected.emit("")
        self._render(geometry=True)
        self._sync_drift()

    def project_star(self, key: str) -> QPointF | None:
        point = self.camera.project(self.world_positions[key], self.width(), self.height()) if key in self.world_positions else None
        return QPointF(point[0], point[1]) if point else None

    def _projector(self):
        eye, right, up, forward = self.camera.basis()
        focal = self.camera.focal(self.height())
        w, h = self.width() / 2, self.height() / 2
        def project(position):
            relative = (position[0] - eye[0], position[1] - eye[1], position[2] - eye[2])
            depth = dot(relative, forward)
            if depth <= 12 or depth >= 20000:
                return None
            return w + dot(relative, right) * focal / depth, h - dot(relative, up) * focal / depth, depth
        return project

    def _pick(self, point: QPointF) -> str:
        hits = []
        for key, position in self.world_positions.items():
            projected = self.camera.project(position, self.width(), self.height())
            if projected:
                distance = math.hypot(projected[0] - point.x(), projected[1] - point.y())
                if distance < 15:
                    hits.append((distance, projected[2], key))
        return min(hits)[2] if hits else ""

    def _overview_camera(self) -> SpaceCamera:
        camera = SpaceCamera()
        values = list(self.world_positions.values()) or [(-350, -200, -150), (350, 200, 150)]
        camera.target = tuple((min(p[i] for p in values) + max(p[i] for p in values)) / 2 for i in range(3))
        _, right, up, forward = camera.basis()
        focal = camera.focal(max(300, self.height()))
        width, height = max(140, self.width() / 2 - 110), max(100, self.height() / 2 - 115)
        required = []
        for p in values:
            relative = add(p, scale(camera.target, -1))
            required.append(max(abs(dot(relative, right)) * focal / width,
                                abs(dot(relative, up)) * focal / height) - dot(relative, forward))
        camera.distance = max(680, max(required) * 1.12)
        return camera

    def fit_all(self, *, animated: bool = False) -> None:
        destination = self._overview_camera()
        self._fit_distance = destination.distance
        # Longer journeys get breathing room, including a turn back from the
        # far side of the universe. Startup and layout fitting stay immediate.
        turn = abs(math.remainder(destination.yaw - self.camera.yaw, math.tau))
        zoom = abs(math.log(destination.distance / self.camera.distance))
        travel = math.dist(self.camera.target, destination.target) / max(destination.distance, 1)
        duration = round(min(2200, 1250 + turn * 230 + zoom * 200 + travel * 200))
        self._start_flight(destination, duration=duration, animated=animated, overview=True)

    def focus_star(self, key: str, right_inset: int = 0) -> None:
        if key not in self.world_positions:
            return
        self._stop_flight()
        distance = max(420, min(self.camera.distance, self._fit_distance * 0.60))
        _, right, up, _ = self.camera.basis()
        offset = add(scale(right, right_inset * distance / (2 * self.camera.focal(self.height()))),
                     scale(up, 15 * distance / self.camera.focal(self.height())))
        target = add(self.world_positions[key], offset)
        self._start_flight(replace(self.camera, target=target, distance=distance), duration=850)

    def enter_space(self) -> bool:
        if reduced_motion_enabled() or not self.isVisible():
            return False
        self._initial_fit.stop()
        self._stop_flight()
        destination = replace(self.camera)
        overview = self._overview
        # Keep the remembered destination, including an explored constellation.
        # The outgoing-page overlay conceals this initial, wider camera pose.
        self.camera.distance = min(destination.distance * 1.27, 12000)
        self.camera.yaw -= 0.075
        self.camera.pitch = min(1.38, self.camera.pitch + 0.035)
        self._last_activity = time.monotonic()
        self._start_flight(destination, duration=1150, overview=overview, entering=True)
        return True

    def cancel_entry(self) -> None:
        if self._entry_active:
            self._stop_flight()

    def _stop_flight(self) -> None:
        self._flight.stop()
        if self._entry_active:
            self._entry_active = False
            self._entry_opacity = 1.0
            self.entry_finished.emit()
            self._render()

    def _start_flight(self, destination: SpaceCamera, *, duration: int,
                      animated: bool = True, overview: bool = False, entering: bool = False) -> None:
        # Capture the actual in-flight pose when a previous trip is interrupted.
        # Reconfiguring QVariantAnimation must not emit its previous value and
        # briefly move the camera back to an earlier journey's starting point.
        self._stop_flight()
        self._flight_start = replace(self.camera)
        self._flight_end = destination
        self._flight_returns_home = overview
        self._overview = False
        self._entry_active = entering
        if entering:
            self._entry_opacity = 0.0
            self.entry_progress.emit(0.0)
        self._flight.blockSignals(True)
        self._flight.setDuration(duration)
        self._flight.setCurrentTime(0)
        self._flight.blockSignals(False)
        if not animated or reduced_motion_enabled() or not self.isVisible():
            self._animate_camera(1.0)
            self._finish_flight()
        else:
            self._flight.start()

    def _animate_camera(self, progress) -> None:
        if self._flight_start is None or self._flight_end is None:
            return
        pose = camera_between(self._flight_start, self._flight_end, float(progress))
        self.camera.target, self.camera.distance = pose.target, pose.distance
        self.camera.yaw, self.camera.pitch = pose.yaw, pose.pitch
        self.camera.fov = pose.fov
        if self._entry_active:
            self._entry_opacity = max(0.0, min(1.0, (float(progress) - 0.2) / 0.65))
            self.entry_progress.emit(float(progress))
        self._render()

    def _finish_flight(self) -> None:
        self._overview = self._flight_returns_home
        if self._entry_active:
            self._entry_active = False
            self._entry_opacity = 1.0
            self.entry_finished.emit()
            self._render()

    def zoom_by(self, factor: float, **_kwargs) -> None:
        self._stop_flight()
        self.camera.distance = max(170, min(self.camera.distance / factor, self._fit_distance * 3))
        self._overview = False
        self._interacted()
        self._render()

    def set_roaming(self, enabled: bool) -> None:
        self._roaming = enabled
        self._sync_drift()

    def _sync_drift(self) -> None:
        active = self.isVisible() and self._roaming and not reduced_motion_enabled() and bool(self.world_positions) and not self._selected
        if active and not self._drift.isActive():
            self._last_frame = time.monotonic()
            self._drift.start()
        elif not active:
            self._drift.stop()

    def _drift_frame(self) -> None:
        now = time.monotonic()
        dt = min(0.1, now - self._last_frame)
        self._last_frame = now
        if now - self._last_activity > 3 and not self._dragging and self._flight.state() == QAbstractAnimation.State.Stopped:
            self.camera.yaw += dt * 0.014
            self._render()

    def _interacted(self) -> None:
        self._last_activity = time.monotonic()
        self.activity.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._stop_flight()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._press = self._last_position = event.position()
        self._dragging = False
        self._interacted()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._interacted()
        if self._press is not None and self._last_position is not None:
            delta = event.position() - self._last_position
            self._last_position = event.position()
            if (event.position() - self._press).manhattanLength() > 4:
                self._dragging = True
            if self._dragging:
                if event.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton) or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.camera.pan(delta.x(), delta.y(), self.height())
                else:
                    self.camera.orbit(-delta.x(), -delta.y())
                self._overview = False
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._render()
        else:
            key = self._pick(event.position())
            if key != self._hovered:
                self._hovered = key
                self.setCursor(Qt.CursorShape.PointingHandCursor if key else Qt.CursorShape.OpenHandCursor)
                self._render(geometry=True)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if not self._dragging and event.button() == Qt.MouseButton.LeftButton:
            key = self._pick(event.position())
            if key:
                self.select_star(key, reveal=True)
            else:
                self._selected = ""
                self.star_selected.emit("")
                self._render(geometry=True)
                self._sync_drift()
        self._press = self._last_position = None
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hovered:
            self._hovered = ""
            self._render(geometry=True)
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta:
            self.zoom_by(1.15 if delta > 0 else 1 / 1.15)
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus):
            self.zoom_by(1 / 1.25 if key == Qt.Key.Key_Minus else 1.25)
        elif key == Qt.Key.Key_Home:
            self.fit_all(animated=True)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down) and self.world_positions:
            keys = list(self.world_positions)
            direction = -1 if key in (Qt.Key.Key_Left, Qt.Key.Key_Up) else 1
            index = keys.index(self._selected) if self._selected else (-1 if direction == 1 else 0)
            self.select_star(keys[(index + direction) % len(keys)], reveal=True)
        else:
            super().keyPressEvent(event)
            return
        self._interacted()
        event.accept()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_drift()
        if self._overview:
            self._initial_fit.start(0)
        if self._gl:
            QTimer.singleShot(600, self._check_gl)

    def _check_gl(self) -> None:
        if self._gl and not self._gl.isValid():
            self.use_software_renderer()

    def _fit_if_overview(self) -> None:
        if self._overview and self._flight.state() == QAbstractAnimation.State.Stopped:
            self.fit_all()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._initial_fit.stop()
        self._stop_flight()
        self._drift.stop()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._gl:
            self._gl.setGeometry(self.rect())
        self._annotations.setGeometry(self.rect())
        self._annotations.raise_()
        if self._overview:
            self.fit_all()

    def memory_particles(self):
        particles = []
        selected = self._hovered or self._selected
        adjacent = {link.source if link.target == selected else link.target
                    for link in self.atlas.links if selected in (link.source, link.target)}
        for star in self.atlas.stars:
            app, note = star.kind == "app", star.kind == "note"
            color = (1.0, 0.83, 0.59) if app else (1.0, 0.61, 0.29) if note else (0.57, 0.78, 1.0)
            opacity = 1.0 if not selected or star.key in adjacent or star.key == selected or app else 0.38
            diameter = 115 if app else 66 if note else 42 + seed(star.key) * 18
            if star.key == selected:
                diameter *= 1.35
            particles.append((*self.world_positions[star.key], *color, opacity, diameter,
                              1.0 if app or star.key == selected else 0.0, seed(star.key)))
        return particles

    def link_vertices(self):
        vertices = []
        selected = self._hovered or self._selected
        for link in self.atlas.links:
            active = selected in (link.source, link.target)
            # Only the fine chronological path remains in the overview.
            alpha = 0.44 if active else 0.07 if link.kind == "chronology" else 0.018
            color = (0.89, 0.66, 0.38) if link.kind == "nearby" else (0.48, 0.68, 0.95)
            for key in (link.source, link.target):
                vertices.append((*self.world_positions[key], *color, alpha, 1.0, 0.0, 0.0))
        return vertices

    def _sprite(self, color, cloud=False, variant=0):
        cache = self._clouds if cloud else self._sprites
        key = (*color, variant)
        if key in cache:
            return cache[key]
        size = 384 if cloud else 128
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor.fromRgbF(*color)
        if cloud:
            rng = random.Random(variant + 12)
            for _ in range(55):
                x, y = rng.gauss(size / 2, size * 0.17), rng.gauss(size / 2, size * 0.17)
                radius = rng.uniform(35, 110)
                gradient = QRadialGradient(x, y, radius)
                gradient.setColorAt(0, QColor(c.red(), c.green(), c.blue(), 28))
                gradient.setColorAt(1, QColor(c.red(), c.green(), c.blue(), 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(gradient)
                painter.drawEllipse(QPointF(x, y), radius, radius)
        else:
            gradient = QRadialGradient(size / 2, size / 2, size / 2)
            for stop, alpha in ((0, 255), (0.04, 240), (0.10, 150), (0.22, 38), (0.5, 9), (1, 0)):
                gradient.setColorAt(stop, QColor(c.red(), c.green(), c.blue(), alpha))
            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(pixmap.rect())
        painter.end()
        cache[key] = pixmap
        return pixmap

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._gl:
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#020307"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        project = self._projector()
        focal = self.camera.focal(self.height())
        # GPU renders the complete field; the software path uses fewer tiny
        # decorative particles while preserving every real memory star.
        particles = [p for i, p in enumerate(self.ambient_particles) if p[8] > 1.5 or i % 3 == 0]
        particles += self.memory_particles()
        for p in particles:
            point = project(p[:3])
            if not point:
                continue
            x, y, depth = point
            size = max(1.0, min(700, p[7] * focal / depth))
            if not (-size < x < self.width() + size and -size < y < self.height() + size):
                continue
            alpha = p[6] / (1 + depth * depth * 0.000000008)
            if size < 2.5 and p[8] < 1.5:
                painter.setPen(QPen(QColor.fromRgbF(*p[3:6], min(1, alpha)), max(0.55, size * 0.4)))
                painter.drawPoint(QPointF(x, y))
            else:
                painter.setOpacity(min(1, alpha))
                sprite = self._sprite(p[3:6], p[8] > 1.5, int(p[9] * 3) if p[8] > 1.5 else 0)
                painter.drawPixmap(QRectF(x - size / 2, y - size / 2, size, size), sprite, QRectF(sprite.rect()))
        painter.setOpacity(1)
        vertices = self.link_vertices()
        for i in range(0, len(vertices), 2):
            a, b = vertices[i:i + 2]
            p1, p2 = project(a[:3]), project(b[:3])
            if p1 and p2:
                painter.setPen(QPen(QColor.fromRgbF(*a[3:7]), 0.7))
                painter.drawLine(QPointF(*p1[:2]), QPointF(*p2[:2]))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.end()

    def paint_annotations(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._entry_opacity)
        occupied = []
        for star in sorted(self.atlas.stars, key=lambda s: s.kind != "app"):
            active = star.key in (self._selected, self._hovered)
            if self.minimal_labels and not active:
                continue
            if star.kind != "app" and not active:
                continue
            point = self.project_star(star.key)
            if point is None or not self.rect().adjusted(25, 80, -25, -90).contains(point.toPoint()):
                continue
            label = star.label if star.kind == "app" else star.label[5:] if star.kind == "day" else tr("手记 · ", "Note · ") + star.sources[0].date[5:]
            font = QFont("Microsoft YaHei", 9 if star.kind == "app" else 8)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            label = metrics.elidedText(label, Qt.TextElideMode.ElideRight, 190)
            width = metrics.horizontalAdvance(label)
            box = QRectF(point.x() + 15, point.y() + 6, width + 6, metrics.height() + 4)
            if not active and any(box.intersects(other) for other in occupied):
                continue
            occupied.append(box.adjusted(-5, -4, 5, 4))
            painter.setPen(QColor("#e0e6f0" if active else "#a3b0c6"))
            painter.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            if active:
                painter.setPen(QPen(QColor(215, 231, 255, 100), 0.7))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(point, 13, 13)
        if not self.atlas.stars:
            painter.setPen(QColor("#acbcd4"))
            painter.setFont(QFont("Microsoft YaHei", 13))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             tr("这片星空，等待你留下足迹。\n试试其他日期，或写下一句话。",
                                "This sky is waiting for your memories.\nTry another date, or leave a note."))
