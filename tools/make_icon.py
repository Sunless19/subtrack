"""Writes assets/subtrack.ico from the icon drawn in subtrack.ui.icon.

Run after changing the icon:  python tools/make_icon.py
The .ico holds one PNG per size, which Windows Vista and later read natively.
Run it on a normal desktop session: Qt's "offscreen" platform has no fonts, so
the letter would come out as an empty box. The result is committed, so CI never
needs to run this.
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from subtrack.ui.icon import ICON_SIZES, draw_icon  # noqa: E402


def png_bytes(size: int) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    draw_icon(size).save(buffer, "PNG")
    return bytes(buffer.data())


def write_ico(path: Path) -> None:
    images = [(size, png_bytes(size)) for size in ICON_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))  # reserved, type 1 = icon, count
    offset = len(header) + 16 * len(images)
    directory = b""
    for size, data in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        directory += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + directory + b"".join(data for _, data in images))


if __name__ == "__main__":
    app = QGuiApplication([])
    target = ROOT / "assets" / "subtrack.ico"
    write_ico(target)
    print(f"Wrote {target} ({target.stat().st_size} bytes)")
