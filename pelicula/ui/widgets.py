"""Controles personalizados: slider, chave, seções, histograma e linha do tempo."""

from __future__ import annotations

import math
import os
import random

import numpy as np
from PySide6.QtCore import (Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QColorDialog, QComboBox, QFileDialog, QFrame,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from .. import luts, params, system
from ..i18n import _, decimal_sep, parse_decimal
from . import icons, theme
from .store import ParamStore


# ------------------------------------------------------------------ chave liga/desliga
class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._p = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(36, 20)

    def _get(self) -> float:
        return self._p

    def _set(self, v: float) -> None:
        self._p = v
        self.update()

    knob = Property(float, _get, _set)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._p)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def paintEvent(self, _event):
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._p = 1.0 if self.isChecked() else 0.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 2, 34, 16)
        off = QColor(theme.PANEL3)
        on = QColor(theme.ACCENT)
        c = QColor(int(off.red() + (on.red() - off.red()) * self._p),
                   int(off.green() + (on.green() - off.green()) * self._p),
                   int(off.blue() + (on.blue() - off.blue()) * self._p))
        p.setPen(QPen(QColor("#3a332c") if self._p < 0.5 else c, 1))
        p.setBrush(c)
        p.drawRoundedRect(r, 8, 8)
        x = 3 + self._p * 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1b1205") if self._p > 0.5 else QColor("#cfc4b4"))
        p.drawEllipse(QRectF(x, 4, 12, 12))
        p.end()


# ------------------------------------------------------------------ slider
class FilmSlider(QWidget):
    valueChanged = Signal(float)
    released = Signal()
    resetRequested = Signal()

    def __init__(self, lo: float, hi: float, step: float, default: float, parent=None):
        super().__init__(parent)
        self.lo, self.hi, self.step, self.default = float(lo), float(hi), float(step), float(default)
        self._v = float(default)
        self._drag = False
        self._hover = False
        self._fine_anchor = None
        self.origin = 0.0 if self.lo < 0 < self.hi else self.lo
        self.setMinimumHeight(22)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def value(self) -> float:
        return self._v

    def setValue(self, v: float, emit: bool = False) -> None:
        v = min(max(float(v), self.lo), self.hi)
        if v != self._v:
            self._v = v
            self.update()
            if emit:
                self.valueChanged.emit(v)

    def _x(self, v: float) -> float:
        span = self.hi - self.lo or 1.0
        return 8 + (self.width() - 16) * (v - self.lo) / span

    def _from_x(self, x: float) -> float:
        span = self.hi - self.lo
        v = self.lo + (x - 8) / max(1.0, self.width() - 16) * span
        return self._snap(v)

    def _snap(self, v: float) -> float:
        if self.step > 0:
            v = round((v - self.lo) / self.step) * self.step + self.lo
        return min(max(v, self.lo), self.hi)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        x0, x1 = 8, self.width() - 8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.PANEL3))
        p.drawRoundedRect(QRectF(x0, cy - 2, x1 - x0, 4), 2, 2)
        xv = self._x(self._v)
        xo = self._x(self.origin)
        a, b = sorted((xo, xv))
        grad = QLinearGradient(a, 0, b, 0)
        grad.setColorAt(0, QColor(theme.ACCENT))
        grad.setColorAt(1, QColor(theme.ACCENT_HI))
        en = self.isEnabled()
        p.setBrush(QBrush(grad) if en else QColor(theme.ACCENT_DIM))
        p.drawRoundedRect(QRectF(a, cy - 2, max(b - a, 0.5), 4), 2, 2)
        xd = self._x(self.default)
        p.setBrush(QColor(theme.FAINT))
        p.drawEllipse(QPointF(xd, cy + 7), 1.5, 1.5)
        rad = 7.5 if (self._drag or self._hover) else 6.5
        if self._drag or self.hasFocus():
            p.setBrush(QColor(240, 166, 58, 60))
            p.drawEllipse(QPointF(xv, cy), rad + 4, rad + 4)
        p.setBrush(QColor("#f6eee2") if en else QColor(theme.FAINT))
        p.setPen(QPen(QColor(theme.ACCENT), 2))
        p.drawEllipse(QPointF(xv, cy), rad - 1, rad - 1)
        p.end()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._drag = True
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._fine_anchor = (e.position().x(), self._v)
        else:
            self._fine_anchor = None
            self.setValue(self._from_x(e.position().x()), emit=True)
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag:
            if self._fine_anchor:
                x0, v0 = self._fine_anchor
                span = (self.hi - self.lo) / max(1.0, self.width() - 16)
                self.setValue(self._snap(v0 + (e.position().x() - x0) * span * 0.1), emit=True)
            else:
                self.setValue(self._from_x(e.position().x()), emit=True)
        else:
            hov = abs(e.position().x() - self._x(self._v)) < 12
            if hov != self._hover:
                self._hover = hov
                self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.update()
            self.released.emit()

    def leaveEvent(self, _event):
        self._hover = False
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.resetRequested.emit()

    def wheelEvent(self, e):
        e.ignore()

    def keyPressEvent(self, e):
        k = e.key()
        mult = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        st = self.step or (self.hi - self.lo) / 100
        if k in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self.setValue(self._v + st * mult, emit=True)
            self.released.emit()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self.setValue(self._v - st * mult, emit=True)
            self.released.emit()
        else:
            super().keyPressEvent(e)


