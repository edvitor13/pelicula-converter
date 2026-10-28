"""Janela "Gerar legendas" (módulo Beta `legendas_auto`): a fala vira legenda neste computador.

Escolhe o que ouvir (o arquivo aberto no modo Película; na Edição, a montagem inteira ou os clipes escolhidos,
`subauto.spans_for`), o idioma, o modelo e o tamanho das linhas, e põe a transcrição na fila de tarefas
(`subauto.make_job`, a mesma chave e o mesmo tipo de `transcribe.make_job`). Sem o motor, o modelo ou o VAD, a
janela diz o que falta e abre Configurações › Componentes: nada é baixado sem o usuário pedir.

A janela não é modal e pode ser fechada: o trabalho continua na fila e, quando termina, as legendas entram no
projeto num passo de desfazer só (`TimelineModel.edit_subtitles` + `subauto.apply`), trocando as que havia nos
trechos ouvidos. Se o projeto mudou e os arquivos não estão mais nele, nada é posto.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import jobs, subauto, tools, transcribe
from ..platforms import fmt_seconds
from ..i18n import _, fmt_int
from . import icons, theme
from .job_bridge import bridge

PREFS = "transcricao/"


def open_for(win) -> "TranscribeDialog":
    """Abre (ou traz para a frente) a janela, com o que a janela principal mostra agora."""
    dlg = getattr(win, "_transcribe_dialog", None)
    if dlg is None:
        dlg = TranscribeDialog(win)
        win._transcribe_dialog = dlg
    if not dlg.busy:
        dlg.refresh()
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


def model_label(model: str) -> str:
    tool = tools.get(transcribe.MODELS[model])
    art = tool.artifact()
    size = f" • {tools.fmt_size(art.size)}" if art is not None and art.size else ""
    return _(transcribe.MODEL_LABELS[model]) + size


class TranscribeDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.settings = getattr(win, "settings", None)
        self.job: jobs.Job | None = None
        self.applied = 0                # legendas que o último trabalho pôs no projeto
        self.setWindowTitle(_("Gerar legendas"))
        self.setModal(False)
        self.resize(560, 0)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        k = QLabel(_("LEGENDAS AUTOMÁTICAS"))
        k.setObjectName("Kicker")
        head.addWidget(k)
        beta = QLabel(_("Beta"))
        beta.setStyleSheet(f"color: {theme.ACCENT_HI}; border: 1px solid {theme.ACCENT_DIM}; border-radius: 8px; "
                           f"padding: 0 7px; font-size: 8.5pt; font-weight: 600;")
        head.addWidget(beta)
        head.addStretch(1)
        lay.addLayout(head)
        title = QLabel(_("Gerar legendas pela fala"))
        title.setObjectName("PanelTitle")
        title.setStyleSheet("font-size: 14pt;")
        lay.addWidget(title)
        intro = QLabel(_("A fala vira legenda neste computador, sem enviar nada para a internet. As legendas ficam "
                         "presas aos arquivos e acompanham os cortes; as que já existem nos trechos ouvidos são "
                         "trocadas. A janela pode ser fechada enquanto ele trabalha."))
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        lay.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)
        self.scope = QComboBox()
        self.scope.currentIndexChanged.connect(lambda _i: self._sync())
        form.addRow(_("Ouvir:"), self.scope)
        self.where = QLabel()
        self.where.setObjectName("Faint")
        self.where.setWordWrap(True)
        form.addRow("", self.where)
        self.language = QComboBox()
        for key, label in subauto.languages().items():
            self.language.addItem(_(label), key)
        form.addRow(_("Idioma:"), self.language)
        self.model_box = QComboBox()
        for key in transcribe.MODELS:
            self.model_box.addItem(model_label(key), key)
        self.model_box.setToolTip(_("Rápido (small): bom para a maioria dos vídeos. Preciso (turbo): acerta mais, "
                                    "mas é mais lento sem placa de vídeo."))
        self.model_box.currentIndexChanged.connect(lambda _i: self._sync())
        form.addRow(_("Modelo:"), self.model_box)
        self.max_chars = QSpinBox()
        self.max_chars.setRange(16, 80)
        self.max_chars.setSuffix(" " + _("caracteres"))
        self.max_chars.setToolTip(_("O máximo de letras em cada linha da legenda (42 é o comum na TV e no cinema; "
                                    "para vídeos verticais, uns 24)"))
        self.max_lines = QSpinBox()
        self.max_lines.setRange(1, 3)
        self.max_lines.setSuffix(" " + _("linhas"))
        form.addRow(_("Cada legenda:"), self._row(self.max_chars, self.max_lines))
        self.gpu = QCheckBox(_("Usar a placa de vídeo, se houver (sem ela, roda no processador)"))
        form.addRow("", self.gpu)
        lay.addLayout(form)

        self.missing_row = QWidget()
        mr = QHBoxLayout(self.missing_row)
        mr.setContentsMargins(0, 0, 0, 0)
        self.missing = QLabel()
        self.missing.setWordWrap(True)
        self.missing.setStyleSheet(f"color: {theme.ACCENT_HI};")
        mr.addWidget(self.missing, 1)
        self.btn_components = QPushButton(_("Abrir Componentes…"))
        self.btn_components.clicked.connect(self.open_components)
        mr.addWidget(self.btn_components)
        lay.addWidget(self.missing_row)

        self.progress_row = QWidget()
        pr = QVBoxLayout(self.progress_row)
        pr.setContentsMargins(0, 4, 0, 0)
        pr.setSpacing(3)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        pr.addWidget(self.bar)
        self.stage = QLabel()
        self.stage.setObjectName("Muted")
        pr.addWidget(self.stage)
        lay.addWidget(self.progress_row)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.message)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_cancel = QPushButton(_("Cancelar"))
        self.btn_cancel.clicked.connect(self.cancel)
        buttons.addWidget(self.btn_cancel)
        self.btn_close = QPushButton(_("Fechar"))
        self.btn_close.clicked.connect(self.close)
        buttons.addWidget(self.btn_close)
        self.btn_run = QPushButton("  " + _("Gerar legendas"))
        self.btn_run.setObjectName("Primary")
        self.btn_run.setIcon(icons.icon("wand", "#1b1205", 15))
        self.btn_run.clicked.connect(self.start)
        buttons.addWidget(self.btn_run)
        lay.addLayout(buttons)

        self._load_prefs()
        b = bridge()
        b.changed.connect(self._on_job_changed)
        b.finished.connect(self._finished)
        self.show_message("")
        self.refresh()

    @staticmethod
    def _row(*widgets) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        for x in widgets:
            h.addWidget(x)
        h.addStretch(1)
        return w

    # ------------------------------------------------------------ preferências (as do usuário, em QSettings)
    def _pref(self, key: str, default):
        value = self.settings.value(PREFS + key, None) if self.settings is not None else None
        if value is None:
            return default
        if isinstance(default, bool):
            return str(value).lower() in ("1", "true")
        try:
            return type(default)(value)
        except (TypeError, ValueError):
            return default

    def _load_prefs(self) -> None:
        self._choose(self.language, self._pref("idioma", "auto"))
        installed = transcribe.installed_models()
        self._choose(self.model_box, self._pref("modelo", installed[0] if installed else transcribe.DEFAULT_MODEL))
        self.max_chars.setValue(self._pref("caracteres", transcribe.Options.max_chars))
        self.max_lines.setValue(self._pref("linhas", transcribe.Options.max_lines))
        self.gpu.setChecked(self._pref("placa", True))

    def _save_prefs(self) -> None:
        if self.settings is None:
            return
        for key, value in (("idioma", self.language.currentData()), ("modelo", self.model_box.currentData()),
                           ("caracteres", self.max_chars.value()), ("linhas", self.max_lines.value()),
                           ("placa", "true" if self.gpu.isChecked() else "false")):
            self.settings.setValue(PREFS + key, value)

    @staticmethod
    def _choose(combo: QComboBox, data) -> None:
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    # ------------------------------------------------------------ o que ouvir
    @property
    def busy(self) -> bool:
        return self.job is not None and self.job.active

    def refresh(self) -> None:
        """Refaz a lista do que dá para ouvir (o modo e a seleção da janela principal podem ter mudado)."""
        win = self.win
        seq = win.model.seq
        keep = self.scope.currentData()
        self.scope.blockSignals(True)
        self.scope.clear()
        trivial = seq.is_trivial()
        if getattr(win, "mode", "") != "edicao" and trivial:
            self.scope.addItem(_("O arquivo aberto: {nome}").format(nome=os.path.basename(trivial)), "arquivo")
        else:
            self.scope.addItem(_("A montagem inteira"), "montagem")
            if getattr(win, "mode", "") == "edicao" and win.model.selected_clips():
                self.scope.addItem(_("Os clipes escolhidos"), "selecao")
        self._choose(self.scope, keep)
        self.scope.blockSignals(False)
        self._sync()

    def spans(self) -> list[subauto.Span]:
        seq = self.win.model.seq
        scope = self.scope.currentData()
        if scope == "arquivo":
            path = seq.is_trivial()
            src = seq.sources.get(path) if path else None
            return subauto.whole_file(path) if src is not None and src.has_audio else []
        ids = [c.id for c in self.win.model.selected_clips()] if scope == "selecao" else None
        return subauto.spans_for(seq, ids)

    def options(self) -> transcribe.Options:
        return transcribe.Options(model=self.model_box.currentData(), language=self.language.currentData(),
                                  gpu=self.gpu.isChecked(), max_chars=self.max_chars.value(),
                                  max_lines=self.max_lines.value())

    def _describe(self, spans: list[subauto.Span]) -> str:
        if not spans:
            return ""
        seq = self.win.model.seq
        total = 0.0
        for sp in spans:
            end = sp.end if sp.end > sp.start else seq.sources[sp.path].duration
            total += max(0.0, end - sp.start)
        files = len({sp.path for sp in spans})
        if files == 1 and len(spans) == 1:
            return _("{tempo} de som para ouvir.").format(tempo=fmt_seconds(total))
        return _("{tempo} de som em {n} trechos de {arquivos} arquivos.").format(
            tempo=fmt_seconds(total), n=fmt_int(len(spans)), arquivos=fmt_int(files))

    def _sync(self) -> None:
        busy = self.busy
        lack = transcribe.missing(self.model_box.currentData() or transcribe.DEFAULT_MODEL)
        if lack:
            self.missing.setText(_("Para gerar legendas, baixe em Configurações › Componentes: {lista}.").format(
                lista=", ".join(_(t.name) for t in lack)))
        self.missing_row.setVisible(bool(lack))
        spans = [] if busy else self.spans()
        if not busy:
            text = self._describe(spans)
            self.where.setText(text or _("Não há som para ouvir aqui."))
        for w in (self.scope, self.language, self.model_box, self.max_chars, self.max_lines, self.gpu):
            w.setEnabled(not busy)
        self.btn_run.setEnabled(not busy and not lack and bool(spans))
        self.btn_cancel.setVisible(busy)
        self.btn_cancel.setEnabled(busy and not self.job.cancelled)
        self.progress_row.setVisible(busy)
        if busy:
            self._show_progress(self.job)

    # ------------------------------------------------------------ ações
    def open_components(self) -> None:
        """Configurações › Componentes (o usuário escolhe o que baixar); na volta, confere de novo."""
        self.win.show_settings("componentes")
        self._sync()

    def start(self) -> jobs.Job | None:
        if self.busy:
            return self.job
        spans = self.spans()
        if not spans or transcribe.missing(self.model_box.currentData()):
            self._sync()
            return None
        self._save_prefs()
        opts = self.options()
        names = sorted({os.path.basename(sp.path) for sp in spans})
        name = names[0] if len(names) == 1 else _("{n} arquivos").format(n=fmt_int(len(names)))
        job = subauto.make_job(opts, _("Legendas: {nome}").format(nome=name), spans)
        job.data = {"caminhos": sorted({sp.path for sp in spans})}
        self.job = bridge().queue.submit(job)
        self.applied = 0
        self.show_message("")
        self._sync()
        return self.job

    def cancel(self) -> None:
        if self.busy:
            self.job.cancel()
            self.stage.setText(_("Cancelando…"))
            self.btn_cancel.setEnabled(False)

    # ------------------------------------------------------------ andamento
    def show_message(self, text: str, tone: str = "muted") -> None:
        color = {"ok": theme.OK, "danger": theme.DANGER, "accent": theme.ACCENT_HI}.get(tone, theme.MUTED)
        self.message.setStyleSheet(f"color: {color};")
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _show_progress(self, job: jobs.Job) -> None:
        frac = job.progress
        if frac is None:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(frac * 1000))
        self.stage.setText(_("Cancelando…") if job.cancelled else (job.stage or _("Na fila…")))

    def _on_job_changed(self, job: jobs.Job) -> None:
        if job is self.job and job.active:
            self._show_progress(job)

    def _finished(self, job: jobs.Job) -> None:
        """Na thread principal (sinal da ponte), com a janela aberta ou não: põe as legendas no projeto."""
        if job is not self.job:
            return
        tone = "muted"
        if job.state == jobs.CONCLUIDO:
            text, tone = self._apply(job.result or [])
        elif job.state == jobs.CANCELADO:
            text = _("Transcrição cancelada.")
        else:
            text, tone = job.error or _("A transcrição falhou."), "danger"
        self.show_message(text, tone)
        self._sync()
        if not self.isVisible():
            self.win.statusBar().showMessage(text, 8000)

    def _apply(self, results) -> tuple[str, str]:
        model = self.win.model
        sources = model.seq.sources
        results = [r for r in results if r.path is None or r.path in sources]
        if not results:
            return _("O projeto mudou durante a transcrição: as legendas não foram postas."), "danger"
        n = sum(len(r.cues) for r in results)
        if n == 0:
            return _("Nenhuma fala reconhecida nos trechos ouvidos."), "muted"
        model.edit_subtitles(lambda subs: subauto.apply(subs, results) and None)
        self.applied = n
        ui = getattr(self.win, "subs_ui", None)
        if ui is not None:
            ui.show_panel(True)
        where = _("na placa de vídeo") if all(r.device == "gpu" for r in results) else _("no processador")
        lang = results[0].language
        label = subauto.languages().get(lang)
        return _("{n} legendas geradas ({idioma}, {onde}).").format(
            n=fmt_int(n), idioma=_(label) if label else lang, onde=where), "ok"

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self.busy:
            self._save_prefs()
        super().closeEvent(event)
