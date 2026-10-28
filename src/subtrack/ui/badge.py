"""Coloured initial badges shown next to subscription names.

Generated from the name (same name, same colour), so no logo files or internet
lookups are needed and no brand artwork is copied.
"""

import hashlib
from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

# Distinct, readable with white text, in both light and dark themes.
_PALETTE = [
    "#e53935", "#d81b60", "#8e24aa", "#5e35b1", "#3949ab", "#1e88e5", "#039be5", "#00897b",
    "#43a047", "#7cb342", "#f4511e", "#6d4c41", "#546e7a", "#c0ca33", "#fb8c00", "#00acc1",
]


def badge_colour(name: str) -> QColor:
    digest = hashlib.md5(name.strip().lower().encode()).digest()
    return QColor(_PALETTE[digest[0] % len(_PALETTE)])


def _initials(name: str) -> str:
    words = [w for w in name.replace("+", " ").split() if w[:1].isalnum()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:1].upper()
    return (words[0][:1] + words[1][:1]).upper()


@lru_cache(maxsize=512)
def badge_icon(name: str, size: int = 32) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(badge_colour(name))
    painter.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    text = _initials(name)
    font = QFont("Segoe UI")
    font.setBold(True)
    font.setPixelSize(round(size * (0.5 if len(text) == 1 else 0.4)))
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)
