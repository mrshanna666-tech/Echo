from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Echo应用图标展示与设计预览.png"
OUTPUT_DIR = ROOT / "assets" / "icons"
MASTER = OUTPUT_DIR / "echo_master.png"
ICO = OUTPUT_DIR / "echo.ico"

# The large dark icon occupies the upper-left showcase area. Keep a small,
# even margin so the outer glow remains visible without retaining the poster.
CROP_X = 96
CROP_Y = 104
CROP_SIZE = 576
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(image: QImage) -> bytes:
    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Could not encode icon PNG")
    buffer.close()
    return bytes(payload)


def build() -> None:
    source = QImage(str(SOURCE))
    if source.isNull():
        raise FileNotFoundError(SOURCE)
    crop = source.copy(CROP_X, CROP_Y, CROP_SIZE, CROP_SIZE)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    master = crop.scaled(
        1024,
        1024,
        aspectMode=Qt.AspectRatioMode.KeepAspectRatio,
        mode=Qt.TransformationMode.SmoothTransformation,
    )
    if not master.save(str(MASTER), "PNG"):
        raise RuntimeError(f"Could not save {MASTER}")

    images = []
    for size in ICON_SIZES:
        rendered = crop.scaled(
            size,
            size,
            aspectMode=Qt.AspectRatioMode.KeepAspectRatio,
            mode=Qt.TransformationMode.SmoothTransformation,
        )
        images.append((size, png_bytes(rendered)))

    directory_size = 6 + 16 * len(images)
    offset = directory_size
    with ICO.open("wb") as output:
        output.write(struct.pack("<HHH", 0, 1, len(images)))
        for size, payload in images:
            dimension = 0 if size == 256 else size
            output.write(
                struct.pack(
                    "<BBBBHHII",
                    dimension,
                    dimension,
                    0,
                    0,
                    1,
                    32,
                    len(payload),
                    offset,
                )
            )
            offset += len(payload)
        for _, payload in images:
            output.write(payload)


if __name__ == "__main__":
    build()
