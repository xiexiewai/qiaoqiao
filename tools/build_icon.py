"""Export the approved pixel master as a multi-size Windows icon using Qt."""

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main():
    master = QImage(str(ROOT / "assets" / "qiaoqiao-pixel.png"))
    if master.isNull() or master.width() != 64 or master.height() != 64:
        raise RuntimeError("The approved icon master must be a 64 x 64 PNG.")
    frames = []
    for size in SIZES:
        image = master.scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ).convertToFormat(QImage.Format.Format_ARGB32)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError(f"Could not encode the {size}px icon.")
        frames.append(bytes(buffer.data()))
        buffer.close()

    # ICONDIR + ICONDIRENTRY records, followed by 32-bit PNG frames.
    offset = 6 + 16 * len(SIZES)
    entries = []
    for size, frame in zip(SIZES, frames):
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(frame), offset))
        offset += len(frame)
    content = struct.pack("<HHH", 0, 1, len(SIZES)) + b"".join(entries) + b"".join(frames)
    target = ROOT / "assets" / "qiaoqiao.ico"
    if not target.exists() or target.read_bytes() != content:
        target.write_bytes(content)
    print(target)


if __name__ == "__main__":
    main()
