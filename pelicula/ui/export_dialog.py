"""Janela de exportação: qualidades prontas, opções do arquivo e desempenho da máquina."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QRadioButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from .. import chapters as chapters_mod, export, media, system
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


def fmt_dur(sec: float) -> str:
    sec = int(round(max(sec, 1)))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


class _Bridge(QObject):
    done = Signal(int, float)


class ExportDialog(QDialog):
    def __init__(self, parent, info: media.MediaInfo, values: dict, preset_name: str,
                 in_out: tuple[int, int] | None, last_dir: str = "", last_quality: str = "",
                 perf: dict | None = None, gpu_name: str = "", sequence=None, chapters=None):
        super().__init__(parent)
        self.info = info
        self.sequence = sequence  # timeline.Sequence quando o que sai é a montagem do modo Edição
        self.chapters = list(chapters or [])  # [(quadro, título)] dos capítulos da montagem (`chapters.points`)
        self.values = values
        self.preset_name = preset_name
        self.in_out = in_out
        self.gpu_name = gpu_name
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
        t = QLabel((sequence.name or _("Montagem da edição")) if sequence is not None else Path(info.path).name)
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 14pt;")
        lay.addWidget(t)
        sub = QLabel(_("Look: {look}  •  {resumo}").format(look=preset_name, resumo=info.summary()))
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)

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
        lay.addWidget(g2)
        if image:
            for w in (self.fps, self.audio, self.grain, self.bitrate, self.speed):
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
        lay.addStretch(1)

        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(22, 8, 22, 16)
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
        for w in (self.qval, self.bitrate):
            w.valueChanged.connect(self._custom)
        for w in (self.grain, self.dither):
            w.toggled.connect(self._custom)
        self.res.currentIndexChanged.connect(self._update_mem)
        self.pix.currentIndexChanged.connect(self._update_mem)
        i = self.quality.findData(last_quality)
        self.quality.setCurrentIndex(i if i >= 0 else 0)
        self._quality_changed()
        self._update_mem()
        self._sync_chapters()

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
        return w * h * 3 * (2 if export.high_depth(s) else 1)

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
        self._set_combo(self.pix, s.pix)
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
            tune_grain=self.grain.isChecked() and self.grain.isVisible(), dither=self.dither.isChecked())
        if hasattr(self, "buffer"):
            p = self.perf_dict()
            s.threads, s.priority, s.hwaccel, s.gpu, s.buffer = (p["threads"], p["priority"], p["hwaccel"],
                                                                 p["gpu"], p["buffer"])
        return s

    def _quality_changed(self) -> None:
        key = self.quality.currentData()
        for k, label, s in self.presets:
            if k == key:
                self._apply(s)
                self.qdesc.setText(_describe(k))
                return
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
            stem = Path(self.info.path).stem + "_pelicula"
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
        a, b = (self.in_out if (self.r_sel.isChecked() and self.in_out) else (0, self.info.frames - 1))
        dur = (b - a + 1) / self.info.fps
        frames = round(dur * fps)
        depth = 16 if export.high_depth(s) else 8
        mins = int(dur // 60)
        secs = dur - mins * 60
        size = ""
        if s.bitrate > 0:
            mb = s.bitrate * dur / 8
            size = f" • ~{mb / 1000:.1f} GB" if mb > 1000 else f" • ~{mb:.0f} MB"
        self.summary.setText(_("Saída: {w}×{h} • {fps} quadros/s • {duracao} • {quadros} quadros • "
                               "processamento em {bits} bits por canal").format(
            w=w, h=h, fps=f"{fps:.3f}", duracao=f"{mins}min{secs:04.1f}s", quadros=frames, bits=depth) + size)
        self._schedule_estimate()

    # ------------------------------------------------------------ tempo estimado
    def _range(self) -> tuple[int, int]:
        return self.in_out if (self.r_sel.isChecked() and self.in_out) else (0, -1)

    def _cancel_estimate(self) -> None:
        if self._est_cancel is not None:
            self._est_cancel.set()
            self._est_cancel = None

    def _schedule_estimate(self) -> None:
        if not hasattr(self, "_est_timer"):
            return
        self._cancel_estimate()
        self._est_token += 1
        self.est_label.setText(_("Tempo estimado: medindo a velocidade desta máquina…"))
        self._est_timer.start()

    def _start_estimate(self) -> None:
        s = self.settings()
        if not s.codec:
            return
        token = self._est_token
        cancel = threading.Event()
        self._est_cancel = cancel
        info, values, seq = self.info, dict(self.values), self.sequence

        def run():
            try:
                fps = export.measure_speed(info, values, s, cancel, sequence=seq)
            except Exception:  # noqa: BLE001
                fps = 0.0
            if not cancel.is_set():
                self._bridge.done.emit(token, fps)

        threading.Thread(target=run, daemon=True).start()

    def _est_done(self, token: int, fps: float) -> None:
        if token != self._est_token:
            return
        self._est_cancel = None
        if fps <= 0:
            self.est_label.setText(_("Tempo estimado: não foi possível medir com estas opções."))
            return
        a, b = self._range()
        frames = export.job_frames(self.info, self.settings(), a, b)
        secs = frames / fps + 2
        if self.info.is_image:
            self.est_label.setText(_("Tempo estimado: {tempo}").format(tempo=fmt_dur(secs)))
        else:
            self.est_label.setText(_("Tempo estimado: ≈ {tempo}  •  {fps} quadros/s medidos agora nesta máquina "
                                     "com estas opções").format(tempo=fmt_dur(secs), fps=fmt_decimal(fps, 1)))

    def done(self, r: int) -> None:
        self._est_timer.stop()
        self._cancel_estimate()
        super().done(r)

    def _accept(self) -> None:
        path = self.path.text().strip()
        if not path:
            return
        if os.path.abspath(path) == os.path.abspath(self.info.path):
            QMessageBox.warning(self, _("Exportar"), _("Escolha um nome diferente do arquivo original."))
            return
        s = self.settings()
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
        a, b = (self.in_out if (self.r_sel.isChecked() and self.in_out) else (0, -1))
        return export.ExportJob(info=self.info, values=dict(self.values), settings=self.settings(),
                                out_path=self.path.text().strip(), start_frame=a, end_frame=b,
                                name=f"{Path(self.path.text()).name}  •  {self.preset_name}",
                                sequence=self.sequence, chapters=self.chapter_points())

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
