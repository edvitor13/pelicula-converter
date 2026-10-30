"""Janela de exportação: plataformas, qualidades prontas, opções do arquivo e desempenho da máquina."""

from __future__ import annotations

import math
import os
import queue
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QRadioButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from .. import chapters as chapters_mod, export, media, platforms, subtitles as subs_mod, system
from .. import fit as fitmod
from ..i18n import N_, _, fmt_decimal, fmt_int
from . import icons, theme
from .widgets import FilmSlider, compact, timecode

# Textos em português marcados com N_(); são traduzidos com _() na hora de aparecer na tela.
PIX_NAMES = {"yuv420p": N_("4:2:0 8 bits"), "yuv422p": N_("4:2:2 8 bits"), "yuv444p": N_("4:4:4 8 bits"),
             "yuv420p10le": N_("4:2:0 10 bits"), "yuv422p10le": N_("4:2:2 10 bits"),
             "yuv444p10le": N_("4:4:4 10 bits"), "yuv420p12le": N_("4:2:0 12 bits"), "p010le": N_("4:2:0 10 bits"),
             "nv12": N_("4:2:0 8 bits"), "yuv444p16le": N_("4:4:4 16 bits"), "rgb48le": N_("RGB 16 bits"),
             "rgb48be": N_("RGB 16 bits"), "rgb24": N_("RGB 8 bits"), "yuvj444p": N_("4:4:4 8 bits"),
             "pal8": N_("256 cores")}
Q_LABELS = {"crf": N_("CRF (menor = melhor)"), "cq": N_("CQ (menor = melhor)"), "gq": N_("Qualidade (menor = melhor)"),
            "qp": N_("QP (menor = melhor)"), "qscale": N_("Qualidade (menor = melhor)"),
            "jpgq": N_("Qualidade (menor = melhor)"), "webpq": N_("Qualidade (maior = melhor)")}
Q_DEFAULT = {"crf": 16, "cq": 17, "gq": 20, "qp": 20, "qscale": 3, "jpgq": 2, "webpq": 90}
P_DEFAULT = {"x264": "slow", "x265": "slow", "h264_nvenc": "p6", "hevc_nvenc": "p6", "h264_qsv": "medium",
             "hevc_qsv": "medium", "h264_amf": "quality", "hevc_amf": "quality", "vp9": "2", "av1": "5"}
# Quadros fixos da lista (as plataformas acrescentam o delas se faltar); "" = segue a resolução.
FRAMES = ("", "1080x1920", "720x1280", "1080x1350", "1080x1080", "1920x1080", "1280x720", "2160x3840", "3840x2160")
# Volume alvo (LUFS integrados; 0 = desligado) com o uso de cada um.
LOUDNESS = ((0.0, N_("Desligado (volume original)")), (-14.0, N_("−14 LUFS (redes e streaming)")),
            (-16.0, N_("−16 LUFS (podcast)")), (-23.0, N_("−23 LUFS (TV e festival, EBU R 128)")),
            (-24.0, N_("−24 LUFS (TV nos EUA, ATSC A/85)")))
PLATFORM_KEYS = ("platform", "frame", "fit", "target_mb", "maxrate", "loudness", "true_peak")
PREVIEW_BOX = 200  # px do quadrado onde a prévia do resultado aparece
PREVIEW_MAX = 400  # maior lado (px) do quadro renderizado para a prévia
# Legendas na exportação (`subtitles.DELIVERY`): chave → rótulo.
SUBTITLE_LABELS = {"nao": N_("Sem legendas"), "faixa": N_("Faixa de legenda no arquivo (dá para ligar e desligar)"),
                   "copia": N_("Gravada na cópia (antes do look: com grão, halação e tremor)"),
                   "digital": N_("Digital (gravada depois do look, nítida)"), "srt": N_("Arquivo .srt ao lado do vídeo"),
                   "vtt": N_("Arquivo .vtt ao lado do vídeo")}

@dataclass
class ExportTarget:
    """Uma sequência do projeto que pode sair na exportação (#57), com o que a janela principal entrega pronto: o que
    depende dela (`info`, a montagem, capítulos, legendas, entrada e saída) muda junto quando ela é escolhida."""

    id: str
    name: str
    info: media.MediaInfo
    sequence: Any = None          # timeline.Sequence (uma cópia; None = o arquivo de `info`, lido direto)
    in_out: tuple[int, int] | None = None
    chapters: list = field(default_factory=list)
    subtitles: Any = None
    cues: list = field(default_factory=list)
    frame: int = 0                # o quadro da prévia do resultado


def safe_name(name: str) -> str:
    """O nome de uma sequência como parte do nome de um arquivo."""
    return re.sub(r'[<>:"/\\|?*]', "-", name).strip(" .") or "sequencia"


def fmt_dur(sec: float) -> str:
    sec = int(round(max(sec, 1)))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


class _Bridge(QObject):
    done = Signal(int, float, float)   # medição: (vez, quadros/s, bytes de vídeo por segundo)
    preview = Signal(int, object)      # prévia: (vez, quadro RGB 8 bits ou None se falhou)


class _PreviewWorker:
    """Renderiza a prévia do resultado numa thread com o próprio `Engine` (um contexto OpenGL por thread),
    pelo mesmo caminho da exportação (`export.preview_frame`). Só o pedido mais recente é atendido."""

    def __init__(self, bridge: _Bridge):
        self.bridge = bridge
        self.q: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None

    def request(self, token: int, args: tuple) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, daemon=True, name="previa_exportacao")
            self.thread.start()
        self.q.put((token, args))

    def stop(self) -> None:
        if self.thread is not None:
            self.q.put(None)

    def _loop(self) -> None:
        engine = None
        failed = False
        while True:
            item = self.q.get()
            while item is not None and not self.q.empty():  # pula pedidos velhos
                nxt = self.q.get()
                item = nxt
            if item is None:
                break
            token, (info, values, s, frame, seq, scale, keys, burn) = item
            img = None
            if not failed:
                try:
                    if engine is None:
                        from ..engine import Engine
                        engine = Engine()
                    img = export.preview_frame(engine, info, values, s, frame, seq=seq, scale=scale, depth=8,
                                               keys=keys, burn=burn)
                except Exception:  # noqa: BLE001 — sem GPU ou arquivo ilegível: a janela diz "indisponível"
                    img = None
                    failed = engine is None
            self.bridge.preview.emit(token, img)
        if engine is not None:
            engine.release()


