"""The app icon, drawn in code so the running app needs no image files.

tools/make_icon.py uses the same drawing to produce assets/subtrack.ico for the
.exe and the installer.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw_icon(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    margin = size / 16
    radius = size * 0.22
    painter.setBrush(QColor("#2f6fdf"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QRectF(margin, margin, size - 2 * margin, size - 2 * margin), radius, radius)
    font = QFont("Segoe UI")
    font.setBold(True)
    font.setPixelSize(round(size * 0.62))
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "S")
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(draw_icon(size))
    return icon