def compact(combo: QComboBox, chars: int = 10) -> QComboBox:
    """Evita que listas com textos longos alarguem o painel."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return combo


def fmt_value(p: params.Param, v) -> str:
    """Valor como aparece na caixa de texto, com o separador decimal do idioma."""
    if p.kind == "int":
        return str(int(v))
    if p.percent:
        return f"{v * 100:.0f}%"
    txt = f"{v:.{p.decimals}f}".replace(".", decimal_sep())
    return txt + p.unit


def parse_value(p: params.Param, txt: str):
    """Lê o valor digitado; aceita vírgula ou ponto decimal em qualquer idioma."""
    t = txt.strip().replace("%", "")
    for u in (p.unit.strip(), "px", "EV", "°", "×"):
        if u:
            t = t.replace(u, "")
    v = parse_decimal(t)
    if p.percent:
        v /= 100.0
    return v


# ------------------------------------------------------------------ linhas de parâmetro
class ParamRow(QWidget):
    def __init__(self, param: params.Param, store: ParamStore, parent=None):
        super().__init__(parent)
        self.param = param
        self.store = store
        if param.tip:
            self.setToolTip(_(param.tip))

    def refresh(self) -> None:
        pass

    def _label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("Muted")
        return lab


class NumberRow(ParamRow):
    def __init__(self, param, store, parent=None):
        super().__init__(param, store, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self._label(_(param.label)))
        top.addStretch(1)
        if param.kind == "int":
            dice = QToolButton()
            dice.setObjectName("Flat")
            dice.setIcon(icons.icon("dice", theme.MUTED, 16))
            dice.setToolTip(_("Sortear"))
            dice.clicked.connect(lambda: self.store.set(param.key, random.randint(int(param.min), int(param.max))))
            top.addWidget(dice)
        self.edit = QLineEdit()
        self.edit.setObjectName("Value")
        self.edit.setFixedWidth(70)
        self.edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.edit.editingFinished.connect(self._edited)
        top.addWidget(self.edit)
        lay.addLayout(top)
        self.top = top  # linha do título: o losango das chaves entra aqui (`keyframes_ui`)
        self.slider = FilmSlider(param.min, param.max, param.step, param.default)
        self.slider.valueChanged.connect(self._slid)
        self.slider.resetRequested.connect(lambda: self.store.set(param.key, param.default))
        self.slider.released.connect(self.store.commit)
        lay.addWidget(self.slider)
        self.refresh()

    def _slid(self, v: float) -> None:
        if self.param.kind == "int":
            v = int(round(v))
        self.store.set(self.param.key, v)

    def _edited(self) -> None:
        try:
            v = parse_value(self.param, self.edit.text())
        except ValueError:
            self.refresh()
            return
        v = min(max(v, self.param.min), self.param.max)
        if self.param.kind == "int":
            v = int(round(v))
        self.store.set(self.param.key, v)
        self.store.commit()
        self.refresh()

    def refresh(self) -> None:
        v = self.store.shown(self.param.key)
        self.slider.setValue(v)
        if not self.edit.hasFocus():
            self.edit.setText(fmt_value(self.param, v))


class BoolRow(ParamRow):
    def __init__(self, param, store, parent=None):
        super().__init__(param, store, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.addWidget(self._label(_(param.label)))
        lay.addStretch(1)
        self.sw = ToggleSwitch()
        self.sw.toggled.connect(lambda on: self.store.set(param.key, bool(on)))
        lay.addWidget(self.sw)
        self.refresh()

    def refresh(self) -> None:
        self.sw.blockSignals(True)
        self.sw.setChecked(bool(self.store.get(self.param.key)))
        self.sw.blockSignals(False)
        self.sw.update()


class ChoiceRow(ParamRow):
    def __init__(self, param, store, parent=None):
        super().__init__(param, store, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(4)
        lay.addWidget(self._label(_(param.label)))
        self.combo = compact(QComboBox())
        for val, lab in param.choices:
            self.combo.addItem(_(lab), val)
        self.combo.currentIndexChanged.connect(lambda _i: self.store.set(param.key, self.combo.currentData()))
        lay.addWidget(self.combo)
        self.refresh()

    def refresh(self) -> None:
        self.combo.blockSignals(True)
        i = self.combo.findData(self.store.get(self.param.key))
        self.combo.setCurrentIndex(max(i, 0))
        self.combo.blockSignals(False)


class ColorButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.color = QColor(255, 255, 255)
        self.setFixedSize(92, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.PANEL2))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 7, 7)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(5, 5, 16, self.height() - 10), 4, 4)
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(8.5))
        p.drawText(QRectF(26, 0, self.width() - 30, self.height()), Qt.AlignmentFlag.AlignVCenter,
                   self.color.name().upper())
        p.end()


class ColorRow(ParamRow):
    def __init__(self, param, store, parent=None):
        super().__init__(param, store, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.addWidget(self._label(_(param.label)))
        lay.addStretch(1)
        self.btn = ColorButton()
        self.btn.clicked.connect(self._pick)
        lay.addWidget(self.btn)
        self.top = lay
        self.refresh()

    def _pick(self) -> None:
        start = self.btn.color
        dlg = QColorDialog(start, self.window())
        dlg.setWindowTitle(_(self.param.label))
        dlg.currentColorChanged.connect(lambda c: self.store.set(self.param.key, [c.redF(), c.greenF(), c.blueF()], record=False))
        if dlg.exec():
            c = dlg.selectedColor()
            self.store.set(self.param.key, [c.redF(), c.greenF(), c.blueF()])
        else:
            self.store.set(self.param.key, [start.redF(), start.greenF(), start.blueF()], record=False)
        self.store.commit()

    def refresh(self) -> None:
        r, g, b = self.store.shown(self.param.key)
        self.btn.color = QColor.fromRgbF(r, g, b)
        self.btn.update()


class LutRow(ParamRow):
    """Escolha do arquivo .cube: LUTs instalados no PC ou um arquivo qualquer."""

    def __init__(self, param, store, parent=None):
        super().__init__(param, store, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(4)
        lay.addWidget(self._label(_(param.label)))
        self.combo = compact(QComboBox())
        self.combo.setMaxVisibleItems(18)
        lay.addWidget(self.combo)
        self.path = QLabel()
        self.path.setObjectName("Faint")
        self.path.setWordWrap(True)
        lay.addWidget(self.path)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        inst = QPushButton(_("Instalar LUTs…"))
        inst.setIcon(icons.icon("plus", theme.TEXT, 14))
        inst.setToolTip(_("Copia arquivos .cube para a pasta do app; eles passam a aparecer sempre nesta lista."))
        inst.clicked.connect(self._install)
        folder = QPushButton(_("Pasta"))
        folder.setIcon(icons.icon("folder", theme.TEXT, 14))
        folder.setToolTip(_("Abrir a pasta dos LUTs instalados"))
        folder.clicked.connect(lambda: system.open_path(luts.user_dir()))
        btns.addWidget(inst, 1)
        btns.addWidget(folder)
        lay.addLayout(btns)
        self.combo.activated.connect(self._chosen)
        self._fill()
        self.refresh()

    def _install(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(self.window(), _("Instalar LUTs"), "", _("LUT 3D (*.cube)"))
        if paths:
            self.install(paths)

    def install(self, paths: list[str]) -> None:
        from PySide6.QtWidgets import QMessageBox
        done, errors = luts.install(paths)
        self._fill()
        if done:
            self.set_path(done[0])
            msg = _("{n} LUT(s) instalado(s) em Meus LUTs.").format(n=len(done))
        else:
            msg = _("Nenhum LUT foi instalado.")
        if errors:
            msg += "\n\n" + _("Não foi possível instalar:") + "\n" + "\n".join(errors[:8])
        QMessageBox.information(self.window(), _("Instalar LUTs"), msg)

    def _fill(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(_("(nenhum)"), "")
        for label, path in luts.find_system_luts():
            self.combo.addItem(label, path)
        self.combo.addItem(_("Procurar arquivo .cube…"), "__browse__")
        self.combo.blockSignals(False)

    def _chosen(self, _i: int) -> None:
        data = self.combo.currentData()
        if data == "__browse__":
            path, _filter = QFileDialog.getOpenFileName(self.window(), _("Escolher LUT"), "", _("LUT 3D (*.cube)"))
            if not path:
                self.refresh()
                return
            data = path
        self.set_path(data)

    def set_path(self, path: str) -> None:
        self.store.set(self.param.key, path, record=False)
        if path:
            self.store.set("lut_entrada", luts.guess_input(path), record=False)
            self.store.set("lut_on", True, record=False)
        self.store.commit()

    def refresh(self) -> None:
        path = self.store.get(self.param.key)
        self.combo.blockSignals(True)
        i = self.combo.findData(path)
        if i < 0 and path:
            self.combo.insertItem(self.combo.count() - 1, os.path.basename(path), path)
            i = self.combo.findData(path)
        self.combo.setCurrentIndex(max(i, 0))
        self.combo.blockSignals(False)
        self.path.setText(path if path else _("Os LUTs do Premiere e do Resolve instalados aparecem na lista."))


# ------------------------------------------------------------------ roda de cor (modo Edição)
def wheel_hue(x: float, y: float) -> float:
    """Matiz (graus, 0 = vermelho) de um ponto [x, y] da roda.

    Convenção das rodas: 0° (vermelho) à direita, crescendo no sentido anti-horário com y para cima
    (60° amarelo, 120° verde, 180° ciano, 240° azul, 300° magenta), como o matiz HSV.
    """
    return math.degrees(math.atan2(y, x)) % 360.0


def hue_color(hue_deg: float, sat: float = 1.0, val: float = 1.0) -> QColor:
    return QColor.fromHsvF((hue_deg % 360.0) / 360.0, min(max(sat, 0.0), 1.0), min(max(val, 0.0), 1.0))


_WHEEL_CACHE: dict = {}


def _wheel_image(size: int) -> QImage:
    """Disco de matiz × saturação (mesma convenção de `wheel_hue`), desenhado com numpy."""
    img = _WHEEL_CACHE.get(size)
    if img is not None:
        return img
    r = size / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dx = (xx + 0.5 - r) / r
    dy = -(yy + 0.5 - r) / r
    dist = np.sqrt(dx * dx + dy * dy)
    h6 = (np.degrees(np.arctan2(dy, dx)) % 360.0) / 60.0
    val = 0.82
    c = val * np.clip(dist, 0.0, 1.0) * 0.78
    x = c * (1.0 - np.abs(h6 % 2.0 - 1.0))
    z = np.zeros_like(c)
    sector = np.floor(h6).astype(np.int32) % 6
    table = [(c, x, z), (x, c, z), (z, c, x), (z, x, c), (x, z, c), (c, z, x)]
    rgb = np.zeros((size, size, 3), np.float32)
    for k, chans in enumerate(table):
        sel = sector == k
        for ch, arr in enumerate(chans):
            rgb[..., ch][sel] = arr[sel]
    rgb += (val - c)[..., None]
    alpha = np.clip((1.0 - dist) * r, 0.0, 1.0)  # borda suave de 1 px
    out = np.zeros((size, size, 4), np.uint8)
    out[..., :3] = np.clip(rgb * 255.0 * alpha[..., None], 0, 255).astype(np.uint8)
    out[..., 3] = (alpha * 255.0).astype(np.uint8)
    out = np.ascontiguousarray(out)
    img = QImage(out.data, size, size, 4 * size, QImage.Format.Format_RGBA8888_Premultiplied).copy()
    _WHEEL_CACHE[size] = img
    return img


class ColorWheel(QWidget):
    """Disco de cor com um ponto arrastável, sempre dentro do círculo unitário."""

    valueChanged = Signal(float, float)
    released = Signal()
    resetRequested = Signal()

    def __init__(self, size: int = 112, parent=None):
        super().__init__(parent)
        self._size = size
        self._v = (0.0, 0.0)
        self._drag = False
        self._fine = None
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def value(self) -> tuple[float, float]:
        return self._v

    def setValue(self, x: float, y: float, emit: bool = False) -> None:
        r = math.hypot(x, y)
        if r > 1.0:
            x, y = x / r, y / r
        v = (float(x), float(y))
        if v != self._v:
            self._v = v
            self.update()
            if emit:
                self.valueChanged.emit(*v)

    def radius(self) -> float:
        return self._size / 2.0 - 4.0

    def center(self) -> QPointF:
        return QPointF(self._size / 2.0, self._size / 2.0)

    def value_at(self, pos: QPointF) -> tuple[float, float]:
        c, r = self.center(), self.radius()
        return (pos.x() - c.x()) / r, -(pos.y() - c.y()) / r

    def puck_pos(self) -> QPointF:
        c, r = self.center(), self.radius()
        return QPointF(c.x() + self._v[0] * r, c.y() - self._v[1] * r)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c, r = self.center(), self.radius()
        d = int(round(r * 2))
        p.drawImage(QRectF(c.x() - r, c.y() - r, d, d), _wheel_image(d))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 110), 1))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(255, 255, 255, 55), 1))
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        p.drawEllipse(c, r * 0.5, r * 0.5)
        pk = self.puck_pos()
        active = math.hypot(*self._v) > 1e-4
        p.setPen(QPen(QColor("#1b1205"), 3))
        p.drawEllipse(pk, 6, 6)
        p.setPen(QPen(QColor(theme.ACCENT_HI) if active else QColor("#f6eee2"), 2))
        p.setBrush(hue_color(wheel_hue(*self._v), math.hypot(*self._v), 1.0) if active else QColor(0, 0, 0, 0))
        p.drawEllipse(pk, 6, 6)
        p.end()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._drag = True
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._fine = (e.position(), self._v)
        else:
            self._fine = None
            self.setValue(*self.value_at(e.position()), emit=True)

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        if self._fine is not None:
            p0, v0 = self._fine
            r = self.radius()
            d = e.position() - p0
            self.setValue(v0[0] + d.x() / r * 0.15, v0[1] - d.y() / r * 0.15, emit=True)
        else:
            self.setValue(*self.value_at(e.position()), emit=True)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.released.emit()

    def mouseDoubleClickEvent(self, e):
        self.resetRequested.emit()

    def wheelEvent(self, e):
        e.ignore()


class WheelRow(ParamRow):
    """Roda de cor de um parâmetro "wheel" (valor [x, y] no disco unitário)."""

    def __init__(self, param, store, parent=None):
        super().__init__(param, store, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(self._label(_(param.label)))
        top.addStretch(1)
        self.text = QLabel()
        self.text.setObjectName("Faint")
        top.addWidget(self.text)
        lay.addLayout(top)
        self.top = top
        row = QHBoxLayout()
        row.addStretch(1)
        self.wheel = ColorWheel()
        self.wheel.setToolTip(_(param.tip) if param.tip else
                              _("Arraste para dar cor. Duplo clique zera. Shift + arrastar: ajuste fino."))
        self.wheel.valueChanged.connect(lambda x, y: self.store.set(param.key, [x, y]))
        self.wheel.released.connect(self.store.commit)
        self.wheel.resetRequested.connect(self._reset)
        row.addWidget(self.wheel)
        row.addStretch(1)
        lay.addLayout(row)
        self.refresh()

    def _reset(self) -> None:
        self.store.set(self.param.key, [0.0, 0.0])
        self.store.commit()

    def refresh(self) -> None:
        x, y = self.store.shown(self.param.key)
        self.wheel.setValue(x, y)
        amt = math.hypot(x, y)
        if amt < 1e-4:
            self.text.setText(_("neutro"))
        else:
            self.text.setText(f"{wheel_hue(x, y):.0f}° • {amt * 100:.0f}%")


class ColorChip(QAbstractButton):
    """Bolinha de cor (faixa do HSL); um ponto claro indica que a faixa tem ajuste."""

    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self.color = color
        self.marked = False
        self.setCheckable(True)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sizeHint(self) -> QSize:
        return QSize(24, 24)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(12, 12)
        if self.isChecked():
            p.setPen(QPen(QColor(theme.ACCENT_HI), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 10.5, 10.5)
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.setBrush(self.color)
        p.drawEllipse(c, 7.5, 7.5)
        if self.marked:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#f6eee2"))
            p.drawEllipse(QPointF(18.5, 5.5), 2.6, 2.6)
        p.end()


def make_row(param: params.Param, store: ParamStore) -> ParamRow:
    if param.kind in ("float", "int"):
        return NumberRow(param, store)
    if param.kind == "bool":
        return BoolRow(param, store)
    if param.kind == "choice":
        return ChoiceRow(param, store)
    if param.kind == "color":
        return ColorRow(param, store)
    if param.kind == "file":
        return LutRow(param, store)
    if param.kind == "wheel":
        return WheelRow(param, store)
    raise ValueError(param.kind)


# ------------------------------------------------------------------ seção recolhível
class SectionCard(QFrame):
    def __init__(self, section: params.Section, store: ParamStore, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.section = section
        self.store = store
        self.setObjectName("Card")
        self.setStyleSheet(f"QFrame#Card {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 12px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(4)
        head = QWidget()
        head.setCursor(Qt.CursorShape.PointingHandCursor)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        self.chev = QLabel()
        self.chev.setFixedSize(16, 16)
        hl.addWidget(self.chev)
        tl = QVBoxLayout()
        tl.setSpacing(0)
        title = QLabel(_(section.title))
        title.setObjectName("PanelTitle")
        title.setMinimumWidth(60)
        tl.addWidget(title)
        if section.subtitle:
            sub = QLabel(_(section.subtitle))
            sub.setObjectName("Faint")
            sub.setWordWrap(True)
            sub.setMinimumWidth(60)
            tl.addWidget(sub)
        hl.addLayout(tl, 1)
        rst = QToolButton()
        rst.setObjectName("Flat")
        rst.setIcon(icons.icon("reset", theme.FAINT, 16))
        rst.setToolTip(_("Restaurar os valores padrão desta seção"))
        rst.clicked.connect(self._reset)
        hl.addWidget(rst)
        self.switch = None
        if section.toggle:
            self.switch = ToggleSwitch()
            self.switch.setToolTip(_("Ligar ou desligar esta seção"))
            self.switch.toggled.connect(lambda on: self.store.set(section.toggle, bool(on)))
            hl.addWidget(self.switch)
        head.mousePressEvent = lambda e: self.set_expanded(not self.expanded)
        lay.addWidget(head)
        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 6, 0, 0)
        bl.setSpacing(4)
        self.rows: list[ParamRow] = []
        self._chips: dict[str, ColorChip] = {}
        self.hsl_color = ""
        if section.layout == "hsl":
            self._build_hsl_chips(bl)
        for p in section.params:
            if p.key == section.toggle:
                continue
            row = make_row(p, store)
            self.rows.append(row)
            bl.addWidget(row)
        if section.layout == "hsl" and self._chips:
            self.set_hsl_color(next(iter(self._chips)))
        lay.addWidget(self.body)
        self._fx = QGraphicsOpacityEffect(self.body)
        self._fx.setOpacity(1.0)
        self.body.setGraphicsEffect(self._fx)
        self.expanded = True
        self.set_expanded(expanded)
        self.refresh()

    def set_expanded(self, on: bool) -> None:
        self.expanded = on
        self.body.setVisible(on)
        pm = icons.icon("chevron", theme.MUTED, 16).pixmap(16, 16)
        if not on:
            from PySide6.QtGui import QTransform
            pm = pm.transformed(QTransform().rotate(-90), Qt.TransformationMode.SmoothTransformation)
        self.chev.setPixmap(pm)

    def set_advanced(self, show: bool) -> None:
        if self._chips:
            return
        for r in self.rows:
            if r.param.advanced:
                r.setVisible(show)

    # ------------------------------------------------------------ HSL (cor por faixa)
    def _build_hsl_chips(self, layout: QVBoxLayout) -> None:
        from .. import editparams
        row = QHBoxLayout()
        row.setSpacing(2)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, label, hue in editparams.HSL_COLORS:
            chip = ColorChip(hue_color(hue, 0.85, 0.95))
            chip.setToolTip(_(label))
            chip.clicked.connect(lambda _checked=False, k=key: self.set_hsl_color(k))
            group.addButton(chip)
            row.addWidget(chip)
            self._chips[key] = chip
        row.addStretch(1)
        layout.addLayout(row)
        self._hsl_names = {key: label for key, label, _hue in editparams.HSL_COLORS}
        self.hsl_label = QLabel()
        self.hsl_label.setObjectName("Muted")
        layout.addWidget(self.hsl_label)

    def set_hsl_color(self, key: str) -> None:
        """Mostra só as linhas (matiz, saturação, luminância) da faixa de cor escolhida."""
        if key not in self._chips:
            return
        self.hsl_color = key
        self._chips[key].setChecked(True)
        self.hsl_label.setText(_(self._hsl_names[key]))
        prefix = f"hsl_{key}_"
        for r in self.rows:
            r.setVisible(r.param.key.startswith(prefix))

    def _refresh_chips(self) -> None:
        for key, chip in self._chips.items():
            prefix = f"hsl_{key}_"
            marked = any(abs(float(self.store.shown(p.key))) > 1e-6 for p in self.section.params
                         if p.key.startswith(prefix))
            if marked != chip.marked:
                chip.marked = marked
                chip.update()

    def _reset(self) -> None:
        for p in self.section.params:
            if p.key == self.section.toggle:
                continue
            self.store.set(p.key, list(p.default) if p.kind in params.LIST_KINDS else p.default, record=False)
        self.store.commit()

    def refresh(self, key: str = "*") -> None:
        for r in self.rows:
            if key == "*" or r.param.key == key:
                r.refresh()
        if self._chips:
            self._refresh_chips()
        if self.switch is not None and key in ("*", self.section.toggle):
            on = bool(self.store.get(self.section.toggle))
            self.switch.blockSignals(True)
            self.switch.setChecked(on)
            self.switch.blockSignals(False)
            self.switch.update()
            self._fx.setOpacity(1.0 if on else 0.45)

    def keys(self) -> set[str]:
        return {p.key for p in self.section.params}


# ------------------------------------------------------------------ botões segmentados
class Segmented(QFrame):
    changed = Signal(str)

    def __init__(self, items: list[tuple[str, str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("SegBox")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        for key, text, tip in items:
            b = QToolButton()
            b.setObjectName("Seg")
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[key] = b
            b.clicked.connect(lambda _checked=False, k=key: self.changed.emit(k))

    def set_current(self, key: str) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)


# ------------------------------------------------------------------ histograma
class Histogram(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(86)
        self.h = None

    def set_image(self, img: np.ndarray | None) -> None:
        if img is None:
            self.h = None
        else:
            sub = img[::6, ::6]
            if sub.dtype == np.float32:  # leitura de log com super-brancos (`media.float_input`)
                sub = np.clip(sub * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
            elif sub.dtype != np.uint8:
                sub = (sub >> 8).astype(np.uint8)
            hs = []
            for c in range(3):
                h = np.bincount(sub[..., c].ravel() >> 2, minlength=64).astype(np.float32)
                hs.append(h)
            hs = np.sqrt(np.array(hs))
            m = hs[:, 1:-1].max() or 1.0
            self.h = np.clip(hs / m, 0, 1)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor("#100f0e"))
        p.drawRoundedRect(r, 9, 9)
        p.setPen(QPen(QColor(255, 255, 255, 14), 1))
        for i in range(1, 4):
            x = r.left() + r.width() * i / 4
            p.drawLine(QPointF(x, r.top() + 6), QPointF(x, r.bottom() - 6))
        if self.h is not None:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            cols = [QColor(235, 80, 70, 150), QColor(80, 200, 120, 150), QColor(70, 130, 245, 160)]
            w = r.width() - 12
            hh = r.height() - 14
            for c in range(3):
                path = QPainterPath()
                path.moveTo(r.left() + 6, r.bottom() - 6)
                n = len(self.h[c])
                for i, v in enumerate(self.h[c]):
                    path.lineTo(r.left() + 6 + w * i / (n - 1), r.bottom() - 6 - hh * float(v))
                path.lineTo(r.left() + 6 + w, r.bottom() - 6)
                path.closeSubpath()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(cols[c])
                p.drawPath(path)
        p.end()


# ------------------------------------------------------------------ linha do tempo
class Timeline(QWidget):
    seek = Signal(int)
    scrubbing = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.total = 1
        self.fps = 24.0
        self.pos = 0
        self.inp = None
        self.out = None
        self.markers: list[tuple[int, str, str]] = []  # (quadro, cor, nome): marcadores da montagem, só para ver
        self._hover_x = None
        self._drag = False
        self.setMinimumHeight(34)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_markers(self, items) -> None:
        """Marcadores mostrados na barra (editar é no modo Edição): [(quadro, cor "#rrggbb", nome)]."""
        self.markers = [(int(f), str(col), str(name)) for f, col, name in items]
        self.update()

    def marker_near(self, x: float, tol: float = 5.0) -> tuple[int, str] | None:
        """(quadro, nome) do marcador mais perto de x, se estiver a até `tol` pixels."""
        best = None
        for f, _col, name in self.markers:
            d = abs(self._x(f) - x)
            if d <= tol and (best is None or d < best[0]):
                best = (d, f, name)
        return (best[1], best[2]) if best else None

    def set_media(self, total: int, fps: float) -> None:
        self.total = max(1, total)
        self.fps = fps or 24.0
        self.pos = 0
        self.inp = self.out = None
        self.update()

    def set_pos(self, frame: int) -> None:
        self.pos = frame
        self.update()

    def set_inout(self, a, b) -> None:
        self.inp, self.out = a, b
        self.update()

    def _x(self, f: float) -> float:
        return 10 + (self.width() - 20) * f / max(1, self.total - 1)

    def _f(self, x: float) -> int:
        return int(round(min(max((x - 10) / max(1, self.width() - 20), 0), 1) * (self.total - 1)))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2 + 2
        x0, x1 = 10, self.width() - 10
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.PANEL3))
        p.drawRoundedRect(QRectF(x0, cy - 3, x1 - x0, 6), 3, 3)
        if self.inp is not None or self.out is not None:
            a = self._x(self.inp or 0)
            b = self._x(self.out if self.out is not None else self.total - 1)
            p.setBrush(QColor(240, 166, 58, 70))
            p.drawRoundedRect(QRectF(a, cy - 7, max(b - a, 2), 14), 4, 4)
            p.setBrush(QColor(theme.ACCENT))
            for xx in (a, b):
                p.drawRect(QRectF(xx - 1, cy - 9, 2, 18))
        xp = self._x(self.pos)
        p.setBrush(QColor(theme.ACCENT_DIM))
        p.drawRoundedRect(QRectF(x0, cy - 3, max(xp - x0, 0), 6), 3, 3)
        for f, col, _name in self.markers:
            if 0 <= f < self.total:
                xm = self._x(f)
                tri = QPainterPath()
                tri.moveTo(xm - 3.5, cy - 11)
                tri.lineTo(xm + 3.5, cy - 11)
                tri.lineTo(xm, cy - 5)
                tri.closeSubpath()
                p.setBrush(QColor(col))
                p.drawPath(tri)
        if self._hover_x is not None and not self._drag:
            near = self.marker_near(self._hover_x)
            f = near[0] if near else self._f(self._hover_x)
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRect(QRectF(self._x(f) - 0.5, cy - 8, 1, 16))
            txt = timecode(f, self.fps) + (f"  •  {near[1]}" if near and near[1] else "")
            fm = QFontMetrics(theme.font(8))
            tw = fm.horizontalAdvance(txt) + 12
            bx = min(max(self._x(f) - tw / 2, 0), self.width() - tw)
            p.setBrush(QColor(theme.PANEL3))
            p.drawRoundedRect(QRectF(bx, 0, tw, 15), 4, 4)
            p.setPen(QColor(theme.TEXT))
            p.setFont(theme.font(8))
            p.drawText(QRectF(bx, 0, tw, 15), Qt.AlignmentFlag.AlignCenter, txt)
            p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f6eee2"))
        p.setPen(QPen(QColor(theme.ACCENT), 2))
        p.drawEllipse(QPointF(xp, cy), 6, 6)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self.scrubbing.emit(True)
            near = self.marker_near(e.position().x())
            self.seek.emit(near[0] if near else self._f(e.position().x()))  # clique num marcador: vai até ele

    def mouseMoveEvent(self, e):
        self._hover_x = e.position().x()
        if self._drag:
            self.seek.emit(self._f(e.position().x()))
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.scrubbing.emit(False)
            near = self.marker_near(e.position().x())
            self.seek.emit(near[0] if near else self._f(e.position().x()))

    def leaveEvent(self, _event):
        self._hover_x = None
        self.update()


def timecode(frame: int, fps: float) -> str:
    fps = fps or 24.0
    nominal = max(1, int(round(fps)))
    secs = frame / fps
    h = int(secs // 3600)
    m = int(secs % 3600 // 60)
    s = int(secs % 60)
    f = int(round(frame - math.floor(secs) * fps)) % nominal
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"
