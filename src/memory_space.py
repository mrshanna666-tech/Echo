"""Deterministic 3D presentation geometry; depth never implies extra evidence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

from src.memory_star_map import MemoryAtlas

Vec3 = tuple[float, float, float]


def seed(key: str) -> float:
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big") / 2**64


def add(a: Vec3, b: Vec3) -> Vec3:
    return tuple(x + y for x, y in zip(a, b))


def scale(a: Vec3, value: float) -> Vec3:
    return tuple(x * value for x in a)


def dot(a: Vec3, b: Vec3) -> float:
    return sum(x * y for x, y in zip(a, b))


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def normalize(a: Vec3) -> Vec3:
    return scale(a, 1 / max(math.sqrt(dot(a, a)), 0.00001))


def constellation_positions(atlas: MemoryAtlas) -> dict[str, Vec3]:
    """Preserve app grouping; shared depths are a visual arrangement only."""
    centers = {star.app_name: (star.position, (seed(star.key) - 0.5) * 510)
               for star in atlas.stars if star.kind == "app"}
    positions = {}
    for star in atlas.stars:
        x, y = star.position
        center, layer = centers.get(star.app_name, ((x, y), 0))
        z = layer if star.kind == "app" else layer + (seed(star.key + ":depth") - 0.5) * 230
        # A gently curved volume gives nearby stars a visible parallax.
        z += (x - center[0]) * 0.12
        positions[star.key] = (x, -y * 0.86, z)
    return positions


@dataclass
class SpaceCamera:
    target: Vec3 = (0.0, 0.0, 0.0)
    distance: float = 1500.0
    yaw: float = 0.12
    pitch: float = 0.18
    fov: float = 50.0

    def basis(self) -> tuple[Vec3, Vec3, Vec3, Vec3]:
        offset = (math.sin(self.yaw) * math.cos(self.pitch), math.sin(self.pitch),
                  math.cos(self.yaw) * math.cos(self.pitch))
        eye = add(self.target, scale(offset, self.distance))
        forward = scale(offset, -1)
        right = normalize(cross(forward, (0.0, 1.0, 0.0)))
        return eye, right, cross(right, forward), forward

    def focal(self, height: int) -> float:
        return height / (2 * math.tan(math.radians(self.fov) / 2))

    def project(self, position: Vec3, width: int, height: int) -> tuple[float, float, float] | None:
        eye, right, up, forward = self.basis()
        relative = add(position, scale(eye, -1))
        depth = dot(relative, forward)
        if depth <= 12 or depth >= 20000:
            return None
        focal = self.focal(height)
        return (width / 2 + dot(relative, right) * focal / depth,
                height / 2 - dot(relative, up) * focal / depth, depth)

    def orbit(self, dx: float, dy: float) -> None:
        self.yaw += dx * 0.006
        self.pitch = max(-1.38, min(1.38, self.pitch + dy * 0.006))

    def pan(self, dx: float, dy: float, height: int) -> None:
        _, right, up, _ = self.basis()
        units = self.distance / max(self.focal(height), 1)
        self.target = add(self.target, add(scale(right, -dx * units), scale(up, dy * units)))


def camera_between(start: SpaceCamera, end: SpaceCamera, progress: float) -> SpaceCamera:
    """Blend a complete pose with gentle starts/stops and the shortest turn.

    A quintic smoothstep has zero velocity and acceleration at both ends.
    Logarithmic distance keeps a large pullback from rushing past nearby stars.
    """
    t = max(0.0, min(1.0, progress))
    t = t * t * t * (t * (t * 6 - 15) + 10)
    yaw_delta = math.remainder(end.yaw - start.yaw, math.tau)
    return SpaceCamera(
        target=tuple(a + (b - a) * t for a, b in zip(start.target, end.target)),
        distance=math.exp(math.log(start.distance) * (1 - t) + math.log(end.distance) * t),
        yaw=start.yaw + yaw_delta * t,
        pitch=start.pitch + (end.pitch - start.pitch) * t,
        fov=start.fov + (end.fov - start.fov) * t,
    )
