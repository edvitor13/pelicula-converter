"""Janela "Remover silêncios…" (módulo `silencios`): achar os trechos sem fala, revisar e tirar de uma vez.

A análise roda na fila de tarefas (`rangecut.find_silences` sobre o som mixado da montagem, ou só o dos clipes
escolhidos, numa cópia da sequência). A lista mostra cada trecho com uma caixa de marcar; clicar leva o cursor
ao trecho. "Tirar os marcados" passa por `TimelineModel.remove_ranges`: todas as faixas destravadas encostam
(o som continua junto da imagem), as chaves, os marcadores e as legendas acompanham, e tudo vira um passo de
desfazer só.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QProgressBar, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import jobs, rangecut, silences
from ..i18n import N_, _, fmt_decimal, fmt_int
from ..platforms import fmt_seconds
from . import icons, theme
from .job_bridge import bridge
from .subtitles_panel import fmt_time

JOB_KEY = "silencios"
PREFS = "silencios/"
COLS = (N_("Início"), N_("Fim"), N_("Duração"), N_("Nível"))


class SilencesDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.settings = getattr(win, "settings", None)
        self.job: jobs.Job | None = None
        self.found: list[silences.Silence] = []
        self.removed = 0                # quadros que "Tirar os marcados" tirou
        self.setWindowTitle(_("Remover silêncios"))
        self.resize(600, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        k = QLabel(_("REMOVER SILÊNCIOS"))
        k.setObjectName("Kicker")
        lay.addWidget(k)
        title = QLabel(_("Tirar os trechos sem fala"))
        title.setObjectName("PanelTitle")
        title.setStyleSheet("font-size: 14pt;")
        lay.addWidget(title)
        intro = QLabel(_("Mede o som da montagem e acha os trechos sem fala. Revise a lista e tire os marcados de "
                         "uma vez: o que vem depois encosta em todas as faixas destravadas, e o som continua junto "
                         "da imagem. Dá para desfazer num passo só."))
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        lay.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)
        self.scope = QComboBox()
        form.addRow(_("Ouvir:"), self.scope)
        self.threshold = QSpinBox()
        self.threshold.setRange(-60, -6)
        self.threshold.setSuffix(" dB")
        self.threshold.setToolTip(_("Quanto abaixo do volume típico do trecho conta como silêncio: −30 dB tira só o "
                                    "silêncio de verdade; perto de −15 dB tira também respiros e ruído baixo."))
        form.addRow(_("Limiar:"), self.threshold)
        self.min_duration = QDoubleSpinBox()
        self.min_duration.setRange(0.1, 10.0)
        self.min_duration.setSingleStep(0.1)
        self.min_duration.setDecimals(1)
        self.min_duration.setSuffix(" s")
        self.min_duration.setToolTip(_("Silêncios mais curtos que isto ficam (pausas naturais da fala)."))
        form.addRow(_("Duração mínima:"), self.min_duration)
        self.padding = QDoubleSpinBox()
        self.padding.setRange(0.0, 1.0)
        self.padding.setSingleStep(0.05)
        self.padding.setDecimals(2)
        self.padding.setSuffix(" s")
        self.padding.setToolTip(_("Quanto do silêncio fica encostado na fala de cada lado, para o corte não ficar "
                                  "seco."))
        form.addRow(_("Folga:"), self.padding)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.btn_analyze = QPushButton(_("Analisar"))
        self.btn_analyze.setIcon(icons.icon("volume", theme.TEXT, 15))
        self.btn_analyze.clicked.connect(self.analyze)
        row.addWidget(self.btn_analyze)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        row.addWidget(self.bar, 1)
        row.addStretch(1)
        lay.addLayout(row)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([_(c) for c in COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(lambda _it: self._sync())
        self.table.currentCellChanged.connect(lambda r, _c, _pr, _pc: self._preview(r))
        lay.addWidget(self.table, 1)
        marks = QHBoxLayout()
        self.btn_all = QPushButton(_("Marcar todos"))
        self.btn_all.clicked.connect(lambda: self.set_all(True))
        self.btn_none = QPushButton(_("Desmarcar todos"))
        self.btn_none.clicked.connect(lambda: self.set_all(False))
        marks.addWidget(self.btn_all)
        marks.addWidget(self.btn_none)
        marks.addStretch(1)
        lay.addLayout(marks)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_close = QPushButton(_("Fechar"))
        self.btn_close.clicked.connect(self.reject)
        buttons.addWidget(self.btn_close)
        self.btn_apply = QPushButton("  " + _("Tirar os marcados"))
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.setIcon(icons.icon("ripple_delete", "#1b1205", 15))
        self.btn_apply.clicked.connect(self.apply)
        buttons.addWidget(self.btn_apply)
        lay.addLayout(buttons)
        self._load_prefs()
        self._fill_scope()
        self._sync()

    # ------------------------------------------------------------ preferências (as do usuário, em QSettings)
    def _pref(self, key: str, default):
        value = self.settings.value(PREFS + key, None) if self.settings is not None else None
        try:
            return type(default)(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    def _load_prefs(self) -> None:
        self.threshold.setValue(self._pref("limiar", -30))
        self.min_duration.setValue(self._pref("minimo", 0.5))
        self.padding.setValue(self._pref("folga", 0.1))

    def _save_prefs(self) -> None:
        if self.settings is not None:
            for key, value in (("limiar", self.threshold.value()), ("minimo", self.min_duration.value()),
                               ("folga", self.padding.value())):
                self.settings.setValue(PREFS + key, value)

    def _fill_scope(self) -> None:
        self.scope.clear()
        self.scope.addItem(_("A montagem inteira"), "montagem")
        if self.win.model.selected_clips():
            self.scope.addItem(_("Os clipes escolhidos"), "selecao")

    # ------------------------------------------------------------ análise
    @property
    def busy(self) -> bool:
        return self.job is not None and self.job.active

    def analyze(self) -> jobs.Job | None:
        if self.busy:
            return self.job
        self._save_prefs()
        seq = self.win.model.seq.copy()   # o trabalho lê uma cópia (outra thread)
        ids = [c.id for c in self.win.model.selected_clips()] if self.scope.currentData() == "selecao" else None
        opts = dict(threshold=float(self.threshold.value()), min_duration=self.min_duration.value(),
                    padding=self.padding.value())

        def run(job: jobs.Job):
            job.report(_("Medindo o som da montagem…"))
            return rangecut.find_silences(seq, ids, cancel=job.cancel_event, **opts)

        self.found = []
        self._fill([])
        self.summary.setText("")
        self.job = bridge().submit(run, _("Silêncios da montagem"), kind=jobs.CPU, key=JOB_KEY,
                                   on_finished=self._analyzed)
        self._sync()
        return self.job

    def _analyzed(self, job: jobs.Job) -> None:
        if job is not self.job:
            return
        if job.state == jobs.CONCLUIDO:
            self.found = list(job.result or [])
            self._fill(self.found)
            if not self.found:
                self.summary.setText(_("Nenhum silêncio com essa regulagem."))
        elif job.state == jobs.ERRO:
            self.summary.setText(job.error)
        self._sync()

    def _fill(self, items: list[silences.Silence]) -> None:
        t = self.table
        t.blockSignals(True)
        t.setRowCount(len(items))
        for r, s in enumerate(items):
            first = QTableWidgetItem(fmt_time(s.start))
            first.setFlags(first.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            first.setCheckState(Qt.CheckState.Checked)
            cells = [first, QTableWidgetItem(fmt_time(s.end)), QTableWidgetItem(fmt_seconds(s.duration)),
                     QTableWidgetItem(_("{n} dB").format(n=fmt_decimal(s.level, 0)))]
            for c, item in enumerate(cells):
                t.setItem(r, c, item)
        t.blockSignals(False)

    # ------------------------------------------------------------ revisão
    def checked(self) -> list[silences.Silence]:
        return [s for r, s in enumerate(self.found)
                if self.table.item(r, 0) is not None and self.table.item(r, 0).checkState() == Qt.CheckState.Checked]

    def set_all(self, on: bool) -> None:
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._sync()

    def _preview(self, row: int) -> None:
        """Leva o cursor ao começo do trecho (a imagem do ponto do corte)."""
        if 0 <= row < len(self.found):
            self.win.seek(int(round(self.found[row].start * self.win.model.seq.fps)))

    def frames(self) -> list[tuple[int, int]]:
        return rangecut.to_frames(self.win.model.seq, silences.ranges(self.checked()))

    def _sync(self) -> None:
        busy = self.busy
        self.bar.setVisible(busy)
        for w in (self.btn_analyze, self.scope, self.threshold, self.min_duration, self.padding):
            w.setEnabled(not busy)
        chosen = self.checked()
        has = bool(self.found)
        self.btn_all.setEnabled(has)
        self.btn_none.setEnabled(has)
        self.btn_apply.setEnabled(not busy and bool(self.frames()))
        if has:
            self.summary.setText(_("{n} de {total} trechos marcados • {tempo} a tirar").format(
                n=fmt_int(len(chosen)), total=fmt_int(len(self.found)),
                tempo=fmt_seconds(rangecut.total(silences.ranges(chosen)))))

    def apply(self) -> int:
        """Tira os trechos marcados num passo de desfazer e fecha a janela. Devolve os quadros tirados."""
        frames = self.frames()
        if not frames or self.busy:
            return 0
        n = self.win.model.remove_ranges(frames)
        self.removed = n
        if n:
            tempo = fmt_seconds(n / self.win.model.seq.fps)
            text = (_("1 trecho tirado ({tempo}).").format(tempo=tempo) if len(frames) == 1 else
                    _("{n} trechos tirados ({tempo}).").format(n=fmt_int(len(frames)), tempo=tempo))
            self.win.statusBar().showMessage(text, 6000)
        self.accept()
        return n

    def done(self, result: int) -> None:  # noqa: D401 — fechar cancela a análise que estiver rodando
        if self.busy:
            self.job.cancel()
        super().done(result)