class ExportDialog(QDialog):
    def __init__(self, parent, info: media.MediaInfo, values: dict, preset_name: str,
                 in_out: tuple[int, int] | None, last_dir: str = "", last_quality: str = "",
                 perf: dict | None = None, gpu_name: str = "", sequence=None, frame: int = 0,
                 last_platform: str = "", chapters=None, look_keys: dict | None = None, subtitles=None,
                 subtitle_cues=None, queue_jobs=(), no_effects: bool = False, targets=None, target_id: str = ""):
        super().__init__(parent)
        self.info = info
        # 1.7, várias sequências: com duas ou mais, uma linha "Sequência" escolhe qual sai (a aberta, para começar) e
        # dá para pôr várias na fila, uma tarefa para cada, com as mesmas opções (`ExportTarget`, `jobs`).
        self.targets: dict[str, ExportTarget] = {t.id: t for t in (targets or [])} if len(targets or []) > 1 else {}
        self._target_id = target_id
        self._auto_stem = ""   # o nome que a janela propôs para o arquivo (enquanto a pessoa não muda)
        self.no_effects = bool(no_effects)  # 1.7: "Desligar todos os efeitos" (`ExportSettings.no_effects`)
        self.queue_jobs = queue_jobs  # o que já está na fila: outro trabalho com o mesmo destino pede outro nome
        # legendas do projeto (`subtitles.Subtitles`) e as da montagem em segundos da sequência
        self.subs_doc = subtitles
        self.subs_cues = list(subtitle_cues or [])
        self.look_keys = dict(look_keys or {})  # chaves de animação do look (`Project.look_keys`)
        self.sequence = sequence  # timeline.Sequence quando o que sai é a montagem do modo Edição
        self.chapters = list(chapters or [])  # [(quadro, título)] dos capítulos da montagem (`chapters.points`)
        self.values = values
        self.preset_name = preset_name
        self.in_out = in_out
        self.gpu_name = gpu_name
        self.frame_index = int(frame)  # quadro da prévia do resultado (o que está na tela da janela principal)
        self._maxrate = 0.0  # teto de taxa da plataforma (sem campo próprio; aparece no resumo)
        self._vbps = 0.0     # bytes de vídeo por segundo medidos na estimativa (tamanho provável)
        self.setWindowTitle(_("Exportar"))
        self.setMinimumWidth(700)
        self.resize(720, 860)
        self._building = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(22, 20, 22, 8)
        lay.setSpacing(12)
        k = QLabel(_("EXPORTAR"))
        k.setObjectName("Kicker")
        lay.addWidget(k)
        t = QLabel(self._title_of(sequence, info))
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 14pt;")
        lay.addWidget(t)
        sub = QLabel(_("Look: {look}  •  {resumo}").format(look=preset_name, resumo=info.summary()))
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        self.title_label, self.sub_label = t, sub
        self.seq_group = self._sequence_group()
        lay.addWidget(self.seq_group)
        self.seq_group.setVisible(bool(self.targets))

        # destino
        row = QHBoxLayout()
        self.path = QLineEdit()
        row.addWidget(self.path, 1)
        b = QPushButton(_("Procurar…"))
        b.setIcon(icons.icon("folder", theme.TEXT, 16))
        b.clicked.connect(self._browse)
        row.addWidget(b)
        g0 = QGroupBox(_("Destino"))
        QVBoxLayout(g0).addLayout(row)
        lay.addWidget(g0)

        # plataforma (só vídeo)
        self.platform_group = self._platform_group()
        lay.addWidget(self.platform_group)
        self.platform_group.setVisible(not info.is_image)

        # qualidade
        g1 = QGroupBox(_("Formato e qualidade"))
        v1 = QVBoxLayout(g1)
        self.quality = compact(QComboBox(), 20)
        self.quality.setMaxVisibleItems(24)
        self.presets = export.quality_presets(info)
        for key, label, _s in self.presets:
            self.quality.addItem(label, key)
        self.quality.addItem(_("Personalizado"), "custom")
        v1.addWidget(self.quality)
        self.qdesc = QLabel()
        self.qdesc.setObjectName("Faint")
        self.qdesc.setWordWrap(True)
        v1.addWidget(self.qdesc)
        lay.addWidget(g1)

        # ajustes do arquivo
        g2 = QGroupBox(_("Ajustes do arquivo"))
        form = QFormLayout(g2)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.codec = compact(QComboBox())
        image = info.is_image
        for key, c in export.CODECS.items():
            if bool(c.get("image")) != image or not export.available(key):
                continue
            self.codec.addItem(_(c["label"]), key)
        self.container = compact(QComboBox())
        self.pix = compact(QComboBox())
        self.qval = QDoubleSpinBox()
        self.qval.setDecimals(0)
        self.qlabel = QLabel(_("Qualidade"))
        self.bitrate = QDoubleSpinBox()
        self.bitrate.setRange(0, 2000)
        self.bitrate.setDecimals(1)
        self.bitrate.setSuffix(" Mb/s")
        self.bitrate.setSpecialValueText(_("Automática (qualidade constante)"))
        self.speed = compact(QComboBox())
        self.profile = compact(QComboBox())
        self.res = compact(QComboBox())
        for key, lab in export.RESOLUTIONS:
            self.res.addItem(_(lab), key)
        self.res.setToolTip(_("O número vale para o lado menor do quadro, como no YouTube e nos celulares: em 1080p, "
                              "um vídeo deitado sai 1920 × 1080 e um vídeo em pé sai 1080 × 1920."))
        self.fps = compact(QComboBox())
        for key, lab in export.FPS:
            self.fps.addItem(_(lab), key)
        self.audio = compact(QComboBox())
        for key, lab in export.AUDIO:
            self.audio.addItem(_(lab), key)
        self.grain = QCheckBox(_("Otimizar o codificador para grão (tune grain)"))
        self.dither = QCheckBox(_("Pontilhado (dither) para evitar faixas em 8 bits"))
        form.addRow(_("Codec"), self.codec)
        form.addRow(_("Recipiente"), self.container)
        form.addRow(_("Formato de cor"), self.pix)
        self._alpha_rows(form)
        form.addRow(self.qlabel, self.qval)
        form.addRow(_("Taxa de bits"), self.bitrate)
        form.addRow(_("Velocidade"), self.speed)
        form.addRow(_("Perfil"), self.profile)
        form.addRow(_("Resolução"), self.res)
        form.addRow(_("Quadros/s"), self.fps)
        form.addRow(_("Áudio"), self.audio)
        form.addRow("", self.grain)
        form.addRow("", self.dither)
        self.form = form
        self._platform_rows(form)
        lay.addWidget(g2)
        if image:
            for w in (self.fps, self.audio, self.grain, self.bitrate, self.speed, self.frame_box, self.fit_box,
                      self.target, self.loud, self.peak, self.net_grain):
                form.setRowVisible(w, False)

        # desempenho
        lay.addWidget(self._perf_group(perf or {}))

        # trecho
        self.r_all = QRadioButton(_("Vídeo inteiro"))
        self.r_sel = QRadioButton(_("Só o trecho marcado"))
        grp = QButtonGroup(self)
        grp.addButton(self.r_all)
        grp.addButton(self.r_sel)
        self.r_all.setChecked(True)
        if not image:
            rr = QHBoxLayout()
            rr.addWidget(self.r_all)
            rr.addWidget(self.r_sel)
            rr.addStretch(1)
            if in_out:
                a, b2 = in_out
                self.r_sel.setText(_("Só o trecho marcado ({inicio} – {fim})").format(
                    inicio=timecode(a, info.fps), fim=timecode(b2, info.fps)))
            else:
                self.r_sel.setEnabled(False)
                self.r_sel.setToolTip(_("Marque entrada (I) e saída (O) na linha do tempo."))
            lay.addLayout(rr)
            self.r_sel.toggled.connect(self._summary)
        self.chapters_box = self._chapters_box()
        lay.addWidget(self.chapters_box)
        self.subs_row = self._subtitles_row()
        lay.addWidget(self.subs_row)
        lay.addStretch(1)

        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(22, 8, 22, 16)
        self.warn = QLabel()  # avisos: limites da plataforma, duas passadas, som recodificado
        self.warn.setStyleSheet(f"color: {theme.DANGER};")
        self.warn.setWordWrap(True)
        self.warn.setVisible(False)
        fl.addWidget(self.warn)
        self.est_label = QLabel()
        self.est_label.setStyleSheet(f"color: {theme.ACCENT_HI}; font-weight: 600;")
        self.est_label.setWordWrap(True)
        fl.addWidget(self.est_label)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        fl.addWidget(self.summary)
        self._bridge = _Bridge()
        self._bridge.done.connect(self._est_done)
        self._bridge.preview.connect(self._preview_done)
        self._preview_worker = _PreviewWorker(self._bridge)
        self._preview_token = 0
        self._preview_key = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(350)
        self._preview_timer.timeout.connect(self._start_preview)
        self._est_token = 0
        self._est_cancel: threading.Event | None = None
        self._est_timer = QTimer(self)
        self._est_timer.setSingleShot(True)
        self._est_timer.setInterval(900)
        self._est_timer.timeout.connect(self._start_estimate)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(_("Cancelar"))
        cancel.clicked.connect(self.reject)
        ok = QPushButton("  " + _("Adicionar à fila e exportar"))
        ok.setObjectName("Primary")
        ok.setIcon(icons.icon("export", "#1b1205", 16))
        ok.clicked.connect(self._accept)
        self.ok_button = ok
        btns.addWidget(cancel)
        btns.addWidget(ok)
        fl.addLayout(btns)
        outer.addWidget(foot)

        self.out_dir = last_dir if last_dir and os.path.isdir(last_dir) else str(Path(info.path).parent)
        self.quality.currentIndexChanged.connect(self._quality_changed)
        self.codec.currentIndexChanged.connect(self._codec_changed)
        for w in (self.container, self.pix, self.speed, self.profile, self.res, self.fps, self.audio):
            w.currentIndexChanged.connect(self._custom)
        self.container.currentIndexChanged.connect(self._fix_ext)
        self.container.currentIndexChanged.connect(self._sync_chapters)
        self.container.currentIndexChanged.connect(self._sync_subtitles)
        for w in (self.qval, self.bitrate):
            w.valueChanged.connect(self._custom)
        for w in (self.grain, self.dither):
            w.toggled.connect(self._custom)
        self.res.currentIndexChanged.connect(self._update_mem)
        self.pix.currentIndexChanged.connect(self._update_mem)
        self.alpha_box.toggled.connect(self._summary)  # independe da qualidade escolhida (não vira "Personalizado")
        self.alpha_box.toggled.connect(self._update_mem)
        self.frame_box.currentIndexChanged.connect(self._frame_changed)
        for w in (self.fit_box, self.loud):
            w.currentIndexChanged.connect(self._custom)
        for w in (self.target, self.peak):
            w.valueChanged.connect(self._custom)
        self.net_grain.toggled.connect(self._custom)
        self.trim_max.toggled.connect(self._summary)
        self.platform.currentIndexChanged.connect(self._platform_changed)
        i = self.quality.findData(last_quality)
        self.quality.setCurrentIndex(i if i >= 0 else 0)
        self._quality_changed()
        if platforms.get(last_platform) is not None and not info.is_image:
            self._set_combo(self.platform, last_platform)  # a última plataforma usada preenche tudo de novo
        self._update_mem()
        self._sync_chapters()
        self._init_subtitles()

    # ------------------------------------------------------------ várias sequências
    def _title_of(self, sequence, info) -> str:
        if self.targets and self._target_id in self.targets:
            return self.targets[self._target_id].name
        return (sequence.name or _("Montagem da edição")) if sequence is not None else Path(info.path).name

    def _stem(self, tid: str = "") -> str:
        """O nome proposto para o arquivo (sem a extensão). Com várias sequências, o da sequência; sozinha, como sempre."""
        t = self.targets.get(tid or self._target_id)
        if t is not None:
            return safe_name(t.name) + "_pelicula"
        return media.sequence_stem(self.info.path) + "_pelicula"

    def _sequence_group(self) -> QGroupBox:
        """A linha "Sequência": qual sai e, marcando "Pôr várias na fila", quais (uma tarefa para cada)."""
        g = QGroupBox(_("Sequência"))
        v = QVBoxLayout(g)
        self.seq_box = compact(QComboBox(), 20)
        for t in self.targets.values():
            self.seq_box.addItem(t.name, t.id)
        self.seq_box.setCurrentIndex(max(0, self.seq_box.findData(self._target_id)))
        self._target_id = str(self.seq_box.currentData() or self._target_id)
        self.seq_box.setToolTip(_("Qual sequência do projeto sai. Escolher outra troca o que depende dela: duração, "
                                  "trecho (volta para a sequência inteira), capítulos, legendas, nome e tamanho."))
        v.addWidget(self.seq_box)
        self.seq_info = QLabel()
        self.seq_info.setObjectName("Muted")
        v.addWidget(self.seq_info)
        self.multi_box = QCheckBox(_("Pôr várias sequências na fila"))
        self.multi_box.setToolTip(_("Uma tarefa para cada sequência marcada, com as mesmas opções abaixo. Cada arquivo "
                                    "leva o nome da sequência, na pasta do destino."))
        v.addWidget(self.multi_box)
        self.multi_list = QListWidget()
        self.multi_list.setObjectName("Panel")
        for t in self.targets.values():
            item = QListWidgetItem(t.name)
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if t.id == self._target_id else Qt.CheckState.Unchecked)
            item.setSizeHint(QSize(0, 28))
            self.multi_list.addItem(item)
        self.multi_list.setFixedHeight(min(190, 28 * max(1, len(self.targets)) + 8))
        self.multi_list.setVisible(False)
        self.multi_list.itemChanged.connect(self._multi_changed)
        v.addWidget(self.multi_list)
        self.multi_box.toggled.connect(self._multi_toggled)
        self.seq_box.currentIndexChanged.connect(self._sequence_changed)
        self._sync_seq_info()
        return g

    def _sync_seq_info(self) -> None:
        if not self.targets:
            return
        i = self.info
        self.seq_info.setText(_("{w} × {h} • {fps} quadros/s • {dur}").format(
            w=i.width, h=i.height, fps=fmt_decimal(i.fps, 3), dur=fmt_dur(i.frames / max(i.fps, 1e-6))))

    def multi_on(self) -> bool:
        return bool(self.targets) and self.multi_box.isChecked()

    def checked_ids(self) -> list[str]:
        """As sequências marcadas para a fila, na ordem das abas."""
        out = []
        for i in range(self.multi_list.count()):
            it = self.multi_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(str(it.data(Qt.ItemDataRole.UserRole)))
        return out

    def _multi_toggled(self, on: bool) -> None:
        self.multi_list.setVisible(on)
        self._multi_changed()

    def _multi_changed(self, *_args) -> None:
        n = len(self.checked_ids()) if self.multi_on() else 1
        self.ok_button.setText("  " + (_("Pôr {n} na fila").format(n=n) if self.multi_on()
                                       else _("Adicionar à fila e exportar")))
        self.ok_button.setEnabled(n > 0)
        self.path.setToolTip(_("O arquivo da sequência escolhida; as outras vão para esta pasta, com o nome de cada "
                               "uma.") if self.multi_on() else "")

    def _sequence_changed(self, *_args) -> None:
        tid = str(self.seq_box.currentData() or "")
        if tid and tid != self._target_id:
            self._set_target(tid)

    def _set_target(self, tid: str) -> None:
        """Outra sequência escolhida: tudo o que depende dela é refeito (duração, trecho de volta para a sequência
        inteira, capítulos, legendas, transparência, qualidades prontas, tamanhos, nome do arquivo e a prévia)."""
        t = self.targets.get(tid)
        if t is None:
            return
        old_stem = self._auto_stem
        self._target_id = tid
        self.info, self.sequence = t.info, t.sequence
        self.chapters, self.subs_doc, self.subs_cues = list(t.chapters), t.subtitles, list(t.cues)
        self.in_out, self.frame_index = t.in_out, int(t.frame)
        self.title_label.setText(t.name)
        self.sub_label.setText(_("Look: {look}  •  {resumo}").format(look=self.preset_name, resumo=t.info.summary()))
        self._sync_seq_info()
        if self.multi_on():  # a escolhida entra na fila junto
            for i in range(self.multi_list.count()):
                if self.multi_list.item(i).data(Qt.ItemDataRole.UserRole) == tid:
                    self.multi_list.item(i).setCheckState(Qt.CheckState.Checked)
        self._building = True
        try:
            self.r_all.setChecked(True)
            if self.in_out:
                a, b = self.in_out
                self.r_sel.setText(_("Só o trecho marcado ({inicio} – {fim})").format(
                    inicio=timecode(a, self.info.fps), fim=timecode(b, self.info.fps)))
                self.r_sel.setEnabled(True)
                self.r_sel.setToolTip("")
            else:
                self.r_sel.setText(_("Só o trecho marcado"))
                self.r_sel.setEnabled(False)
                self.r_sel.setToolTip(_("Marque entrada (I) e saída (O) na linha do tempo."))
            self._reload_presets()
            self._res_labels(self.codec.currentData())
            self.alpha_box.setChecked(bool(getattr(self.sequence, "transparent", False)))
            self.chapters_box.setText(_("Incluir capítulos ({n}) — dos marcadores marcados como capítulo").format(
                n=len(self.chapters)))
            self.chapters_box.setVisible(bool(self.chapters) and not self.info.is_image)
            self.subs_row.setVisible(bool(self.subs_cues) and self.subs_doc is not None)
        finally:
            self._building = False
        self._sync_alpha()
        self._init_subtitles()
        cur = self.path.text().strip()
        if cur and old_stem and Path(cur).stem == old_stem:  # o nome era o proposto: acompanha a sequência
            stem = self._stem()
            self._auto_stem = stem
            self.path.setText(str(Path(cur).with_name(stem + Path(cur).suffix)))
        self._preview_key = None
        self._summary()
        self._update_mem()

    def _reload_presets(self) -> None:
        """As qualidades prontas de outra sequência: só a "Original" depende do arquivo (formato do primeiro vídeo)."""
        new = export.quality_presets(self.info)
        if [(k, s.to_dict()) for k, _l, s in new] == [(k, s.to_dict()) for k, _l, s in self.presets]:
            return
        cur = self.quality.currentData()
        self.presets = new
        self.quality.blockSignals(True)
        self.quality.clear()
        for key, label, _s in new:
            self.quality.addItem(label, key)
        self.quality.addItem(_("Personalizado"), "custom")
        i = self.quality.findData(cur)
        self.quality.setCurrentIndex(i if i >= 0 else self.quality.count() - 1)
        self.quality.blockSignals(False)
        if cur == "original":
            self._building = False
            self._quality_changed()

    def jobs(self) -> list[export.ExportJob]:
        """As tarefas da fila: uma para a sequência escolhida (`job`) ou, em "Pôr várias sequências na fila", uma para
        cada marcada, com as mesmas opções. A escolhida usa o destino digitado; as outras, o nome da sequência na mesma
        pasta (sem sobrescrever nada: se o nome já existe, vira `nome_2`)."""
        if not self.multi_on():
            return [self.job()]
        base = self.settings()
        typed = self.path.text().strip()
        made: dict[str, export.ExportJob] = {}
        taken = list(self.queue_jobs)
        wanted = self.checked_ids()
        order = ([self._target_id] if self._target_id in wanted else []) + [i for i in wanted if i != self._target_id]
        for tid in order:
            if tid == self._target_id:
                job = self.job()
            else:
                t = self.targets[tid]
                s = export.ExportSettings.from_dict(base.to_dict())
                if media.pix_has_alpha(s.pix) and not getattr(t.sequence, "transparent", False):
                    s.pix = export.opaque_pix(s.codec, s.pix)  # esta sequência não tem fundo transparente
                path = str(Path(typed).with_name(self._stem(tid) + Path(typed).suffix))
                if (export.queue_clash(path, s, taken) or export.output_exists(path, s)
                        or export.partial_clash(path, s, export.job_inputs(t.info, t.sequence))):
                    path = export.free_output(path, s, taken)
                a, b = self._range_for(t)
                job = export.ExportJob(
                    info=t.info, values=dict(self.values), settings=s, out_path=path, start_frame=a, end_frame=b,
                    name=f"{Path(path).name}  •  {self.preset_name}", sequence=t.sequence,
                    chapters=self._chapters_of(t.chapters), look_keys=dict(self.look_keys),
                    **subs_mod.delivery_fields(self.subtitle_choice() if t.cues and t.subtitles is not None else "nao",
                                               t.subtitles, t.cues, self.container.currentData()))
            made[tid] = job
            taken.append(job)
        return [made[i] for i in wanted]

    def _range_for(self, t: ExportTarget) -> tuple[int, int]:
        """O trecho de outra sequência: inteira, com o corte na duração máxima da plataforma (se marcado)."""
        p = self.current_platform()
        if p is not None and p.max_s and not self.trim_max.isHidden() and self.trim_max.isChecked():
            return 0, max(0, min(t.info.frames, int(math.floor(p.max_s * t.info.fps + 1e-6))) - 1)
        return 0, -1

    def _chapters_of(self, points) -> list[tuple[int, str]]:
        if not points or self.chapters_box.isHidden() or not self.chapters_box.isChecked():
            return []
        return list(points) if self.container.currentData() in chapters_mod.CONTAINERS else []

    # ------------------------------------------------------------ plataforma
    def _platform_group(self) -> QGroupBox:
        g = QGroupBox(_("Plataforma"))
        h = QHBoxLayout(g)
        h.setSpacing(14)
        v = QVBoxLayout()
        v.setSpacing(6)
        self.platform = compact(QComboBox(), 20)
        self.platform.setMaxVisibleItems(32)
        self.platform.addItem(_("Nenhuma (escolha a qualidade abaixo)"), "")
        model = self.platform.model()
        for _gid, label, items in platforms.grouped():
            self.platform.addItem(_(label).upper(), None)  # título do grupo (não dá para escolher)
            head = model.item(self.platform.count() - 1)
            head.setEnabled(False)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            for p in items:
                self.platform.addItem("    " + _(p.name), p.id)
        self.platform.setToolTip(_("Preenche o formato, o quadro, o som e os limites para a plataforma escolhida. "
                                   "Depois dá para mudar qualquer opção. Nada é enviado: o arquivo fica no "
                                   "computador."))
        v.addWidget(self.platform)
        self.plimits = QLabel()
        self.plimits.setObjectName("Muted")
        self.plimits.setWordWrap(True)
        v.addWidget(self.plimits)
        self.pnote = QLabel()
        self.pnote.setObjectName("Faint")
        self.pnote.setWordWrap(True)
        v.addWidget(self.pnote)
        self.trim_max = QCheckBox()
        self.trim_max.setVisible(False)
        v.addWidget(self.trim_max)
        v.addStretch(1)
        h.addLayout(v, 1)
        pv = QVBoxLayout()
        pv.setSpacing(4)
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW_BOX, PREVIEW_BOX)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(f"background: #000; border: 1px solid {theme.BORDER}; color: {theme.FAINT};")
        self.preview.setWordWrap(True)
        self.preview.setToolTip(_("Um quadro do resultado, feito pelo mesmo caminho da exportação: quadro, encaixe "
                                  "e look como vão sair."))
        pv.addWidget(self.preview)
        self.preview_caption = QLabel(_("Prévia do resultado"))
        self.preview_caption.setObjectName("Faint")
        self.preview_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pv.addWidget(self.preview_caption)
        pv.addStretch(1)
        h.addLayout(pv)
        return g

    def _platform_rows(self, form: QFormLayout) -> None:
        """Quadro fixo, encaixe, tamanho alvo, volume alvo, pico real e "Grão para redes"."""
        self.frame_box = compact(QComboBox())
        for key in FRAMES:
            self._add_frame(key)
        self.frame_box.setToolTip(_("Tamanho exato do quadro (ex.: 1080 × 1920 para Reels e TikTok). Um vídeo de "
                                    "outra proporção entra conforme o Encaixe. Automático segue a Resolução."))
        self.fit_box = compact(QComboBox())
        for key, label in fitmod.MODES:
            self.fit_box.addItem(_(label), key)
        self.fit_box.setToolTip(_("Vídeo de outra proporção no quadro: cortar as sobras, bordas pretas ou o próprio "
                                  "vídeo desfocado no fundo. O look de película é desenhado no quadro final."))
        self.target = QDoubleSpinBox()
        self.target.setRange(0, 100_000)
        self.target.setDecimals(1)
        self.target.setSuffix(" MB")
        self.target.setSpecialValueText(_("Desligado"))
        self.target.setToolTip(_("O arquivo sai com no máximo este tamanho (1 MB = 1.000.000 bytes), para "
                                 "Discord, WhatsApp e e-mail. Usa duas passadas: leva cerca do dobro do tempo."))
        self.loud = compact(QComboBox())
        for val, label in LOUDNESS:
            self.loud.addItem(_(label), val)
        self.loud.setToolTip(_("Acerta o volume do som (medido em duas passadas, EBU R 128). As plataformas "
                               "abaixam o som alto demais; no volume delas o vídeo soa como os outros."))
        self.peak = QDoubleSpinBox()
        self.peak.setRange(-9.0, 0.0)
        self.peak.setDecimals(1)
        self.peak.setSingleStep(0.5)
        self.peak.setSuffix(" dBTP")
        self.peak.setValue(export.ExportSettings().true_peak)
        self.peak.setToolTip(_("Pico real máximo do som com volume alvo (−1 dBTP é o padrão; −2 no Spotify)."))
        self.net_grain = QCheckBox(_("Grão para redes"))
        self.net_grain.setToolTip(_("Grão com tamanho mínimo no quadro de saída, para sobreviver à recompressão "
                                    "das redes. Desligado, o grão sai como na prévia."))
        form.addRow(_("Quadro"), self.frame_box)
        form.addRow(_("Encaixe"), self.fit_box)
        form.addRow(_("Tamanho alvo"), self.target)
        form.addRow(_("Volume alvo"), self.loud)
        form.addRow(_("Pico real"), self.peak)
        form.addRow("", self.net_grain)

    def _add_frame(self, key: str) -> None:
        size = export.parse_frame(key)
        if size:
            label = f"{size[0]} × {size[1]} ({platforms.aspect_name(*size)})"
        else:
            label = _("Automático (pela resolução)")
        self.frame_box.addItem(label, key)

    def _set_loudness(self, value: float) -> None:
        i = self.loud.findData(float(value))
        if i < 0:
            self.loud.addItem(_("{lufs} LUFS").format(lufs=platforms.fmt_lufs(value)), float(value))
            i = self.loud.count() - 1
        self.loud.setCurrentIndex(i)

    def platform_id(self) -> str:
        return str(self.platform.currentData() or "")

    def current_platform(self) -> platforms.Platform | None:
        return platforms.get(self.platform_id())

    def _platform_changed(self, *_args) -> None:
        if self._building:
            return
        p = self.current_platform()
        if p is None:
            self._quality_changed()  # "Nenhuma": volta à qualidade escolhida (ou só limpa os limites)
            return
        dur = self._duration()
        s = platforms.settings_for(p.id, self.info, base=self.settings(), duration=dur)
        s.net_grain = self.net_grain.isChecked()  # escolha do usuário, não da plataforma
        self._apply(s)
        self.quality.blockSignals(True)
        self.quality.setCurrentIndex(self.quality.count() - 1)
        self.quality.blockSignals(False)
        self.qdesc.setText(_("Opções de {plataforma}. Dá para mudar qualquer uma abaixo.").format(
            plataforma=_(p.name)))

    def _frame_changed(self, *_args) -> None:
        if self._building:
            return
        size = export.parse_frame(self.frame_box.currentData() or "")
        if size:  # quadro escolhido à mão: encaixe automático (cortar quando a proporção é parecida)
            self._building = True
            self._set_combo(self.fit_box, platforms.auto_fit(self.info.width, self.info.height, *size))
            self._building = False
        self._custom()

    def _platform_info(self) -> None:
        """Limites e nota da plataforma, e o corte opcional na duração máxima."""
        p = self.current_platform()
        self.plimits.setVisible(p is not None)
        self.pnote.setVisible(p is not None)
        if p is None:
            self.trim_max.setVisible(False)
            return
        self.plimits.setText(platforms.limits_text(p))
        note = _(p.note) if p.note else ""
        if not p.official:
            note = (note + " " if note else "") + _("(Valores conservadores: a plataforma não publica especificação.)")
        self.pnote.setText(note)
        over = bool(p.max_s) and self._duration(trim=False) > p.max_s + 0.05
        self.trim_max.setVisible(over)
        if over:
            self.trim_max.setText(_("Exportar só os primeiros {dur} (o limite de {plataforma})").format(
                dur=platforms.fmt_seconds(p.max_s), plataforma=_(p.name)))

    def _sync_rows(self, s: export.ExportSettings) -> None:
        """Habilita as linhas que valem para as opções atuais."""
        fixed = export.parse_frame(s.frame) is not None
        self.res.setEnabled(not fixed)
        self.fit_box.setEnabled(fixed)
        if not self.info.is_image:
            self.form.setRowVisible(self.target, s.codec in export.TWO_PASS_CODECS)
            sound = bool(self.info.has_audio) and s.audio != "none"
            self.loud.setEnabled(sound)
            self.peak.setEnabled(sound and export.wants_loudness(s))
        target = export.uses_target(s)
        self.qval.setEnabled(not target)
        self.bitrate.setEnabled(not target)

    # ------------------------------------------------------------ desempenho
    def _perf_group(self, perf: dict) -> QGroupBox:
        g = QGroupBox(_("Desempenho"))
        v = QVBoxLayout(g)
        total, avail = system.ram()
        cores = system.cpu_threads()
        gpus = system.nvidia_gpus()
        nv = ", ".join(f"{n} ({m // 1024} GB)" for _idx, n, m in gpus) or _("nenhuma placa NVIDIA")
        info = QLabel("<br>".join([
            "<b>" + _("Esta máquina") + "</b>",
            _("Processador: {cpu} • {n} núcleos lógicos").format(cpu=system.cpu_name(), n=cores),
            _("Memória: {total} ({livre} livres agora)").format(total=system.gb(total), livre=system.gb(avail)),
            _("Placa que processa os efeitos: {placa}").format(placa=self.gpu_name or "GPU"),
            _("Codificação por GPU: {placas}").format(placas=nv),
        ]))
        info.setObjectName("Muted")
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(info)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        trow = QHBoxLayout()
        self.threads = QSpinBox()
        self.threads.setRange(0, cores)
        self.threads.setSpecialValueText(_("Todos ({n})").format(n=cores))
        self.threads.setValue(int(perf.get("threads", 0)))
        self.threads.setToolTip(_("Quantos núcleos o ffmpeg pode usar para ler, converter e codificar. "
                                  "Menos núcleos deixa o computador mais livre, mas exporta mais devagar."))
        trow.addWidget(self.threads)
        tslider = FilmSlider(0, cores, 1, 0)
        tslider.setValue(self.threads.value())
        tslider.valueChanged.connect(lambda x: self.threads.setValue(int(round(x))))
        self.threads.valueChanged.connect(lambda x: tslider.setValue(x))
        trow.addWidget(tslider, 1)
        form.addRow(_("Núcleos do processador"), trow)
        self.priority = compact(QComboBox())
        for key, lab in export.PRIORITIES:
            self.priority.addItem(_(lab), key)
        self.priority.setCurrentIndex(max(0, self.priority.findData(perf.get("priority", "normal"))))
        form.addRow(_("Prioridade"), self.priority)
        self.hw = compact(QComboBox())
        self.hw.addItem(_(export.HWACCEL_LABELS["none"]), "none")
        self.hw.addItem(_(export.HWACCEL_LABELS["auto"]), "auto")
        try:
            accels = media.hwaccels()
        except RuntimeError:
            accels = []
        for key in ("cuda", "d3d11va", "dxva2", "qsv"):
            if key in accels and (key != "cuda" or gpus):
                self.hw.addItem(_(export.HWACCEL_LABELS[key]), key)
        self.hw.setCurrentIndex(max(0, self.hw.findData(perf.get("hwaccel", "none"))))
        self.hw.setToolTip(_("Usa a placa de vídeo para decodificar o arquivo de entrada. Ajuda com H.264/H.265 "
                             "pesados; em muitos casos a diferença é pequena."))
        form.addRow(_("Decodificação por hardware"), self.hw)
        self.gpu = compact(QComboBox())
        for idx, name, mem in gpus or [(0, _("Placa {n}").format(n=0), 0)]:
            self.gpu.addItem(f"{idx}: {name}" + (f" ({mem // 1024} GB)" if mem else ""), idx)
        self.gpu.setCurrentIndex(max(0, self.gpu.findData(int(perf.get("gpu", 0)))))
        self.gpu.setToolTip(_("Placa usada pelos codecs NVIDIA (NVENC)."))
        form.addRow(_("Placa para codificar"), self.gpu)
        mrow = QHBoxLayout()
        self.buffer = QSpinBox()
        self.buffer.setRange(2, 64)
        self.buffer.setSuffix(" " + _("quadros"))
        self.buffer.setValue(int(perf.get("buffer", 4)))
        self.buffer.setToolTip(_("Quadros guardados na memória entre leitura, efeitos e gravação. "
                                 "Mais quadros suaviza variações de velocidade, mas usa mais RAM."))
        mrow.addWidget(self.buffer)
        self.mem_label = QLabel()
        self.mem_label.setObjectName("Faint")
        mrow.addWidget(self.mem_label, 1)
        form.addRow(_("Memória (buffer)"), mrow)
        self.buffer.valueChanged.connect(self._update_mem)
        v.addLayout(form)
        tip = QLabel(_("Os efeitos rodam na placa de vídeo principal do Windows. Em notebooks com duas placas, "
                       "escolha \"Alto desempenho\" para o Python em Configurações > Sistema > Tela > Gráficos."))
        tip.setObjectName("Faint")
        tip.setWordWrap(True)
        v.addWidget(tip)
        return g

    def _frame_bytes(self) -> int:
        s = self.settings()
        if not s.codec:
            return 0
        w, h = export.output_size(self.info, s)
        return w * h * (4 if export.wants_alpha(s) else 3) * (2 if export.high_depth(s) else 1)

    def _update_mem(self, *_args):
        fb = self._frame_bytes()
        if not fb:
            return
        _total, avail = system.ram()
        mx = int(max(2, min(64, avail * 0.5 // (2 * fb))))
        self.buffer.setMaximum(mx)
        use = self.buffer.value() * 2 * fb + 3 * fb
        self.mem_label.setText(_("≈ {mb} MB de RAM • máximo seguro agora: {maximo}").format(
            mb=fmt_int(use / (1 << 20)), maximo=mx))

    def perf_dict(self) -> dict:
        return {"threads": self.threads.value(), "priority": self.priority.currentData(),
                "hwaccel": self.hw.currentData(), "gpu": self.gpu.currentData() or 0, "buffer": self.buffer.value()}

    # ------------------------------------------------------------ preenchimento
    def _set_combo(self, combo: QComboBox, data) -> None:
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _fill_codec_fields(self, key: str) -> None:
        c = export.CODECS[key]
        self.container.clear()
        for e in c["exts"]:
            self.container.addItem("." + e, e)
        self.pix.clear()
        for pf in c["pix"]:
            if media.pix_has_alpha(pf):
                continue  # com alfa: "Manter a transparência" (`_alpha_rows`)
            self.pix.addItem(f"{_(PIX_NAMES.get(pf, pf))}  ({pf})", pf)
        rc = c.get("rc")
        self.speed.clear()
        for s in c.get("presets", []):
            self.speed.addItem(s, s)
        self.profile.clear()
        for val, lab in c.get("profiles", []):
            self.profile.addItem(_(lab), val)
        self.form.setRowVisible(self.speed, bool(c.get("presets")) and not self.info.is_image)
        self.form.setRowVisible(self.profile, bool(c.get("profiles")))
        has_q = rc in Q_LABELS
        self.form.setRowVisible(self.qval, has_q)
        self.form.setRowVisible(self.bitrate, rc in ("crf", "cq", "gq", "qp") and not self.info.is_image)
        if has_q:
            lo, hi = c["qrange"]
            self.qval.setRange(lo, hi)
            self.qlabel.setText(_(Q_LABELS[rc]))
        self.grain.setVisible(bool(c.get("grain")))
        if hasattr(self, "gpu"):
            self.gpu.setEnabled(bool(c.get("gpu")))
        self._res_labels(key)
        self._sync_alpha()

    def _res_labels(self, codec: str) -> None:
        """Cada resolução mostra o tamanho que sai deste arquivo (o número vale para o lado menor)."""
        names = dict(export.RESOLUTIONS)
        for i in range(self.res.count()):
            key = self.res.itemData(i)
            w, h = export.output_size(self.info, export.ExportSettings(codec=codec, resolution=key))
            self.res.setItemText(i, f"{_(names[key])} — {w} × {h}")

    def _apply(self, s: export.ExportSettings) -> None:
        self._building = True
        self._set_combo(self.codec, s.codec)
        self._fill_codec_fields(s.codec)
        self._set_combo(self.container, s.container)
        self._set_combo(self.pix, export.opaque_pix(s.codec, s.pix))
        if media.pix_has_alpha(s.pix) and export.supports_alpha(s.codec):
            self.alpha_box.setChecked(True)
        self._set_combo(self.speed, s.preset)
        self._set_combo(self.profile, s.profile)
        if export.CODECS[s.codec].get("rc") in Q_LABELS:
            self.qval.setValue(s.quality)
        self.bitrate.setValue(s.bitrate)
        self._set_combo(self.res, s.resolution)
        self._set_combo(self.fps, s.fps)
        self._set_combo(self.audio, s.audio)
        self.grain.setChecked(s.tune_grain)
        self.dither.setChecked(s.dither)
        if self.frame_box.findData(s.frame) < 0:
            self._add_frame(s.frame)
        self._set_combo(self.frame_box, s.frame)
        self._set_combo(self.fit_box, s.fit)
        self.target.setValue(float(s.target_mb))
        self._set_loudness(s.loudness)
        self.peak.setValue(float(s.true_peak))
        self.net_grain.setChecked(bool(s.net_grain))
        self._maxrate = float(s.maxrate)
        self._set_combo(self.platform, s.platform)
        self._building = False
        self._fix_ext()
        self._summary()
        if hasattr(self, "buffer"):
            self._update_mem()

    def settings(self) -> export.ExportSettings:
        s = export.ExportSettings(
            codec=self.codec.currentData(), container=self.container.currentData() or "mp4",
            pix=self.pix.currentData() or "yuv420p", quality=self.qval.value(), preset=self.speed.currentData() or "",
            profile=self.profile.currentData() or "", bitrate=self.bitrate.value(),
            resolution=self.res.currentData(), fps=self.fps.currentData(), audio=self.audio.currentData(),
            # isHidden e não isVisible: depois de "Adicionar à fila" a janela já fechou e nada mais é visível.
            tune_grain=self.grain.isChecked() and not self.grain.isHidden(), dither=self.dither.isChecked())
        if self.keeps_alpha():
            s.pix = export.alpha_pix(s.codec, s.pix)
            if s.codec == "prores" and s.profile not in ("4", "5"):
                s.profile = "4"  # só o ProRes 4444 guarda o alfa
        if not self.info.is_image:
            s.platform = self.platform_id()
            s.frame = self.frame_box.currentData() or ""
            s.fit = self.fit_box.currentData() or fitmod.CORTAR
            s.target_mb = self.target.value() if s.codec in export.TWO_PASS_CODECS else 0.0
            s.maxrate = self._maxrate
            s.loudness = float(self.loud.currentData() or 0.0) if self.info.has_audio else 0.0
            s.true_peak = self.peak.value()
            s.net_grain = self.net_grain.isChecked()
        if hasattr(self, "buffer"):
            p = self.perf_dict()
            s.threads, s.priority, s.hwaccel, s.gpu, s.buffer = (p["threads"], p["priority"], p["hwaccel"],
                                                                 p["gpu"], p["buffer"])
        s.no_effects = self.no_effects
        return s

    def _quality_changed(self) -> None:
        key = self.quality.currentData()
        for k, label, s in self.presets:
            if k == key:
                self._apply(s)
                self.qdesc.setText(_describe(k))
                return
        if not self.platform_id():  # "Nenhuma" no ajuste livre: tira o que a plataforma tinha posto
            s, neutral = self.settings(), export.ExportSettings()
            for k in PLATFORM_KEYS:
                setattr(s, k, getattr(neutral, k))
            s.net_grain = self.net_grain.isChecked()
            self._apply(s)
        self.qdesc.setText(_("Ajuste livre de todas as opções abaixo."))

    def _codec_changed(self) -> None:
        if self._building:
            return
        key = self.codec.currentData()
        self._building = True
        self._fill_codec_fields(key)
        c = export.CODECS[key]
        rc = c.get("rc")
        if rc in Q_DEFAULT:
            q = Q_DEFAULT[rc]
            if key == "av1":
                q = 24
            elif key == "vp9":
                q = 30
            self.qval.setValue(q)
        if key == "prores":
            self._set_combo(self.profile, "3")
        if key in P_DEFAULT:
            self._set_combo(self.speed, P_DEFAULT[key])
        if key == "gif":
            self._set_combo(self.res, "480")
            self._set_combo(self.fps, "15")
        self._building = False
        self._fix_ext()
        self._custom()

    def _custom(self, *_args):
        if self._building:
            return
        self.quality.blockSignals(True)
        self.quality.setCurrentIndex(self.quality.count() - 1)
        self.quality.blockSignals(False)
        self.qdesc.setText(_("Ajuste livre de todas as opções abaixo."))
        self._summary()

    def _fix_ext(self, *_args):
        ext = self.container.currentData() or "mp4"
        cur = self.path.text().strip()
        if not cur:
            stem = self._stem()
            self._auto_stem = stem
            cur = str(Path(self.out_dir) / f"{stem}.{ext}")
        else:
            cur = str(Path(cur).with_suffix("." + ext))
        self.path.setText(cur)

    def _browse(self) -> None:
        ext = self.container.currentData() or "mp4"
        path, _filter = QFileDialog.getSaveFileName(self, _("Salvar como"), self.path.text(),
                                                    _("Arquivo (*.{ext})").format(ext=ext))
        if path:
            self.path.setText(str(Path(path).with_suffix("." + ext)))

    def _summary(self, *_args):
        s = self.settings()
        if not s.codec:
            return
        w, h = export.output_size(self.info, s)
        fps = self.info.fps if s.fps == "original" else export.eval_fraction(s.fps)
        if self.info.is_image:
            self.summary.setText(_("Saída: {w}×{h} • {bits} bits por canal").format(
                w=w, h=h, bits=16 if export.high_depth(s) else 8))
            return
        self._sync_rows(s)
        self._platform_info()
        dur = self._duration()
        frames = round(dur * fps)
        depth = 16 if export.high_depth(s) else 8
        mins = int(dur // 60)
        secs = dur - mins * 60
        size = ""
        if s.bitrate > 0 and not export.uses_target(s):
            mb = s.bitrate * dur / 8
            size = f" • ~{mb / 1000:.1f} GB" if mb > 1000 else f" • ~{mb:.0f} MB"
        elif s.maxrate > 0 and s.codec in export.TWO_PASS_CODECS and not export.uses_target(s):
            size = " • " + _("teto de {taxa} Mb/s").format(taxa=fmt_decimal(s.maxrate, 1))
        self.summary.setText(_("Saída: {w}×{h} • {fps} quadros/s • {duracao} • {quadros} quadros • "
                               "processamento em {bits} bits por canal").format(
            w=w, h=h, fps=f"{fps:.3f}", duracao=f"{mins}min{secs:04.1f}s", quadros=frames, bits=depth) + size
            + (" • " + _("com transparência") if export.wants_alpha(s) else ""))
        self._schedule_estimate()
        self._warnings(s, dur)
        self._schedule_preview()

    def _warnings(self, s: export.ExportSettings, dur: float) -> None:
        """Avisos: limites da plataforma (duração, tamanho estimado), duas passadas e som recodificado."""
        out = []
        p = self.current_platform()
        if p is not None:
            out += platforms.warnings(p, dur, export.estimate_bytes(s, self.info, dur, self._vbps))
        if export.uses_target(s):
            if export.target_bitrate(s, self.info, dur) < export.MIN_TARGET_RATE:
                out.append(export.target_too_small_message(s, dur))
            else:
                out.append(_("Tamanho alvo de {mb} MB: duas passadas, leva cerca do dobro do tempo.").format(
                    mb=export.fmt_mb(float(s.target_mb))))
        if export.audio_reencoded_for_volume(s, self.info):
            out.append(_("O som vai ser recodificado: copiar o original não deixa acertar o volume nem o "
                         "tamanho do arquivo."))
        self.warn.setText("\n".join("⚠ " + t for t in out))
        self.warn.setVisible(bool(out))

    # ------------------------------------------------------------ tempo estimado
    def _range(self) -> tuple[int, int]:
        """Quadros (início, fim inclusivo; -1 = até o fim) que saem, com o corte na duração da plataforma."""
        a, b = self.in_out if (self.r_sel.isChecked() and self.in_out) else (0, -1)
        p = self.current_platform()
        if p is not None and p.max_s and not self.trim_max.isHidden() and self.trim_max.isChecked():
            last = self.info.frames - 1 if b < 0 else b
            n = max(1, int(math.floor(p.max_s * self.info.fps + 1e-6)))
            b = min(last, a + n - 1)
        return a, b

    def _duration(self, trim: bool = True) -> float:
        """Duração (s) do que sai: vídeo inteiro ou trecho, e o corte na duração máxima (`trim`)."""
        if trim:
            a, b = self._range()
        else:
            a, b = self.in_out if (self.r_sel.isChecked() and self.in_out) else (0, -1)
        b = self.info.frames - 1 if b < 0 else b
        return (b - a + 1) / self.info.fps

    def _cancel_estimate(self) -> None:
        if self._est_cancel is not None:
            self._est_cancel.set()
            self._est_cancel = None

    def _schedule_estimate(self) -> None:
        if not hasattr(self, "_est_timer"):
            return
        self._cancel_estimate()
        self._est_token += 1
        self._vbps = 0.0
        self.est_label.setText(_("Tempo estimado: medindo a velocidade desta máquina…"))
        self._est_timer.start()

    def _start_estimate(self) -> None:
        s = self.settings()
        if not s.codec:
            return
        token = self._est_token
        cancel = threading.Event()
        self._est_cancel = cancel
        info, values, seq, keys = self.info, dict(self.values), self.sequence, dict(self.look_keys)

        def run():
            stats: dict = {}
            try:
                fps = export.measure_speed(info, values, s, cancel, sequence=seq, stats=stats, keys=keys)
            except Exception:  # noqa: BLE001
                fps = 0.0
            if not cancel.is_set():
                self._bridge.done.emit(token, fps, float(stats.get("video_bytes_per_second", 0.0)))

        threading.Thread(target=run, daemon=True).start()

    def _est_done(self, token: int, fps: float, vbps: float = 0.0) -> None:
        if token != self._est_token:
            return
        self._est_cancel = None
        if fps <= 0:
            self.est_label.setText(_("Tempo estimado: não foi possível medir com estas opções."))
            return
        a, b = self._range()
        s = self.settings()
        frames = export.job_frames(self.info, s, a, b)
        passes = 2 if export.uses_target(s) else 1  # tamanho alvo: a GPU renderiza duas vezes
        secs = frames / fps * passes + 2
        if self.info.is_image:
            self.est_label.setText(_("Tempo estimado: {tempo}").format(tempo=fmt_dur(secs)))
            return
        text = _("Tempo estimado: ≈ {tempo}  •  {fps} quadros/s medidos agora nesta máquina "
                 "com estas opções").format(tempo=fmt_dur(secs), fps=fmt_decimal(fps, 1))
        if passes == 2:
            text += "  •  " + _("duas passadas")
        self.est_label.setText(text)
        if vbps > 0:  # tamanho provável (qualidade constante): os avisos de tamanho da plataforma
            self._vbps = vbps
            self._warnings(s, self._duration())

    # ------------------------------------------------------------ prévia do resultado
    def _schedule_preview(self) -> None:
        if not hasattr(self, "_preview_timer") or self.info.is_image:
            return
        self._preview_timer.start()

    def _preview_args(self) -> tuple:
        s = self.settings()
        ow, oh = export.output_size(self.info, s)
        scale = min(1.0, PREVIEW_MAX / max(ow, oh))
        a, b = self._range()
        last = self.info.frames - 1 if b < 0 else b
        frame = max(a, min(self.frame_index, last))
        return self.info, dict(self.values), s, frame, self.sequence, scale, dict(self.look_keys), self.burn()

    def _start_preview(self) -> None:
        args = self._preview_args()
        s = args[2]
        key = (export.output_size(self.info, s), s.frame, s.fit, s.net_grain, s.fps, s.dither, args[3],
               self.subtitle_choice(), export.wants_alpha(s))
        if key == self._preview_key:
            return
        self._preview_key = key
        self._preview_token += 1
        if self.preview.pixmap() is None or self.preview.pixmap().isNull():
            self.preview.setText(_("Renderizando…"))
        self._preview_worker.request(self._preview_token, args)

    def _preview_done(self, token: int, img) -> None:
        if token != self._preview_token:
            return
        if img is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(_("Prévia indisponível"))
            return
        from .alphaview import over_checker
        arr = over_checker(img)  # com transparência: sobre o xadrez (3 canais passam direto, em 8 bits)
        h, w = arr.shape[:2]
        qimg = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        pm = QPixmap.fromImage(qimg).scaled(PREVIEW_BOX - 2, PREVIEW_BOX - 2, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        self.preview.setText("")
        self.preview.setPixmap(pm)
        w, h = self._preview_key[0] if self._preview_key else (w, h)
        self.preview_caption.setText(_("Prévia do resultado • {w} × {h}").format(w=w, h=h))

    def done(self, r: int) -> None:
        self._est_timer.stop()
        self._cancel_estimate()
        self._preview_timer.stop()
        self._preview_worker.stop()
        super().done(r)

    def _accept(self) -> None:
        path = self.path.text().strip()
        if not path:
            return
        if os.path.abspath(path) == os.path.abspath(self.info.path):
            QMessageBox.warning(self, _("Exportar"), _("Escolha um nome diferente do arquivo original."))
            return
        s = self.settings()
        if export.queue_clash(path, s, self.queue_jobs):
            free = export.free_output(path, s, self.queue_jobs)
            r = QMessageBox.question(self, _("Exportar"), _(
                "A fila já tem uma exportação gravando em:\n{caminho}\n\nPara não sobrescrever, salvar esta como "
                "{nome}?").format(caminho=export.output_target(path, s), nome=Path(free).name))
            if r != QMessageBox.StandardButton.Yes:
                return
            path = free
            self.path.setText(path)
        clash = export.partial_clash(path, s, export.job_inputs(self.info, self.sequence))
        if clash:
            QMessageBox.warning(self, _("Exportar"), export.partial_clash_message(clash))
            return
        if export.output_exists(path, s):
            if export.is_sequence(s):
                text = _("A pasta já tem uma sequência de quadros com este nome:\n{caminho}\n\nSubstituir? Os "
                         "quadros antigos só são trocados quando a exportação terminar.")
            else:
                text = _("O arquivo já existe:\n{caminho}\n\nSubstituir? O arquivo antigo só é trocado quando a "
                         "exportação terminar.")
            r = QMessageBox.question(self, _("Exportar"), text.format(caminho=export.output_target(path, s)))
            if r != QMessageBox.StandardButton.Yes:
                return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.accept()

    def job(self) -> export.ExportJob:
        a, b = self._range()
        return export.ExportJob(info=self.info, values=dict(self.values), settings=self.settings(),
                                out_path=self.path.text().strip(), start_frame=a, end_frame=b,
                                name=f"{Path(self.path.text()).name}  •  {self.preset_name}",
                                sequence=self.sequence, chapters=self.chapter_points(),
                                look_keys=dict(self.look_keys),
                                **subs_mod.delivery_fields(self.subtitle_choice(), self.subs_doc, self.subs_cues,
                                                           self.container.currentData()))

    # ---------------------------------------------------------------- transparência
    def _alpha_rows(self, form: QFormLayout) -> None:
        """"Manter a transparência": só com a montagem em "Fundo transparente" e um codec que guarda alfa."""
        self.alpha_box = QCheckBox(_("Manter a transparência (canal alfa)"))
        transparent = bool(getattr(self.sequence, "transparent", False))
        self.alpha_box.setChecked(transparent)
        self.alpha_note = QLabel()
        self.alpha_note.setObjectName("Faint")
        self.alpha_note.setWordWrap(True)
        form.addRow("", self.alpha_box)
        form.addRow("", self.alpha_note)
        if self.info.is_image:
            form.setRowVisible(self.alpha_box, False)
            form.setRowVisible(self.alpha_note, False)

    def _sync_alpha(self) -> None:
        if not hasattr(self, "alpha_box"):
            return
        transparent = bool(getattr(self.sequence, "transparent", False))
        ok = export.supports_alpha(self.codec.currentData() or "")
        self.alpha_box.setEnabled(transparent and ok)
        if not transparent:
            text = _("Para exportar com transparência, ligue \"Fundo transparente\" em Configurar a sequência.")
        elif not ok:
            text = _("Este formato não guarda transparência: o fundo sai na cor da sequência. Use ProRes 4444, "
                     "WebM VP9 ou uma sequência PNG ou TIFF.")
        else:
            text = _("Onde nada cobre a tela, o vídeo sai transparente.")
        self.alpha_note.setText(text)

    def keeps_alpha(self) -> bool:
        """A exportação vai sair com transparência (opção marcada e disponível)."""
        return (hasattr(self, "alpha_box") and self.alpha_box.isChecked() and self.alpha_box.isEnabled()
                and not self.info.is_image)

    # ---------------------------------------------------------------- capítulos
    def _chapters_box(self) -> QCheckBox:
        """Incluir capítulos: aparece só quando a montagem tem capítulos; ligado por padrão."""
        box = QCheckBox(_("Incluir capítulos ({n}) — dos marcadores marcados como capítulo").format(
            n=len(self.chapters)))
        box.setChecked(True)
        box.setVisible(bool(self.chapters) and not self.info.is_image)
        return box

    def _sync_chapters(self, *_args) -> None:
        ok = self.container.currentData() in chapters_mod.CONTAINERS
        self.chapters_box.setEnabled(ok)
        self.chapters_box.setToolTip("" if ok else _("Só MP4, MOV e MKV guardam capítulos."))

    # ---------------------------------------------------------------- legendas
    def _subtitles_row(self) -> QWidget:
        """Legendas: aparece só quando a montagem tem legendas (padrão: o que o projeto pede)."""
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(_("Legendas"))
        hl.addWidget(lab)
        self.subs_box = QComboBox()
        for key in subs_mod.DELIVERY:
            self.subs_box.addItem(_(SUBTITLE_LABELS[key]), key)
        self.subs_box.setToolTip(_("Faixa no arquivo: o player liga e desliga (MP4, MOV, MKV e WebM). Gravada na "
                                   "cópia: entra antes do look, como numa cópia de cinema legendada. Digital: entra "
                                   "depois do look, nítida. Arquivo ao lado: .srt ou .vtt com o mesmo nome do vídeo."))
        self.subs_box.currentIndexChanged.connect(self._schedule_preview)
        hl.addWidget(self.subs_box, 1)
        w.setVisible(bool(self.subs_cues) and self.subs_doc is not None)
        return w

    def _init_subtitles(self) -> None:
        self._set_combo(self.subs_box, subs_mod.default_delivery(self.subs_doc if self.subs_cues else None,
                                                                  self.container.currentData()))
        self._sync_subtitles()

    def _sync_subtitles(self, *_args) -> None:
        """A faixa só nos recipientes que guardam legenda; escolhida num que não guarda, vira o .srt ao lado."""
        ok = self.container.currentData() in subs_mod.EMBED_CODECS
        item = self.subs_box.model().item(self.subs_box.findData("faixa"))
        if item is not None:
            item.setEnabled(ok)
            item.setToolTip("" if ok else _("Só MP4, MOV, MKV e WebM guardam faixa de legenda."))
        if not ok and self.subs_box.currentData() == "faixa":
            self._set_combo(self.subs_box, "srt")

    def subtitle_choice(self) -> str:
        if not self.subs_cues or self.subs_doc is None or self.subs_row.isHidden():
            return "nao"
        return str(self.subs_box.currentData() or "nao")

    def burn(self):
        """As legendas gravadas que a prévia do resultado mostra (`subtitles.Burn`), ou None."""
        choice = self.subtitle_choice()
        if choice not in ("copia", "digital"):
            return None
        return subs_mod.Burn.make(choice, self.subs_doc.style, self.subs_cues)

    def chapter_points(self) -> list[tuple[int, str]]:
        """Capítulos que vão para o arquivo (vazio se a opção está desligada ou o recipiente não guarda)."""
        if not self.chapters or self.chapters_box.isHidden() or not self.chapters_box.isChecked():
            return []
        if self.container.currentData() not in chapters_mod.CONTAINERS:
            return []
        return list(self.chapters)


def _describe(key: str) -> str:
    return {
        "original": _("Mesmo codec, resolução, quadros por segundo e profundidade de cor do arquivo original, "
                      "com qualidade alta para não perder detalhe. O áudio é copiado sem recodificar."),
        "mp4": _("O formato que abre em qualquer celular, computador, TV e rede social."),
        "mov": _("Formato preferido da Apple. Abre no iPhone, QuickTime e Final Cut."),
        "mkv": _("H.265 ocupa cerca de metade do espaço do H.264 com a mesma qualidade."),
        "prores_hq": _("Ideal para continuar editando no Premiere, Resolve ou Final Cut. Arquivo grande."),
        "prores_xq": _("A maior qualidade do ProRes, com cor 4:4:4. Arquivos muito grandes."),
        "dnxhr_hqx": _("Equivalente ao ProRes, muito usado no Avid e no Premiere no Windows."),
        "ffv1": _("Sem nenhuma perda: guarda exatamente o resultado do processamento em 16 bits. Ótimo para arquivar."),
        "yt4k_hevc": _("Envie em 4K mesmo que o vídeo seja menor: o YouTube dá mais qualidade e preserva melhor o grão."),
        "yt4k_h264": _("Compatível com tudo. Envie em 4K para o YouTube preservar o grão."),
        "fhd": _("Boa qualidade para guardar ou enviar."),
        "social": _("Equilíbrio entre tamanho e qualidade para redes sociais e mensageiros. O 1080p vale para o lado "
                    "menor: um vídeo vertical sai 1080 × 1920."),
        "leve": _("Arquivo pequeno para prévias e envio rápido."),
        "webm": _("Formato aberto, ideal para colocar em sites. Abre em todos os navegadores."),
        "avi": _("Para aparelhos de DVD, TVs e players antigos."),
        "gif": _("Animação sem som para mensagens e sites. Use trechos curtos (marque entrada e saída)."),
        "gpu": _("Exporta muito mais rápido usando a placa de vídeo NVIDIA."),
        "gpu_intel": _("Exporta mais rápido usando o vídeo integrado da Intel."),
        "gpu_amd": _("Exporta mais rápido usando a placa de vídeo AMD."),
        "png_seq": _("Um PNG de 16 bits por quadro, para composição e efeitos visuais."),
        "img_png": _("Imagem sem perdas em 16 bits."),
        "img_tiff": _("Imagem sem perdas em 16 bits, para gráficas e Photoshop."),
        "img_jpg": _("Imagem leve em alta qualidade."),
        "img_webp": _("Imagem leve para sites."),
    }.get(key, "")
