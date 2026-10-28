"""Tempo do clipe na interface: rampa de velocidade (presets), reverso e congelar um quadro.

- `TempoPanel`: entra no fim do cartão "Velocidade" do inspetor do clipe (abaixo da velocidade e do "Congelar
  quadro"). Escolhe um preset de rampa (`timemap.PRESETS`), a intensidade e a duração de cada transição e aplica
  no trecho que o clipe mostra; "Tirar a rampa" volta à velocidade constante.
- `add_clip_actions`: os mesmos comandos no menu do botão direito de um clipe na linha do tempo.

Toda edição passa pelo `TimelineModel` (um passo do desfazer cada); a conta do tempo é só de `timemap` e
`timeline.Sequence`.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from .. import timemap
from ..i18n import _, fmt_decimal
from .widgets import FilmSlider


def ramp_summary(clip) -> str:
    """Texto curto da rampa do clipe: "rampa de 2,5× a 0,4×"."""
    if not clip.ramp:
        return ""
    rs = [r * clip.speed for _s, r in clip.ramp]
    return _("rampa de {de}× a {ate}×").format(de=fmt_decimal(max(rs), 2), ate=fmt_decimal(min(rs), 2))


class TempoPanel(QWidget):
    """Rampa de velocidade do clipe escolhido (`clip_id()`), no cartão "Velocidade" do inspetor."""

    def __init__(self, model, clip_id: Callable[[], str | None], parent=None):
        super().__init__(parent)
        self.model = model
        self.clip_id = clip_id
        self.setObjectName("TempoPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(4)
        head = QLabel(_("Rampa de velocidade"))
        head.setObjectName("Muted")
        lay.addWidget(head)
        self.preset = QComboBox()
        self.preset.setObjectName("ramp_preset")
        for pid, label in timemap.PRESETS:
            self.preset.addItem(_(label), pid)
        self.preset.setToolTip(_("A forma da rampa. Ela fica presa à imagem: aparar, dividir e mudar a velocidade "
                                 "mantêm a rampa no mesmo trecho do vídeo."))
        lay.addWidget(self.preset)
        self.amount, self.amount_text = self._slider(lay, _("Intensidade"), 0.1, 1.0, 0.05, timemap.AMOUNT_DEFAULT,
                                                     _("Quanto o trecho lento fica lento e o rápido fica rápido "
                                                       "(100% = 4× e 0,25×)."))
        self.ramp_s, self.ramp_text = self._slider(lay, _("Transição"), 0.1, 3.0, 0.1, timemap.RAMP_S_DEFAULT,
                                                   _("Duração de cada mudança de velocidade, em segundos do vídeo."))
        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_apply = QPushButton(_("Aplicar rampa"))
        self.btn_apply.setObjectName("ramp_apply")
        self.btn_apply.clicked.connect(self.apply)
        self.btn_clear = QPushButton(_("Tirar a rampa"))
        self.btn_clear.setObjectName("ramp_clear")
        self.btn_clear.clicked.connect(self.clear)
        for b in (self.btn_apply, self.btn_clear):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(b)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("Faint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self._texts()
        self.refresh()

    def _slider(self, lay, label: str, lo: float, hi: float, step: float, default: float, tip: str):
        top = QHBoxLayout()
        lab = QLabel(label)
        lab.setObjectName("Muted")
        top.addWidget(lab)
        top.addStretch(1)
        text = QLabel()
        text.setObjectName("Faint")
        top.addWidget(text)
        lay.addLayout(top)
        s = FilmSlider(lo, hi, step, default)
        s.setToolTip(tip)
        s.setValue(default)
        s.valueChanged.connect(lambda _v: self._texts())
        s.resetRequested.connect(lambda: (s.setValue(default), self._texts()))
        lay.addWidget(s)
        return s, text

    def _texts(self) -> None:
        self.amount_text.setText(f"{self.amount.value() * 100:.0f}%")
        self.ramp_text.setText(fmt_decimal(self.ramp_s.value(), 1) + " s")

    def _clip(self):
        cid = self.clip_id()
        return self.model.seq.find(cid) if cid else None

    def refresh(self) -> None:
        c = self._clip()
        hold = c is None or self.model.seq._holds(c)
        for w in (self.preset, self.amount, self.ramp_s, self.btn_apply):
            w.setEnabled(not hold)
        self.btn_clear.setEnabled(c is not None and bool(c.ramp))
        if c is None:
            self.status.setText("")
        elif hold:
            self.status.setText(_("Imagens paradas e quadros congelados não têm rampa."))
        elif c.ramp:
            self.status.setText(_("Com {rampa}. O som acompanha a imagem, sem mudar o tom.").format(
                rampa=ramp_summary(c)))
        else:
            self.status.setText(_("Velocidade constante."))

    def apply(self) -> bool:
        c = self._clip()
        return c is not None and self.model.apply_ramp_preset(c.id, self.preset.currentData(), self.amount.value(),
                                                              self.ramp_s.value())

    def clear(self) -> bool:
        c = self._clip()
        return c is not None and self.model.set_ramp(c.id, [])


def add_clip_actions(menu: QMenu, canvas, clip) -> None:
    """Rampa de velocidade (e os outros comandos de tempo) no menu do botão direito de um clipe."""
    m = canvas.model
    holds = m.seq._holds(clip)
    sub = menu.addMenu(_("Rampa de velocidade"))
    sub.setObjectName("ramp_menu")
    sub.setEnabled(not holds)
    for pid, label in timemap.PRESETS:
        act = sub.addAction(_(label), lambda p=pid: m.apply_ramp_preset(clip.id, p))
        act.setObjectName(f"ramp_{pid}")
    sub.addSeparator()
    off = sub.addAction(_("Tirar a rampa"), lambda: m.set_ramp(clip.id, []))
    off.setObjectName("ramp_off")
    off.setEnabled(bool(clip.ramp))


__all__ = ["TempoPanel", "add_clip_actions", "ramp_summary"]
