"""Janela "Recorte por IA (CorridorKey)" (módulo Beta `recorte_ia`).

Escolhe o arquivo (o aberto no modo Película ou o arquivo de origem do clipe selecionado na Edição) e
as opções, e põe o recorte na fila de tarefas como trabalho da placa de vídeo. O CorridorKey roda
sempre num processo separado (`corridorkey.run`); a janela não é modal e pode ser fechada: o trabalho
continua e, ao abrir de novo, ela mostra o andamento.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import corridorkey, jobs, media, system
from ..i18n import _
from . import icons, theme
from .job_bridge import bridge

JOB_KEY = "recorte_ia"
VIDEO_FILTER = "*.mp4 *.mov *.mkv *.avi *.mxf *.webm *.m4v *.mts *.m2ts *.mpg *.mpeg *.wmv"
IMAGE_FILTER = "*.png *.jpg *.jpeg *.tif *.tiff *.exr *.bmp"
KEY_PREFIX = "corridorkey/"


def current_source(main) -> tuple[str, object | None]:
    """O arquivo a recortar: na Edição, o de origem do clipe de vídeo selecionado; senão, o arquivo aberto."""
    if main is None:
        return "", None
    model = getattr(main, "model", None)
    if getattr(main, "mode", "") == "edicao" and model is not None:
        for clip in model.selected_clips():
            try:
                src = model.seq.source(clip)
            except (KeyError, AttributeError):
                continue
            if src is not None and src.has_video and not src.is_image:
                return src.path, src
    info = getattr(main, "file_info", None)
    if info is not None and not getattr(info, "is_image", False):
        return info.path, info
    return "", None


def look_profile(main) -> str:
    store = getattr(main, "store", None)
    return str((store.values if store is not None else {}).get("entrada", "rec709") or "rec709")


def open_for(main) -> "CorridorKeyDialog":
    """Abre (ou traz para a frente) a janela do recorte com o arquivo atual da janela principal."""
    dlg = getattr(main, "_corridorkey_dialog", None)
    if dlg is None:
        dlg = CorridorKeyDialog(main)
        main._corridorkey_dialog = dlg
    if not dlg.busy:
        path, info = current_source(main)
        if path:
            dlg.set_input(path, info)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


class CorridorKeyDialog(QDialog):
    def __init__(self, main=None):
        super().__init__(main if isinstance(main, QWidget) else None)
        self.main = main
        self.settings = getattr(main, "settings", None)
        self.job: jobs.Job | None = None
        self.result_dir = ""
        self._info = None
        self.setWindowTitle(_("Recorte por IA (CorridorKey)"))
        self.setModal(False)
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        k = QLabel(_("RECORTE POR IA"))
        k.setObjectName("Kicker")
        head.addWidget(k)
        beta = QLabel(_("Beta"))
        beta.setStyleSheet(f"color: {theme.ACCENT_HI}; border: 1px solid {theme.ACCENT_DIM}; border-radius: 8px; "
                           f"padding: 0 7px; font-size: 8.5pt; font-weight: 600;")
        head.addWidget(beta)
        head.addStretch(1)
        lay.addLayout(head)
        title = QLabel(_("Tirar o fundo verde ou azul"))
        title.setObjectName("PanelTitle")
        title.setStyleSheet("font-size: 14pt;")
        lay.addWidget(title)
        intro = QLabel(_("Grava o vídeo recortado com transparência (ProRes 4444 com alfa) e a máscara, prontos para "
                         "outros editores. O recorte roda na placa de vídeo, num processo separado; a janela pode ser "
                         "fechada enquanto ele trabalha."))
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        lay.addWidget(intro)
        credit = QLabel(_("CorridorKey, da Corridor Digital. O que você recortar é seu e pode ser usado comercialmente."))
        credit.setWordWrap(True)
        credit.setObjectName("Faint")
        lay.addWidget(credit)

        form = QFormLayout()
        form.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText(_("Escolha um vídeo com fundo verde ou azul"))
        self.input.editingFinished.connect(lambda: self.set_input(self.input.text().strip()))
        btn_in = QPushButton(_("Escolher…"))
        btn_in.clicked.connect(self.pick_input)
        form.addRow(_("Vídeo:"), self._row(self.input, btn_in))
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"color: {theme.ACCENT_HI};")
        self.warning.setVisible(False)
        form.addRow("", self.warning)

        self.hint = QComboBox()
        for key in corridorkey.HINTS:
            self.hint.addItem(_(corridorkey.HINT_LABELS[key]), key)
        self.hint.currentIndexChanged.connect(self._sync)
        form.addRow(_("Dica:"), self.hint)
        self.hint_path = QLineEdit()
        btn_hint = QPushButton(_("Escolher…"))
        btn_hint.clicked.connect(self.pick_hint)
        self.hint_row = self._row(self.hint_path, btn_hint)
        form.addRow(_("Arquivo da dica:"), self.hint_row)
        self.hint_quality = QSpinBox()
        self.hint_quality.setRange(0, 100)
        self.hint_quality.setSuffix(" %")
        self.hint_quality.setValue(95)
        self.hint_quality.setToolTip(_("O quanto confiar na dica: 100% segue a máscara à risca"))
        form.addRow(_("Confiança na dica:"), self.hint_quality)

        self.fmt_video = QRadioButton(_("Vídeo: recorte com alfa (ProRes 4444) e máscara"))
        self.fmt_exr = QRadioButton(_("Sequência EXR linear (para composição)"))
        group = QButtonGroup(self)
        group.addButton(self.fmt_video)
        group.addButton(self.fmt_exr)
        self.fmt_video.setChecked(True)
        fmt = QWidget()
        fl = QVBoxLayout(fmt)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(2)
        fl.addWidget(self.fmt_video)
        fl.addWidget(self.fmt_exr)
        form.addRow(_("Saída:"), fmt)
        self.extra_fg = QCheckBox(_("Também a cor do primeiro plano, sem o verde"))
        self.extra_checker = QCheckBox(_("Também uma prévia sobre xadrez"))
        extras = QWidget()
        el = QVBoxLayout(extras)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(2)
        el.addWidget(self.extra_fg)
        el.addWidget(self.extra_checker)
        form.addRow("", extras)
        self.despill = QSpinBox()
        self.despill.setRange(0, 100)
        self.despill.setSuffix(" %")
        self.despill.setValue(50)
        self.despill.setToolTip(_("Tira o reflexo verde ou azul que a tela joga na pessoa: 0% não mexe, 100% tira tudo"))
        form.addRow(_("Tirar o reflexo do fundo:"), self.despill)
        self.low_vram = QCheckBox(_("Pouca memória na placa de vídeo (mais lento)"))
        self.low_vram.setToolTip(_("Usa menos memória da placa e grava arquivos temporários na pasta do app"))
        form.addRow("", self.low_vram)
        self.output = QLineEdit()
        btn_out = QPushButton(_("Escolher…"))
        btn_out.clicked.connect(self.pick_output)
        form.addRow(_("Pasta de saída:"), self._row(self.output, btn_out))
        lay.addLayout(form)

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
        self.progress_row.setVisible(False)
        lay.addWidget(self.progress_row)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message.setVisible(False)
        lay.addWidget(self.message)
        lay.addStretch(1)

        buttons = QHBoxLayout()
        self.btn_open = QPushButton(_("Abrir pasta"))
        self.btn_open.setIcon(icons.icon("folder", theme.TEXT, 15))
        self.btn_open.clicked.connect(self.open_result)
        self.btn_open.setVisible(False)
        buttons.addWidget(self.btn_open)
        buttons.addStretch(1)
        self.btn_cancel = QPushButton(_("Cancelar recorte"))
        self.btn_cancel.clicked.connect(self.cancel)
        buttons.addWidget(self.btn_cancel)
        self.btn_close = QPushButton(_("Fechar"))
        self.btn_close.clicked.connect(self.close)
        buttons.addWidget(self.btn_close)
        self.btn_run = QPushButton("  " + _("Recortar"))
        self.btn_run.setObjectName("Primary")
        self.btn_run.setIcon(icons.icon("matte", "#1b1205", 15))
        self.btn_run.clicked.connect(self.start)
        buttons.addWidget(self.btn_run)
        lay.addLayout(buttons)

        self._load_prefs()
        b = bridge()
        b.changed.connect(self._on_job_changed)
        b.finished.connect(self._finished)
        running = b.queue.find(JOB_KEY)
        if running is not None:
            self.job = running
            self.result_dir = str((running.data or {}).get("saida", ""))
        self._sync()

    # ------------------------------------------------------------ partes
    @staticmethod
    def _row(*widgets) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        for i, x in enumerate(widgets):
            h.addWidget(x, 1 if i == 0 else 0)
        return w

    def _pref(self, key: str, default):
        if self.settings is None:
            return default
        value = self.settings.value(KEY_PREFIX + key, None)
        if value is None:
            return default
        if isinstance(default, bool):
            return str(value).lower() in ("1", "true")
        try:
            return type(default)(value)
        except (TypeError, ValueError):
            return default

    def _load_prefs(self) -> None:
        self.despill.setValue(self._pref("despill", 50))
        self.low_vram.setChecked(self._pref("pouca_memoria", False))
        self.fmt_exr.setChecked(self._pref("exr", False))
        self.fmt_video.setChecked(not self.fmt_exr.isChecked())
        self.extra_fg.setChecked(self._pref("cor", False))
        self.extra_checker.setChecked(self._pref("xadrez", False))

    def _save_prefs(self) -> None:
        if self.settings is None:
            return
        for key, value in (("despill", self.despill.value()), ("pouca_memoria", self.low_vram.isChecked()),
                           ("exr", self.fmt_exr.isChecked()), ("cor", self.extra_fg.isChecked()),
                           ("xadrez", self.extra_checker.isChecked())):
            self.settings.setValue(KEY_PREFIX + key, "true" if value is True else "false" if value is False else value)

    # ------------------------------------------------------------ estado
    @property
    def busy(self) -> bool:
        return self.job is not None and self.job.active

    def set_input(self, path: str, info=None) -> None:
        """Arquivo a recortar; a pasta de saída segue a do arquivo e o aviso de entrada é refeito."""
        old = self.input.text().strip()
        self.input.setText(path)
        if path and (not self.output.text().strip() or self.output.text().strip() == str(Path(old).parent)):
            self.output.setText(str(Path(path).parent))
        if info is None and path and Path(path).is_file():
            try:
                info = media.probe(path)
            except Exception:  # noqa: BLE001 — sem metadados, sem aviso de HDR
                info = None
        self._info = info
        text = corridorkey.source_warning(info, look_profile(self.main), path) if path else ""
        self.warning.setText(text)
        self.warning.setVisible(bool(text))
        self._sync()

    def _sync(self) -> None:
        hint = self.hint.currentData()
        self.hint_row.setEnabled(hint != "nenhuma")
        self.hint_quality.setEnabled(hint != "nenhuma")
        busy = self.busy
        self.btn_run.setEnabled(not busy and bool(self.input.text().strip()))
        self.btn_cancel.setVisible(busy)
        self.progress_row.setVisible(busy)
        for w in (self.input, self.hint, self.fmt_video, self.fmt_exr, self.extra_fg, self.extra_checker,
                  self.despill, self.low_vram, self.output):
            w.setEnabled(not busy)
        if busy:
            self._show_progress(self.job)

    def options(self) -> corridorkey.Options:
        extras = tuple(e for e, box in (("fg", self.extra_fg), ("checker", self.extra_checker)) if box.isChecked())
        return corridorkey.Options(
            input=self.input.text().strip(), output_dir=self.output.text().strip(),
            hint=self.hint.currentData(), hint_path=self.hint_path.text().strip(),
            hint_quality=self.hint_quality.value() / 100.0, extras=extras, exr=self.fmt_exr.isChecked(),
            despill=self.despill.value() / 100.0, low_vram=self.low_vram.isChecked())

    def _problem(self, opts: corridorkey.Options) -> str:
        if not corridorkey.available():
            return _("O CorridorKey não está instalado. Baixe em Configurações › Componentes.")
        if not opts.input or not Path(opts.input).is_file():
            return _("Escolha um vídeo que exista.")
        if not opts.output_dir:
            return _("Escolha a pasta de saída.")
        if opts.hint != "nenhuma" and not (opts.hint_path and Path(opts.hint_path).is_file()):
            return _("Escolha o arquivo da dica (ou use \"Nenhuma\").")
        return ""

    def existing_outputs(self, opts: corridorkey.Options) -> list[Path]:
        name = corridorkey.clip_name(opts.input)
        out = Path(opts.output_dir)
        if not out.is_dir():
            return []
        return [p for p in out.iterdir() if p.name.startswith(name + "_") and
                any(s in p.name for s in ("_cutout", "_alpha", "_fg", "_checker", "_settings"))]

    # ------------------------------------------------------------ ações
    def start(self) -> jobs.Job | None:
        if self.busy:
            return self.job
        opts = self.options()
        problem = self._problem(opts)
        if problem:
            self.show_message(problem, "danger")
            return None
        if self.warning.text() and not self._confirm(
                _("Recorte por IA"), self.warning.text() + "\n\n" + _("Recortar assim mesmo?")):
            return None
        old = self.existing_outputs(opts)
        if old and not self._confirm(_("Recorte por IA"), _("Já existe um recorte deste vídeo em {pasta}. Substituir?")
                                     .format(pasta=opts.output_dir)):
            return None
        self._save_prefs()
        self.result_dir = opts.output_dir
        name = os.path.basename(opts.input)

        def run(job: jobs.Job):
            return corridorkey.run(opts, job.progress_callback(), job.cancel_event)

        self.job = bridge().submit(run, _("Recorte por IA: {arquivo}").format(arquivo=name), kind=jobs.GPU,
                                   key=JOB_KEY, data={"saida": opts.output_dir, "entrada": opts.input})
        self.show_message("")
        self.btn_open.setVisible(False)
        self._sync()
        return self.job

    def cancel(self) -> None:
        if self.busy:
            self.job.cancel()
            self.stage.setText(_("Cancelando…"))
            self.btn_cancel.setEnabled(False)

    def pick_input(self) -> None:
        start = self.input.text().strip() or str(Path.home())
        f, _sel = QFileDialog.getOpenFileName(self, _("Vídeo com fundo verde ou azul"), start,
                                              _("Vídeos ({lista})").format(lista=VIDEO_FILTER))
        if f:
            self.set_input(f)

    def pick_hint(self) -> None:
        image = self.hint.currentData() == "mascara"
        flt = IMAGE_FILTER if image else VIDEO_FILTER
        title = _("Máscara do primeiro quadro") if image else _("Vídeo de dica")
        f, _sel = QFileDialog.getOpenFileName(self, title, self.input.text().strip() or str(Path.home()),
                                              f"{title} ({flt})")
        if f:
            self.hint_path.setText(f)

    def pick_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, _("Pasta de saída"), self.output.text().strip() or str(Path.home()))
        if d:
            self.output.setText(d)

    def open_result(self) -> None:
        if self.result_dir and Path(self.result_dir).is_dir():
            system.open_path(self.result_dir)

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
        stage = _("Cancelando…") if job.cancelled else (job.stage or _("Na fila…"))
        if not job.cancelled and job.total > 1 and job.done:
            stage += " " + _("{feito} de {total}").format(feito=job.done, total=job.total)
        self.stage.setText(stage)
        self.btn_cancel.setEnabled(not job.cancelled)

    def _on_job_changed(self, job: jobs.Job) -> None:
        if job is self.job and job.active:
            self._show_progress(job)

    def _finished(self, job: jobs.Job) -> None:
        """Na thread principal (sinal da ponte), com a janela aberta ou não."""
        if job is not self.job:
            return
        self._sync()
        if job.state == jobs.CONCLUIDO:
            out = corridorkey.main_output(job.result) if job.result is not None else None
            text = _("Recorte pronto: {arquivo}").format(arquivo=out.name if out else self.result_dir)
            self.show_message(text, "ok")
            self.btn_open.setVisible(True)
        elif job.state == jobs.CANCELADO:
            text = _("Recorte cancelado.")
            self.show_message(text, "muted")
        else:
            text = _("O recorte falhou.")
            self.show_message(job.error or text, "danger")
        status = getattr(self.main, "statusBar", None)
        if status is not None and not self.isVisible():
            status().showMessage(text, 8000)

    # ------------------------------------------------------------ diálogos (substituíveis nos testes)
    def _confirm(self, title: str, text: str) -> bool:
        r = QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                 QMessageBox.StandardButton.No)
        return r == QMessageBox.StandardButton.Yes
