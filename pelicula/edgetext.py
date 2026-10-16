"""Imagem do texto impresso na borda da película (códigos e nome do filme)."""

from __future__ import annotations

import numpy as np


def render(text: str, height: int = 64) -> np.ndarray | None:
    """Máscara (altura x largura, uint8) com o texto em branco. None se não houver Qt de interface."""
    if not text:
        return None
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter
    except ImportError:
        return None
    if QGuiApplication.instance() is None:
        return None
    fams = set(QFontDatabase.families())
    family = next((f for f in ("Bahnschrift SemiCondensed", "Bahnschrift", "Arial Narrow", "DejaVu Sans Condensed",
                               "Arial") if f in fams), "Sans Serif")
    font = QFont(family)
    font.setPixelSize(int(height * 0.62))
    font.setWeight(QFont.Weight.DemiBold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, height * 0.04)
    probe = QImage(8, 8, QImage.Format.Format_Grayscale8)
    p = QPainter(probe)
    p.setFont(font)
    width = p.fontMetrics().horizontalAdvance(text) + height // 2
    p.end()
    img = QImage(width, height, QImage.Format.Format_Grayscale8)
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(font)
    p.setPen(QColor(255, 255, 255))
    p.drawText(0, 0, width, height, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
    p.end()
    bpl = img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * height).reshape(height, bpl)[:, :width]
    # Tinta de borda é levemente borrada e irregular.
    arr = arr.astype(np.float32)
    k = np.array([0.25, 0.5, 0.25], np.float32)
    arr = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), 1, arr)
    arr = np.apply_along_axis(lambda c: np.convolve(c, k, mode="same"), 0, arr)
    rng = np.random.default_rng(len(text))
    arr *= 0.82 + 0.18 * rng.random(arr.shape, dtype=np.float32)
    return np.ascontiguousarray(np.clip(arr, 0, 255).astype(np.uint8))
