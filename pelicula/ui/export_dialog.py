"""Janela de exportação: qualidades prontas, opções do arquivo e desempenho da máquina."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QRadioButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from .. import export, media, system
from . import icons, theme
from .widgets import FilmSlider, compact, timecode

PIX_NAMES = {"yuv420p": "4:2:0 8 bits", "yuv422p": "4:2:2 8 bits", "yuv444p": "4:4:4 8 bits",
             "yuv420p10le": "4:2:0 10 bits", "yuv422p10le": "4:2:2 10 bits", "yuv444p10le": "4:4:4 10 bits",
             "yuv420p12le": "4:2:0 12 bits", "p010le": "4:2:0 10 bits", "nv12": "4:2:0 8 bits",
             "yuv444p16le": "4:4:4 16 bits", "rgb48le": "RGB 16 bits", "rgb48be": "RGB 16 bits",
             "rgb24": "RGB 8 bits", "yuvj444p": "4:4:4 8 bits", "pal8": "256 cores"}
Q_LABELS = {"crf": "CRF (menor = melhor)", "cq": "CQ (menor = melhor)", "gq": "Qualidade (menor = melhor)",
            "qp": "QP (menor = melhor)", "qscale": "Qualidade (menor = melhor)", "jpgq": "Qualidade (menor = melhor)",
            "webpq": "Qualidade (maior = melhor)"}
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
                 perf: dict | None = None, gpu_name: str = ""):
        super().__init__(parent)
        self.info = info
        self.values = values
        self.preset_name = preset_name
        self.in_out = in_out
        self.gpu_name = gpu_name
        self.setWindowTitle("Exportar")
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
        k = QLabel("EXPORTAR")
        k.setObjectName("Kicker")
        lay.addWidget(k)
        t = QLabel(Path(info.path).name)
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 14pt;")
        lay.addWidget(t)
        sub = QLabel(f"Look: {preset_name}  •  {info.summary()}")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # destino
        row = QHBoxLayout()
        self.path = QLineEdit()
        row.addWidget(self.path, 1)
        b = QPushButton("Procurar…")
        b.setIcon(icons.icon("folder", theme.TEXT, 16))
        b.clicked.connect(self._browse)
        row.addWidget(b)
        g0 = QGroupBox("Destino")
        QVBoxLayout(g0).addLayout(row)
        lay.addWidget(g0)

        # qualidade
        g1 = QGroupBox("Formato e qualidade")
        v1 = QVBoxLayout(g1)
        self.quality = compact(QComboBox(), 20)
        self.quality.setMaxVisibleItems(24)
        self.presets = export.quality_presets(info)
        for key, label, _ in self.presets:
            self.quality.addItem(label, key)
        self.quality.addItem("Personalizado", "custom")
        v1.addWidget(self.quality)
        self.qdesc = QLabel()
        self.qdesc.setObjectName("Faint")
        self.qdesc.setWordWrap(True)
        v1.addWidget(self.qdesc)
        lay.addWidget(g1)

        # ajustes do arquivo
        g2 = QGroupBox("Ajustes do arquivo")
        form = QFormLayout(g2)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.codec = compact(QComboBox())
        image = info.is_image
        for key, c in export.CODECS.items():
            if bool(c.get("image")) != image or not export.available(key):
                continue
            self.codec.addItem(c["label"], key)
        self.container = compact(QComboBox())
        self.pix = compact(QComboBox())
        self.qval = QDoubleSpinBox()
        self.qval.setDecimals(0)
        self.qlabel = QLabel("Qualidade")
        self.bitrate = QDoubleSpinBox()
        self.bitrate.setRange(0, 2000)
        self.bitrate.setDecimals(1)
        self.bitrate.setSuffix(" Mb/s")
        self.bitrate.setSpecialValueText("Automática (qualidade constante)")
        self.speed = compact(QComboBox())
        self.profile = compact(QComboBox())
        self.res = compact(QComboBox())
        for key, lab in export.RESOLUTIONS:
            self.res.addItem(lab, key)
        self.fps = compact(QComboBox())
        for key, lab in export.FPS:
            self.fps.addItem(lab, key)
        self.audio = compact(QComboBox())
        for key, lab in export.AUDIO:
            self.audio.addItem(lab, key)
        self.grain = QCheckBox("Otimizar o codificador para grão (tune grain)")
        self.dither = QCheckBox("Pontilhado (dither) para evitar faixas em 8 bits")
        form.addRow("Codec", self.codec)
        form.addRow("Recipiente", self.container)
        form.addRow("Formato de cor", self.pix)
        form.addRow(self.qlabel, self.qval)
        form.addRow("Taxa de bits", self.bitrate)
        form.addRow("Velocidade", self.speed)
        form.addRow("Perfil", self.profile)
        form.addRow("Resolução", self.res)
        form.addRow("Quadros/s", self.fps)
        form.addRow("Áudio", self.audio)
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
        self.r_all = QRadioButton("Vídeo inteiro")
        self.r_sel = QRadioButton("Só o trecho marcado")
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
                self.r_sel.setText(f"Só o trecho marcado ({timecode(a, info.fps)} – {timecode(b2, info.fps)})")
            else:
                self.r_sel.setEnabled(False)
                self.r_sel.setToolTip("Marque entrada (I) e saída (O) na linha do tempo.")
            lay.addLayout(rr)
            self.r_sel.toggled.connect(self._summary)
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
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("  Adicionar à fila e exportar")
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

    # ------------------------------------------------------------ desempenho
    def _perf_group(self, perf: dict) -> QGroupBox:
        g = QGroupBox("Desempenho")
        v = QVBoxLayout(g)
        total, avail = system.ram()
        cores = system.cpu_threads()
        gpus = system.nvidia_gpus()
        nv = ", ".join(f"{n} ({m // 1024} GB)" for _, n, m in gpus) or "nenhuma placa NVIDIA"
        info = QLabel(f"<b>Esta máquina</b><br>Processador: {system.cpu_name()} • {cores} núcleos lógicos<br>"
                      f"Memória: {system.gb(total)} ({system.gb(avail)} livres agora)<br>"
                      f"Placa que processa os efeitos: {self.gpu_name or 'GPU'}<br>Codificação por GPU: {nv}")
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
        self.threads.setSpecialValueText(f"Todos ({cores})")
        self.threads.setValue(int(perf.get("threads", 0)))
        self.threads.setToolTip("Quantos núcleos o ffmpeg pode usar para ler, converter e codificar. "
                                "Menos núcleos deixa o computador mais livre, mas exporta mais devagar.")
        trow.addWidget(self.threads)
        tslider = FilmSlider(0, cores, 1, 0)
        tslider.setValue(self.threads.value())
        tslider.valueChanged.connect(lambda x: self.threads.setValue(int(round(x))))
        self.threads.valueChanged.connect(lambda x: tslider.setValue(x))
        trow.addWidget(tslider, 1)
        form.addRow("Núcleos do processador", trow)
        self.priority = compact(QComboBox())
        for key, lab in export.PRIORITIES:
            self.priority.addItem(lab, key)
        self.priority.setCurrentIndex(max(0, self.priority.findData(perf.get("priority", "normal"))))
        form.addRow("Prioridade", self.priority)
        self.hw = compact(QComboBox())
        self.hw.addItem(export.HWACCEL_LABELS["none"], "none")
        self.hw.addItem(export.HWACCEL_LABELS["auto"], "auto")
        try:
            accels = media.hwaccels()
        except RuntimeError:
            accels = []
        for key in ("cuda", "d3d11va", "dxva2", "qsv"):
            if key in accels and (key != "cuda" or gpus):
                self.hw.addItem(export.HWACCEL_LABELS[key], key)
        self.hw.setCurrentIndex(max(0, self.hw.findData(perf.get("hwaccel", "none"))))
        self.hw.setToolTip("Usa a placa de vídeo para decodificar o arquivo de entrada. Ajuda com H.264/H.265 "
                           "pesados; em muitos casos a diferença é pequena.")
        form.addRow("Decodificação por hardware", self.hw)
        self.gpu = compact(QComboBox())
        for idx, name, mem in gpus or [(0, "Placa 0", 0)]:
            self.gpu.addItem(f"{idx}: {name}" + (f" ({mem // 1024} GB)" if mem else ""), idx)
        self.gpu.setCurrentIndex(max(0, self.gpu.findData(int(perf.get("gpu", 0)))))
        self.gpu.setToolTip("Placa usada pelos codecs NVIDIA (NVENC).")
        form.addRow("Placa para codificar", self.gpu)
        mrow = QHBoxLayout()
        self.buffer = QSpinBox()
        self.buffer.setRange(2, 64)
        self.buffer.setSuffix(" quadros")
        self.buffer.setValue(int(perf.get("buffer", 4)))
        self.buffer.setToolTip("Quadros guardados na memória entre leitura, efeitos e gravação. "
                               "Mais quadros suaviza variações de velocidade, mas usa mais RAM.")
        mrow.addWidget(self.buffer)
        self.mem_label = QLabel()
        self.mem_label.setObjectName("Faint")
        mrow.addWidget(self.mem_label, 1)
        form.addRow("Memória (buffer)", mrow)
        self.buffer.valueChanged.connect(self._update_mem)
        v.addLayout(form)
        tip = QLabel("Os efeitos rodam na placa de vídeo principal do Windows. Em notebooks com duas placas, "
                     "escolha \"Alto desempenho\" para o Python em Configurações > Sistema > Tela > Gráficos.")
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

    def _update_mem(self, *_):
        fb = self._frame_bytes()
        if not fb:
            return
        _, avail = system.ram()
        mx = int(max(2, min(64, avail * 0.5 // (2 * fb))))
        self.buffer.setMaximum(mx)
        use = self.buffer.value() * 2 * fb + 3 * fb
        self.mem_label.setText(f"≈ {use / (1 << 20):,.0f} MB de RAM • máximo seguro agora: {mx}".replace(",", "."))

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
            self.pix.addItem(f"{PIX_NAMES.get(pf, pf)}  ({pf})", pf)
        rc = c.get("rc")
        self.speed.clear()
        for s in c.get("presets", []):
            self.speed.addItem(s, s)
        self.profile.clear()
        for val, lab in c.get("profiles", []):
            self.profile.addItem(lab, val)
        self.form.setRowVisible(self.speed, bool(c.get("presets")) and not self.info.is_image)
        self.form.setRowVisible(self.profile, bool(c.get("profiles")))
        has_q = rc in Q_LABELS
        self.form.setRowVisible(self.qval, has_q)
        self.form.setRowVisible(self.bitrate, rc in ("crf", "cq", "gq", "qp") and not self.info.is_image)
        if has_q:
            lo, hi = c["qrange"]
            self.qval.setRange(lo, hi)
            self.qlabel.setText(Q_LABELS[rc])
        self.grain.setVisible(bool(c.get("grain")))
        if hasattr(self, "gpu"):
            self.gpu.setEnabled(bool(c.get("gpu")))

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
        self.qdesc.setText("Ajuste livre de todas as opções abaixo.")

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

    def _custom(self, *_):
        if self._building:
            return
        self.quality.blockSignals(True)
        self.quality.setCurrentIndex(self.quality.count() - 1)
        self.quality.blockSignals(False)
        self.qdesc.setText("Ajuste livre de todas as opções abaixo.")
        self._summary()

    def _fix_ext(self, *_):
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
        path, _ = QFileDialog.getSaveFileName(self, "Salvar como", self.path.text(), f"Arquivo (*.{ext})")
        if path:
            self.path.setText(str(Path(path).with_suffix("." + ext)))

    def _summary(self, *_):
        s = self.settings()
        if not s.codec:
            return
        w, h = export.output_size(self.info, s)
        fps = self.info.fps if s.fps == "original" else export.eval_fraction(s.fps)
        if self.info.is_image:
            self.summary.setText(f"Saída: {w}×{h} • {'16' if export.high_depth(s) else '8'} bits por canal")
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
        self.summary.setText(f"Saída: {w}×{h} • {fps:.3f} quadros/s • {mins}min{secs:04.1f}s • {frames} quadros • "
                             f"processamento em {depth} bits por canal{size}")
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
        self.est_label.setText("Tempo estimado: medindo a velocidade desta máquina…")
        self._est_timer.start()

    def _start_estimate(self) -> None:
        s = self.settings()
        if not s.codec:
            return
        token = self._est_token
        cancel = threading.Event()
        self._est_cancel = cancel
        info, values = self.info, dict(self.values)

        def run():
            try:
                fps = export.measure_speed(info, values, s, cancel)
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
            self.est_label.setText("Tempo estimado: não foi possível medir com estas opções.")
            return
        a, b = self._range()
        frames = export.job_frames(self.info, self.settings(), a, b)
        secs = frames / fps + 2
        if self.info.is_image:
            self.est_label.setText(f"Tempo estimado: {fmt_dur(secs)}")
        else:
            self.est_label.setText(f"Tempo estimado: ≈ {fmt_dur(secs)}  •  {fps:.1f} quadros/s medidos agora "
                                   f"nesta máquina com estas opções".replace(".", ",", 1))

    def done(self, r: int) -> None:
        self._est_timer.stop()
        self._cancel_estimate()
        super().done(r)

    def _accept(self) -> None:
        path = self.path.text().strip()
        if not path:
            return
        if os.path.abspath(path) == os.path.abspath(self.info.path):
            QMessageBox.warning(self, "Exportar", "Escolha um nome diferente do arquivo original.")
            return
        if os.path.exists(path):
            r = QMessageBox.question(self, "Exportar", f"O arquivo já existe:\n{path}\n\nSubstituir?")
            if r != QMessageBox.StandardButton.Yes:
                return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.accept()

    def job(self) -> export.ExportJob:
        a, b = (self.in_out if (self.r_sel.isChecked() and self.in_out) else (0, -1))
        return export.ExportJob(info=self.info, values=dict(self.values), settings=self.settings(),
                                out_path=self.path.text().strip(), start_frame=a, end_frame=b,
                                name=f"{Path(self.path.text()).name}  •  {self.preset_name}")


def _describe(key: str) -> str:
    return {
        "original": "Mesmo codec, resolução, quadros por segundo e profundidade de cor do arquivo original, "
                    "com qualidade alta para não perder detalhe. O áudio é copiado sem recodificar.",
        "mp4": "O formato que abre em qualquer celular, computador, TV e rede social.",
        "mov": "Formato preferido da Apple. Abre no iPhone, QuickTime e Final Cut.",
        "mkv": "H.265 ocupa cerca de metade do espaço do H.264 com a mesma qualidade.",
        "prores_hq": "Ideal para continuar editando no Premiere, Resolve ou Final Cut. Arquivo grande.",
        "prores_xq": "A maior qualidade do ProRes, com cor 4:4:4. Arquivos muito grandes.",
        "dnxhr_hqx": "Equivalente ao ProRes, muito usado no Avid e no Premiere no Windows.",
        "ffv1": "Sem nenhuma perda: guarda exatamente o resultado do processamento em 16 bits. Ótimo para arquivar.",
        "yt4k_hevc": "Envie em 4K mesmo que o vídeo seja menor: o YouTube dá mais qualidade e preserva melhor o grão.",
        "yt4k_h264": "Compatível com tudo. Envie em 4K para o YouTube preservar o grão.",
        "fhd": "Boa qualidade para guardar ou enviar.",
        "social": "Equilíbrio entre tamanho e qualidade para redes sociais e mensageiros.",
        "leve": "Arquivo pequeno para prévias e envio rápido.",
        "webm": "Formato aberto, ideal para colocar em sites. Abre em todos os navegadores.",
        "avi": "Para aparelhos de DVD, TVs e players antigos.",
        "gif": "Animação sem som para mensagens e sites. Use trechos curtos (marque entrada e saída).",
        "gpu": "Exporta muito mais rápido usando a placa de vídeo NVIDIA.",
        "gpu_intel": "Exporta mais rápido usando o vídeo integrado da Intel.",
        "gpu_amd": "Exporta mais rápido usando a placa de vídeo AMD.",
        "png_seq": "Um PNG de 16 bits por quadro, para composição e efeitos visuais.",
        "img_png": "Imagem sem perdas em 16 bits.",
        "img_tiff": "Imagem sem perdas em 16 bits, para gráficas e Photoshop.",
        "img_jpg": "Imagem leve em alta qualidade.",
        "img_webp": "Imagem leve para sites.",
    }.get(key, "")
