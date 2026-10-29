"""Fotômetro da película na prévia (1.6, módulo Beta "fotometro"; a conta é de `fotometro.py`).

Um botão na barra da prévia (ao lado da zebra e da falsa cor) liga uma camada de `preview_tools.PreviewTools`: cada
parte da imagem pintada pela zona em que cai na curva do negativo escolhido (sem detalhe, pé, reta, ombro,
estourado; o cinza de 18% em verde). Ao lado do botão, o negativo e a latitude em stops. A setinha do botão tem
"Ler um ponto": o próximo clique na imagem mede ali (média de 5 × 5 pixels da luz da cena) e a barra de status mostra
a leitura. Só na tela: a receita do quadro e a exportação não sabem que isto existe.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QMenu, QToolButton, QWidget

from .. import fotometro
from ..i18n import _
from . import theme

SPOT_RADIUS = 2  # 5 × 5 pixels


def meter_icon(color: str = theme.TEXT, size: int = 18) -> QIcon:
    """Um fotômetro de mão: o corpo, o mostrador com o ponteiro e a esfera de luz incidente."""
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size * scale / 24.0, size * scale / 24.0)
        pen = QPen(QColor(color), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(5.5, 7.5, 13, 14), 2.5, 2.5)
        p.drawArc(QRectF(8.5, 2.0, 7, 7), 0, 180 * 16)
        p.drawArc(QRectF(8, 10.5, 8, 8), 30 * 16, 120 * 16)
        p.drawLine(QPointF(12, 17), QPointF(14.5, 12.5))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    return ic


class FilmMeter:
    """O botão, o texto da latitude, a camada da prévia e a leitura de um ponto."""

    def __init__(self, win, tools):
        self.win = win
        self.tools = tools
        self._picking = False
        self.last_reading: fotometro.Reading | None = None
        self.last_latitude: fotometro.Latitude | None = None
        self._build()
        tools.add("fotometro", self.layer)
        win.viewer.picked.connect(self._picked)
        win.viewer.pickCanceled.connect(self._pick_canceled)

    def _build(self) -> None:
        win = self.win
        b = QToolButton()
        b.setObjectName("Flat")
        b.setIcon(meter_icon())
        b.setIconSize(QSize(18, 18))
        b.setText(_("Fotômetro"))
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setCheckable(True)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(self._tip())
        b.toggled.connect(self._toggled)
        menu = QMenu(b)
        self.act_spot = menu.addAction(_("Ler um ponto (clique na imagem)"), self.start_spot)
        b.setMenu(menu)
        b.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn = b
        self.info = QLabel()
        self.info.setObjectName("Faint")
        self.info.setVisible(False)
        bar = win.findChild(QWidget, "ViewerBar")
        if bar is not None and bar.layout() is not None:
            bar.layout().addWidget(self.btn)
            bar.layout().addWidget(self.info)

    @staticmethod
    def _tip() -> str:
        names = "; ".join(_(name) for _z, _c, name in fotometro.ZONES)
        return _("Fotômetro da película (só na tela): onde cada parte da imagem cai na curva do negativo do "
                 "Laboratório, com a revelação, a película vencida e a pré-exposição — {zonas}; o cinza de 18% em "
                 "verde. Sem o Laboratório, vale o negativo padrão. A setinha lê um ponto.").format(zonas=names)

    # ------------------------------------------------------------ estado
    def values(self, ctx=None) -> dict:
        """Os ajustes do look que valem: os do quadro (com as chaves) ou, sem película na prévia, os do painel."""
        v = ctx.values if ctx is not None else None
        return v if v is not None else self.win.store.values

    def _toggled(self, on: bool) -> None:
        self.info.setVisible(bool(on) and not self.btn.isHidden())
        if not on and self._picking:
            self._picking = False
            self.win.viewer.cancel_pick()
        self._sync_info(fotometro.latitude(self.values()))
        self.tools.refresh()

    def _sync_info(self, lat: fotometro.Latitude) -> None:
        self.last_latitude = lat
        name = fotometro.negative_name(lat.negative)
        text = _("{filme}: {latitude}").format(filme=name, latitude=fotometro.latitude_text(lat))
        if lat.default:
            text += " " + _("(negativo padrão: o Laboratório está desligado)")
        self.info.setText(text)
        self.info.setToolTip(_("Trecho reto do negativo em stops da cena em relação ao cinza de 18% (a camada mais "
                               "estreita); o detalhe acaba em {a} e {b} stops.").format(
            a=fotometro.signed(lat.lo_detail), b=fotometro.signed(lat.hi_detail)))

    # ------------------------------------------------------------ camada
    def layer(self, ctx):
        if not self.btn.isChecked() or self.btn.isHidden():
            return None
        lat = fotometro.latitude(self.values(ctx))
        self._sync_info(lat)
        light = ctx.light()
        return fotometro.false_color(fotometro.stops(light[..., :3]), lat, light[..., 3])

    # ------------------------------------------------------------ leitura de um ponto
    def start_spot(self) -> bool:
        win = self.win
        if getattr(win, "cur", None) is None:
            win.statusBar().showMessage(_("Abra um vídeo para medir um ponto."), 5000)
            return False
        if not self.btn.isChecked():
            self.btn.setChecked(True)
        self._picking = True
        win.viewer.start_pick()
        win.statusBar().showMessage(_("Clique no ponto que você quer medir (Esc cancela)."), 6000)
        return True

    def _pick_canceled(self) -> None:
        self._picking = False

    def read_at(self, fx: float, fy: float) -> fotometro.Reading | None:
        """A leitura no ponto (fração da imagem, y para baixo) do quadro da prévia."""
        win = self.win
        if getattr(win, "cur", None) is None:
            return None
        from .preview_tools import Context
        ctx = Context(win, win.frame_recipe())
        light = ctx.light()
        h, w = light.shape[:2]
        x = min(max(int(fx * w), 0), w - 1)
        y = min(max(int(fy * h), 0), h - 1)
        r = SPOT_RADIUS
        patch = light[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, 4).astype(np.float64)
        cover = patch[:, 3]
        if cover.sum() <= 1e-6:
            return None
        lin = (patch[:, :3] * cover[:, None]).sum(0) / cover.sum()
        return fotometro.spot(lin, self.values(ctx))

    def _picked(self, fx: float, fy: float) -> None:
        if not self._picking:
            return
        self._picking = False
        reading = self.read_at(fx, fy)
        status = self.win.statusBar()
        if reading is None:
            status.showMessage(_("Clique dentro da imagem."), 5000)
            return
        self.last_reading = reading
        status.showMessage(_("Fotômetro: {leitura}").format(leitura=fotometro.spot_text(reading)), 15000)

    # ------------------------------------------------------------ módulo
    def module_tools(self) -> list:
        return [self.btn]

    def apply_module(self, on: bool) -> None:
        self.btn.setVisible(on)
        if not on and self.btn.isChecked():
            self.btn.setChecked(False)
        self.info.setVisible(on and self.btn.isChecked())
