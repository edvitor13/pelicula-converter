"""Tempo do clipe na interface: rampa de velocidade (presets), reverso e congelar um quadro.

- `TempoPanel`: entra no fim do cartão "Velocidade" do inspetor do clipe (abaixo da velocidade e do "Congelar
  quadro"). "Reverso" toca o clipe de trás para a frente (o som junto). Escolhe um preset de rampa
  (`timemap.PRESETS`), a intensidade e a duração de cada transição e aplica no trecho que o clipe mostra; "Tirar a
  rampa" volta à velocidade constante. Rampa e reverso combinam: a rampa fica presa à imagem, então no reverso o
  trecho lento continua no mesmo pedaço do vídeo (uma entrada lenta vira uma saída lenta).
- `add_clip_actions`: os mesmos comandos no menu do botão direito de um clipe na linha do tempo, mais "Congelar
  este quadro…" (também no Shift+F do modo Edição: `freeze_at`), que divide o clipe no cursor e põe ali um quadro
  parado de `freeze_seconds` (2 s; a caixa do menu muda o valor), inserindo ou sobrescrevendo conforme o botão
  "Inserir" da linha do tempo.

Toda edição passa pelo `TimelineModel` (um passo do desfazer cada); a conta do tempo é só de `timemap` e
`timeline.Sequence`.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QMenu, QPushButton,
                               QVBoxLayout, QWidget)

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
        self.reverse = QCheckBox(_("Reverso"))
        self.reverse.setObjectName("reverse")
        self.reverse.setToolTip(_("Toca o clipe de trás para a frente, do fim para o começo. O som ligado do mesmo "
                                  "arquivo também toca ao contrário, junto com a imagem."))
        self.reverse.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reverse.toggled.connect(self._reverse_toggled)
        lay.addWidget(self.reverse)
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
        for w in (self.preset, self.amount, self.ramp_s, self.btn_apply, self.reverse):
            w.setEnabled(not hold)
        self.reverse.blockSignals(True)
        self.reverse.setChecked(c is not None and c.reverse)
        self.reverse.blockSignals(False)
        self.btn_clear.setEnabled(c is not None and bool(c.ramp))
        if c is None:
            self.status.setText("")
        elif hold:
            self.status.setText(_("Imagens paradas e quadros congelados não têm rampa nem reverso."))
        elif c.ramp:
            self.status.setText(_("Com {rampa}. O som acompanha a imagem, sem mudar o tom.").format(
                rampa=ramp_summary(c)))
        else:
            self.status.setText(_("Velocidade constante."))

    def _reverse_toggled(self, on: bool) -> None:
        c = self._clip()
        if c is not None and c.reverse != on and not self.model.set_reverse(c.id, on):
            self.refresh()

    def apply(self) -> bool:
        c = self._clip()
        return c is not None and self.model.apply_ramp_preset(c.id, self.preset.currentData(), self.amount.value(),
                                                              self.ramp_s.value())

    def clear(self) -> bool:
        c = self._clip()
        return c is not None and self.model.set_ramp(c.id, [])


def freeze_seconds(canvas) -> float:
    from .edit_model import FREEZE_SECONDS
    return float(getattr(canvas, "freeze_seconds", FREEZE_SECONDS))


def freeze_at(canvas, cid: str | None = None, ask: bool = False) -> str | None:
    """Congela no cursor o quadro do clipe `cid` (ou do vídeo de cima): insere ou sobrescreve conforme o botão
    "Inserir" da linha do tempo. Com `ask`, pergunta antes a duração (e guarda para as próximas vezes)."""
    m = canvas.model
    if m.seq.freeze_target(cid, canvas.playhead) is None:
        return None
    if ask:
        val, ok = QInputDialog.getDouble(canvas, _("Congelar este quadro"),
                                         _("Duração do quadro parado, em segundos:"), freeze_seconds(canvas),
                                         0.1, 60.0, 1)
        if not ok:
            return None
        canvas.freeze_seconds = val
    return m.freeze_frame(cid, canvas.playhead, freeze_seconds(canvas), insert=canvas.insert_mode)


def add_clip_actions(menu: QMenu, canvas, clip) -> None:
    """Reverso, rampa de velocidade e congelar no menu do botão direito de um clipe."""
    m = canvas.model
    holds = m.seq._holds(clip)
    rev = menu.addAction(_("Reverso"))
    rev.setObjectName("reverse")
    rev.setCheckable(True)
    rev.setChecked(clip.reverse)
    rev.setEnabled(not holds)
    rev.toggled.connect(lambda on: m.set_reverse(clip.id, on))
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
    frz = menu.addAction(_("Congelar este quadro…") + " (Shift+F)", lambda: freeze_at(canvas, clip.id, ask=True))
    frz.setObjectName("freeze_here")
    frz.setEnabled(m.seq.freeze_target(clip.id, canvas.playhead) is not None)
    frz.setToolTip(_("Divide o clipe no cursor e põe ali o quadro parado pelo tempo escolhido; o som fica em "
                     "silêncio nesse trecho."))


__all__ = ["TempoPanel", "add_clip_actions", "freeze_at", "freeze_seconds", "ramp_summary"]
