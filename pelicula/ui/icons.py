"""Ícones vetoriais desenhados com QPainter (sem arquivos externos)."""

from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme


def _pen(p: QPainter, color: QColor, w: float = 1.8) -> None:
    pen = QPen(color, w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _reel(p: QPainter, c: QColor, cx: float, cy: float, r: float) -> None:
    _pen(p, c, 1.8)
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setBrush(QBrush(c))
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(5):
        a = math.radians(-90 + i * 72)
        p.drawEllipse(QPointF(cx + math.cos(a) * r * 0.52, cy + math.sin(a) * r * 0.52), r * 0.2, r * 0.2)
    p.drawEllipse(QPointF(cx, cy), r * 0.1, r * 0.1)


def draw(name: str, p: QPainter, c: QColor) -> None:
    if name == "open":
        _pen(p, c)
        path = QPainterPath()
        path.moveTo(3, 7)
        path.lineTo(3, 18)
        path.quadTo(3, 19, 4, 19)
        path.lineTo(19, 19)
        path.lineTo(21.5, 11)
        path.lineTo(7, 11)
        path.lineTo(4.5, 18.5)
        p.drawPath(path)
        path2 = QPainterPath()
        path2.moveTo(3, 7)
        path2.lineTo(3, 5.5)
        path2.lineTo(9, 5.5)
        path2.lineTo(11, 7.5)
        path2.lineTo(18, 7.5)
        path2.lineTo(18, 11)
        p.drawPath(path2)
    elif name == "export":
        _pen(p, c)
        p.drawLine(QPointF(12, 3.5), QPointF(12, 14.5))
        p.drawPolyline([QPointF(7.5, 8), QPointF(12, 3.5), QPointF(16.5, 8)])
        path = QPainterPath()
        path.moveTo(4, 13)
        path.lineTo(4, 19.5)
        path.lineTo(20, 19.5)
        path.lineTo(20, 13)
        p.drawPath(path)
    elif name == "queue":
        _pen(p, c)
        for y in (6, 12, 18):
            p.drawLine(QPointF(9, y), QPointF(20, y))
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        for y in (6, 12, 18):
            p.drawEllipse(QPointF(5, y), 1.4, 1.4)
    elif name == "play":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        path = QPainterPath()
        path.moveTo(7.5, 4.5)
        path.lineTo(19.5, 12)
        path.lineTo(7.5, 19.5)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        p.drawRoundedRect(QRectF(6.5, 5, 3.6, 14), 1, 1)
        p.drawRoundedRect(QRectF(13.9, 5, 3.6, 14), 1, 1)
    elif name in ("step_back", "step_fwd"):
        p.save()
        if name == "step_back":
            p.translate(24, 0)
            p.scale(-1, 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        path = QPainterPath()
        path.moveTo(6, 6)
        path.lineTo(15, 12)
        path.lineTo(6, 18)
        path.closeSubpath()
        p.drawPath(path)
        p.drawRoundedRect(QRectF(16, 6, 2.6, 12), 1, 1)
        p.restore()
    elif name == "loop":
        _pen(p, c)
        path = QPainterPath()
        path.moveTo(17, 7)
        path.lineTo(8, 7)
        path.arcTo(QRectF(3, 7, 10, 10), 90, 180)
        path.lineTo(9, 17)
        p.drawPath(path)
        p.drawPolyline([QPointF(14.5, 4.5), QPointF(17, 7), QPointF(14.5, 9.5)])
        path2 = QPainterPath()
        path2.moveTo(13, 17)
        path2.lineTo(16, 17)
        path2.arcTo(QRectF(11, 7, 10, 10), -90, 180)
        p.drawPath(path2)
    elif name == "mark_in":
        _pen(p, c)
        p.drawPolyline([QPointF(11, 5), QPointF(7, 5), QPointF(7, 19), QPointF(11, 19)])
        p.drawLine(QPointF(12, 12), QPointF(19, 12))
    elif name == "mark_out":
        _pen(p, c)
        p.drawPolyline([QPointF(13, 5), QPointF(17, 5), QPointF(17, 19), QPointF(13, 19)])
        p.drawLine(QPointF(5, 12), QPointF(12, 12))
    elif name == "clear":
        _pen(p, c)
        p.drawLine(QPointF(7, 7), QPointF(17, 17))
        p.drawLine(QPointF(17, 7), QPointF(7, 17))
    elif name == "save":
        _pen(p, c)
        path = QPainterPath()
        path.moveTo(5, 4.5)
        path.lineTo(16, 4.5)
        path.lineTo(19.5, 8)
        path.lineTo(19.5, 19.5)
        path.lineTo(4.5, 19.5)
        path.lineTo(4.5, 5)
        p.drawPath(path)
        p.drawRect(QRectF(8, 13, 8, 6.5))
        p.drawLine(QPointF(8.5, 4.5), QPointF(8.5, 8.5))
        p.drawLine(QPointF(8.5, 8.5), QPointF(14, 8.5))
    elif name == "trash":
        _pen(p, c)
        p.drawLine(QPointF(4.5, 7), QPointF(19.5, 7))
        p.drawPolyline([QPointF(9.5, 7), QPointF(9.5, 4.5), QPointF(14.5, 4.5), QPointF(14.5, 7)])
        path = QPainterPath()
        path.moveTo(6.5, 7)
        path.lineTo(7.5, 19.5)
        path.lineTo(16.5, 19.5)
        path.lineTo(17.5, 7)
        p.drawPath(path)
    elif name == "more":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        for x in (6, 12, 18):
            p.drawEllipse(QPointF(x, 12), 1.7, 1.7)
    elif name == "reset":
        _pen(p, c)
        path = QPainterPath()
        path.arcMoveTo(QRectF(5, 5, 14, 14), 120)
        path.arcTo(QRectF(5, 5, 14, 14), 120, 290)
        p.drawPath(path)
        p.drawPolyline([QPointF(5.2, 4.8), QPointF(8.2, 7.9), QPointF(4.4, 9.6)])
    elif name in ("undo", "redo"):
        p.save()
        if name == "redo":
            p.translate(24, 0)
            p.scale(-1, 1)
        _pen(p, c)
        path = QPainterPath()
        path.moveTo(5, 10)
        path.lineTo(14, 10)
        path.quadTo(19.5, 10, 19.5, 14.5)
        path.quadTo(19.5, 19, 14, 19)
        path.lineTo(10, 19)
        p.drawPath(path)
        p.drawPolyline([QPointF(8.5, 6), QPointF(4.5, 10), QPointF(8.5, 14)])
        p.restore()
    elif name == "settings":
        _pen(p, c)
        for y, x in ((6, 15), (12, 8), (18, 13)):
            p.drawLine(QPointF(4, y), QPointF(20, y))
            p.setBrush(QBrush(QColor(theme.PANEL)))
            p.drawEllipse(QPointF(x, y), 2.3, 2.3)
            p.setBrush(Qt.BrushStyle.NoBrush)
    elif name == "split":
        _pen(p, c)
        p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2, 2)
        p.drawLine(QPointF(12, 3), QPointF(12, 21))
    elif name == "lut":
        _pen(p, c)
        path = QPainterPath()
        path.moveTo(12, 3.5)
        path.lineTo(19.5, 7.5)
        path.lineTo(19.5, 16.5)
        path.lineTo(12, 20.5)
        path.lineTo(4.5, 16.5)
        path.lineTo(4.5, 7.5)
        path.closeSubpath()
        p.drawPath(path)
        p.drawPolyline([QPointF(4.5, 7.5), QPointF(12, 11.5), QPointF(19.5, 7.5)])
        p.drawLine(QPointF(12, 11.5), QPointF(12, 20.5))
    elif name == "image":
        _pen(p, c)
        p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2, 2)
        p.drawPolyline([QPointF(4, 17), QPointF(9.5, 11.5), QPointF(13, 15), QPointF(15.5, 12.5), QPointF(20, 17)])
        p.drawEllipse(QPointF(15.5, 8.8), 1.4, 1.4)
    elif name == "film":
        _reel(p, c, 12, 12, 8.5)
    elif name == "dice":
        _pen(p, c)
        p.drawRoundedRect(QRectF(4.5, 4.5, 15, 15), 3, 3)
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        for x, y in ((8.5, 8.5), (12, 12), (15.5, 15.5)):
            p.drawEllipse(QPointF(x, y), 1.4, 1.4)
    elif name == "check":
        _pen(p, c, 2.2)
        p.drawPolyline([QPointF(5, 12.5), QPointF(10, 17), QPointF(19, 7)])
    elif name == "close":
        _pen(p, c, 2.0)
        p.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
        p.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))
    elif name == "folder":
        _pen(p, c)
        path = QPainterPath()
        path.moveTo(3.5, 6)
        path.lineTo(9.5, 6)
        path.lineTo(11.5, 8)
        path.lineTo(20.5, 8)
        path.lineTo(20.5, 18.5)
        path.lineTo(3.5, 18.5)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "camera":
        _pen(p, c)
        p.drawRoundedRect(QRectF(3.5, 7, 17, 12), 2.5, 2.5)
        p.drawEllipse(QPointF(12, 13), 3.5, 3.5)
        p.drawPolyline([QPointF(8.5, 7), QPointF(10, 4.5), QPointF(14, 4.5), QPointF(15.5, 7)])
    elif name == "chevron":
        _pen(p, c, 2.0)
        p.drawPolyline([QPointF(8, 9.5), QPointF(12, 14), QPointF(16, 9.5)])
    elif name == "plus":
        _pen(p, c, 2.0)
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name in ("volume", "mute"):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        path = QPainterPath()
        path.moveTo(4, 9.5)
        path.lineTo(7.5, 9.5)
        path.lineTo(12, 5.5)
        path.lineTo(12, 18.5)
        path.lineTo(7.5, 14.5)
        path.lineTo(4, 14.5)
        path.closeSubpath()
        p.drawPath(path)
        _pen(p, c)
        if name == "volume":
            p.drawArc(QRectF(10, 8, 8, 8), -50 * 16, 100 * 16)
            p.drawArc(QRectF(9, 4.5, 13, 15), -50 * 16, 100 * 16)
        else:
            p.drawLine(QPointF(15, 9), QPointF(20.5, 15))
            p.drawLine(QPointF(20.5, 9), QPointF(15, 15))
    elif name == "fit":
        _pen(p, c)
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx, cy = 12 + sx * 7, 12 + sy * 6
            p.drawPolyline([QPointF(cx, cy - sy * 3.5), QPointF(cx, cy), QPointF(cx - sx * 3.5, cy)])


@lru_cache(maxsize=256)
def icon(name: str, color: str = theme.TEXT, size: int = 20) -> QIcon:
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size * scale / 24.0, size * scale / 24.0)
        draw(name, p, QColor(color))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    return ic


def assets_dir():
    """Pasta assets/ no código-fonte ou dentro do executável (PyInstaller)."""
    import sys
    from pathlib import Path
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets"


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    d = assets_dir()
    ico = d / "logo.ico"
    if ico.is_file():
        ic = QIcon(str(ico))
        for f in (d / "logo-256.png", d / "logo-512.png"):
            if f.is_file():
                ic.addFile(str(f))
        if not ic.isNull():
            return ic
    return _drawn_app_icon()


def _drawn_app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(s, s)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(s / 24.0, s / 24.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(theme.ACCENT)))
        p.drawRoundedRect(QRectF(0.5, 0.5, 23, 23), 6, 6)
        _reel(p, QColor("#1b1205"), 12, 12, 7.5)
        p.end()
        ic.addPixmap(pm)
    return ic
