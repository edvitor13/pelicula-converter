"""Máquina do tempo na janela (1.6, módulo "maquina_tempo"): ano e lugar, o motivo e a lista do que muda.

Nada acontece sem o "Aplicar": a janela mostra a linha da tabela (`maquina.py`) e cada ajuste que vai mudar (de →
para). Aplicar troca os valores do look num passo só de desfazer (`ParamStore.set_all`) e avisa na barra de status.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox, QVBoxLayout)

from .. import maquina, params
from ..i18n import _


def _show(key: str, value) -> str:
    p = params.PARAMS[key]
    if p.kind == "bool":
        return _("ligado") if value else _("desligado")
    if p.kind == "choice":
        return next((_(label) for v, label in p.choices if v == value), str(value))
    if p.kind == "float":
        if p.percent:
            return f"{float(value) * 100:.0f}%"
        return f"{float(value):g}"
    return str(value)


class TimeMachineDialog(QDialog):
    def __init__(self, win, year: int = 1975, venue: str = "caseiro"):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(_("Máquina do tempo"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        intro = QLabel(_("Escolha o ano e onde o filme passava: a máquina preenche bitola, filme, cor, grão, "
                         "projeção, desgaste e moldura como eram na época. Tudo continua editável."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.year = QSpinBox()
        self.year.setRange(maquina.YEAR_MIN, maquina.YEAR_MAX)
        self.year.setValue(year)
        form.addRow(_("Ano"), self.year)
        self.venue = QComboBox()
        for key, label in maquina.VENUES:
            self.venue.addItem(_(label), key)
        self.venue.setCurrentIndex(max(0, self.venue.findData(venue)))
        form.addRow(_("Onde passava"), self.venue)
        lay.addLayout(form)
        self.title = QLabel()
        self.title.setObjectName("PanelTitle")
        lay.addWidget(self.title)
        self.reason = QLabel()
        self.reason.setWordWrap(True)
        lay.addWidget(self.reason)
        self.diff = QLabel()
        self.diff.setWordWrap(True)
        self.diff.setObjectName("Faint")
        lay.addWidget(self.diff)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_apply = self.buttons.addButton(_("Aplicar"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.year.valueChanged.connect(self.refresh)
        self.venue.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def current(self) -> tuple[int, str]:
        return int(self.year.value()), str(self.venue.currentData())

    def new_values(self) -> dict:
        year, venue = self.current()
        return maquina.apply(self.win.store.values, year, venue)

    def refresh(self) -> None:
        year, venue = self.current()
        row = maquina.row_for(year, venue)
        self.title.setText(f"{_(row.title)} ({row.start}–{row.end})")
        text = _(row.reason)
        if row.cadence:
            text += "\n" + _("Sugestão: no modo Edição, a manivela de {n} qps nos clipes (Câmera de cinema).").format(
                n=row.cadence)
        self.reason.setText(text)
        diff = maquina.changes(self.win.store.values, self.new_values())
        if not diff:
            self.diff.setText(_("O look já está assim: nada muda."))
        else:
            lines = [f"{_(params.PARAMS[k].label)}: {_show(k, a)} → {_show(k, b)}" for k, a, b in diff]
            self.diff.setText(_("Vai mudar:") + "\n" + "\n".join(lines))
        self.btn_apply.setEnabled(bool(diff))


def open_dialog(win) -> bool:
    """Mostra a janela; aplicado, troca o look num passo só de desfazer e avisa. Devolve se aplicou."""
    dlg = TimeMachineDialog(win, *getattr(win, "_time_machine_last", (1975, "caseiro")))
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    year, venue = dlg.current()
    win._time_machine_last = (year, venue)
    n = len(maquina.changes(win.store.values, dlg.new_values()))
    win.store.set_all(dlg.new_values(), record=True)
    row = maquina.row_for(year, venue)
    win.statusBar().showMessage(_("Máquina do tempo: {ano}, {epoca} ({n} ajustes; Ctrl+Z desfaz).").format(
        ano=year, epoca=_(row.title), n=n), 10000)
    return True
