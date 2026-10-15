"""Native, offline OpenGL particles. Qt's painter path remains a fallback."""
from __future__ import annotations

from array import array
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QMatrix4x4, QSurfaceFormat, QVector3D, QVector4D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram
from PySide6.QtOpenGLWidgets import QOpenGLWidget

logger = logging.getLogger(__name__)

# position.xyz, color.rgba, physical diameter, particle type, stable phase.
VERTEX = """
attribute vec3 position;
attribute vec4 color;
attribute float diameter;
attribute float kind;
attribute float phase;
uniform mat4 mvp;
uniform mat4 view;
uniform vec4 params;
varying vec4 tint;
varying float particleKind;
varying float particlePhase;
void main() {
    vec4 camera = view * vec4(position, 1.0);
    float depth = max(12.0, -camera.z);
    gl_Position = mvp * vec4(position, 1.0);
    gl_PointSize = clamp(diameter * params.x * params.y / depth, 1.0, 700.0);
    float fog = 1.0 / (1.0 + depth * depth * 0.000000008);
    tint = vec4(color.rgb, color.a * fog);
    particleKind = kind;
    particlePhase = phase;
}
"""

FRAGMENT = """
uniform vec4 params;
varying vec4 tint;
varying float particleKind;
varying float particlePhase;
float noise(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}
float smoothNoise(vec2 p) {
    vec2 i = floor(p); vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(noise(i), noise(i + vec2(1., 0.)), f.x),
               mix(noise(i + vec2(0., 1.)), noise(i + vec2(1., 1.)), f.x), f.y);
}
void main() {
    if (params.z > 0.5) { gl_FragColor = tint; return; }
    vec2 uv = gl_PointCoord * 2.0 - 1.0;
    float r2 = dot(uv, uv);
    if (r2 > 1.0) discard;
    if (particleKind > 1.5) {
        vec2 p = uv * 3.3 + particlePhase * 30.0;
        float cloud = smoothNoise(p) * 0.55 + smoothNoise(p * 2.1) * 0.3 + smoothNoise(p * 4.2) * 0.15;
        float a = exp(-r2 * 3.5) * smoothstep(0.18, 0.85, cloud) * 1.5;
        gl_FragColor = vec4(tint.rgb, tint.a * a);
    } else {
        float halo = exp(-r2 * 5.0) * 0.16;
        float glow = exp(-r2 * 45.0) * 0.75;
        float core = exp(-r2 * 420.0);
        float rays = 0.0;
        if (particleKind > 0.5) {
            rays = (exp(-abs(uv.x) * 140.0) + exp(-abs(uv.y) * 140.0)) * exp(-r2 * 6.0) * 0.16;
        }
        vec3 light = mix(tint.rgb, vec3(1.0), core * 0.8);
        gl_FragColor = vec4(light, tint.a * (halo + glow + core + rays));
    }
}
"""


class StarGLSurface(QOpenGLWidget):
    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setDepthBufferSize(0)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.ready = False
        self._program = None
        self._buffers = {}
        self._dirty = True

    def initializeGL(self) -> None:  # noqa: N802
        try:
            self._functions = self.context().functions()
            self._program = QOpenGLShaderProgram(self)
            prefix = "precision mediump float;\n" if self.context().isOpenGLES() else "#version 120\n"
            for kind, source in ((QOpenGLShader.ShaderTypeBit.Vertex, VERTEX),
                                 (QOpenGLShader.ShaderTypeBit.Fragment, FRAGMENT)):
                if not self._program.addShaderFromSourceCode(kind, prefix + source):
                    raise RuntimeError(self._program.log())
            if not self._program.link():
                raise RuntimeError(self._program.log())
            self._uniforms = {name: self._program.uniformLocation(name)
                              for name in ("mvp", "view", "params")}
            self.ready = True
            self._dirty = True
            self.context().aboutToBeDestroyed.connect(self._release)
        except Exception:
            logger.exception("Atlas OpenGL initialization failed; using the painter renderer.")
            QTimer.singleShot(0, self.owner.use_software_renderer)

    def _release(self) -> None:
        self.makeCurrent()
        for buffer, _ in self._buffers.values():
            buffer.destroy()
        self._buffers.clear()
        self.ready = False
        self.doneCurrent()

    def clear_memory_geometry(self) -> None:
        if self.ready and "memories" in self._buffers:
            self.makeCurrent()
            buffer, _ = self._buffers.pop("memories")
            buffer.destroy()
            if "links" in self._buffers:
                self._buffers.pop("links")[0].destroy()
            self.doneCurrent()
        self._dirty = True

    def invalidate(self) -> None:
        self._dirty = True
        self.update()

    def _upload(self, name, vertices) -> None:
        if name in self._buffers:
            self._buffers.pop(name)[0].destroy()
        values = array("f", (value for vertex in vertices for value in vertex))
        raw = values.tobytes()
        buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        buffer.create()
        buffer.bind()
        buffer.allocate(raw, len(raw))
        buffer.release()
        self._buffers[name] = (buffer, len(vertices))

    def _draw(self, name, primitive=0x0000) -> None:
        if name not in self._buffers:
            return
        buffer, count = self._buffers[name]
        if not count:
            return
        buffer.bind()
        for name, offset, count_components in (("position", 0, 3), ("color", 12, 4),
                                                ("diameter", 28, 1), ("kind", 32, 1), ("phase", 36, 1)):
            self._program.enableAttributeArray(name)
            self._program.setAttributeBuffer(name, 0x1406, offset, count_components, 40)
        self._functions.glDrawArrays(primitive, 0, count)
        buffer.release()

    def paintGL(self) -> None:  # noqa: N802
        if not self.ready:
            return
        f = self._functions
        f.glClearColor(0.008, 0.012, 0.029, 1.0)
        f.glClear(0x4000)
        f.glDisable(0x0B71)  # GL_DEPTH_TEST: additive particles have no opaque surfaces.
        f.glEnable(0x0BE2)  # GL_BLEND
        f.glBlendFunc(0x0302, 1)
        if not self.context().isOpenGLES():
            f.glEnable(0x8642)  # GL_PROGRAM_POINT_SIZE
            f.glEnable(0x8861)  # GL_POINT_SPRITE (compatibility contexts)
        if self._dirty:
            if "ambient" not in self._buffers:
                self._upload("ambient", self.owner.ambient_particles)
            self._upload("memories", self.owner.memory_particles())
            self._upload("links", self.owner.link_vertices())
            self._dirty = False
        camera = self.owner.camera
        eye, _, _, _ = camera.basis()
        view = QMatrix4x4()
        view.lookAt(QVector3D(*eye), QVector3D(*camera.target), QVector3D(0, 1, 0))
        projection = QMatrix4x4()
        projection.perspective(camera.fov, self.width() / max(self.height(), 1), 12, 20000)
        self._program.bind()
        self._program.setUniformValue(self._uniforms["mvp"], projection * view)
        self._program.setUniformValue(self._uniforms["view"], view)
        focal, pixels = camera.focal(self.height()), self.devicePixelRatioF()
        self._program.setUniformValue(self._uniforms["params"], QVector4D(focal, pixels, 0, 0))
        self._draw("ambient")
        self._program.setUniformValue(self._uniforms["params"], QVector4D(focal, pixels, 1, 0))
        self._draw("links", 0x0001)
        self._program.setUniformValue(self._uniforms["params"], QVector4D(focal, pixels, 0, 0))
        self._draw("memories")
        self._program.release()
