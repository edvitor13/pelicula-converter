"""Janela "Configurar a sequência": resolução, quadros por segundo, cor do fundo, emendas de som e faixa
principal magnética."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import timeline
from ..i18n import N_, _, fmt_decimal
from ..timeline import VIDEO, Sequence
from .widgets import ColorButton

# (chave, rótulo, largura, altura); "primeiro" e "custom" são resolvidos na hora.
RESOLUTIONS: list[tuple[str, str, int, int]] = [
    ("2160", N_("4K UHD — 3840 × 2160"), 3840, 2160),
    ("1440", N_("2K QHD — 2560 × 1440"), 2560, 1440),
    ("1080", N_("Full HD — 1920 × 1080"), 1920, 1080),
    ("720", N_("HD — 1280 × 720"), 1280, 720),
    ("vertical", N_("Vertical — 1080 × 1920 (Reels, TikTok, Shorts)"), 1080, 1920),
    ("quadrado", N_("Quadrado — 1080 × 1080"), 1080, 1080),
    ("4x5", N_("Retrato 4:5 — 1080 × 1350"), 1080, 1350),
]


def fps_label(fps_str: str) -> str:
    """"24000/1001" → "23,976 quadros/s"; "24/1" → "24 quadros/s"."""
    v = float(timeline.parse_fps(fps_str))
    txt = str(int(round(v))) if abs(v - round(v)) < 1e-6 else fmt_decimal(v, 3)
    return _("{fps} quadros/s").format(fps=txt)


def first_video_size(seq: Sequence) -> tuple[int, int] | None:
    vids = sorted((c for c in seq.clips if c.kind == VIDEO), key=lambda c: (c.start, c.track))
    for c in vids:
        src = seq.sources.get(c.src)
        if src is not None and src.width and src.height:
            return src.width, src.height
    return None


class SequenceDialog(QDialog):
    def __init__(self, parent, seq: Sequence):
        super().__init__(parent)
        self.setWindowTitle(_("Configurar a sequência"))
        self.setMinimumWidth(460)
        self.seq = seq
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        intro = QLabel(_("Tamanho e ritmo do vídeo montado. Os clipes se encaixam no quadro conforme o "
                         "\"Encaixe\" de cada um; mudar os quadros por segundo mantém o tempo dos cortes."))
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        form.setSpacing(8)
        self.res = QComboBox()
        self._first = first_video_size(seq)
        for key, label, w, h in RESOLUTIONS:
            self.res.addItem(_(label), key)
        if self._first:
            self.res.addItem(_("Igual ao primeiro clipe — {w} × {h}").format(w=self._first[0], h=self._first[1]),
                             "primeiro")
        self.res.addItem(_("Personalizado"), "custom")
        form.addRow(_("Resolução"), self.res)
        size = QWidget()
        sl = QHBoxLayout(size)
        sl.setContentsMargins(0, 0, 0, 0)
        self.w = QSpinBox()
        self.w.setRange(16, 8192)
        self.w.setSingleStep(2)
        self.h = QSpinBox()
        self.h.setRange(16, 8192)
        self.h.setSingleStep(2)
        sl.addWidget(self.w)
        sl.addWidget(QLabel("×"))
        sl.addWidget(self.h)
        sl.addStretch(1)
        form.addRow(_("Largura × altura"), size)
        self.fps = QComboBox()
        choices = list(timeline.FPS_CHOICES)
        if seq.fps_str not in choices:
            choices.append(seq.fps_str)
        for f in choices:
            self.fps.addItem(fps_label(f), f)
        self.fps.setCurrentIndex(max(0, self.fps.findData(seq.fps_str)))
        form.addRow(_("Quadros por segundo"), self.fps)
        self.bg = ColorButton()
        self.bg.color = QColor.fromRgbF(*[min(max(float(c), 0.0), 1.0) for c in seq.background])
        self.bg.clicked.connect(self._pick_bg)
        form.addRow(_("Cor do fundo"), self.bg)
        self.transp = QCheckBox(_("Fundo transparente"))
        self.transp.setChecked(bool(getattr(seq, "transparent", False)))
        self.transp.setToolTip(_("Onde nenhum clipe cobre a tela, o vídeo fica transparente em vez da cor do fundo: a "
                                 "prévia mostra um xadrez, \"Salvar quadro\" em PNG ou TIFF guarda a transparência e "
                                 "a exportação a mantém em ProRes 4444, WebM VP9 e sequências PNG ou TIFF. Nos "
                                 "outros formatos o fundo sai na cor escolhida."))
        form.addRow("", self.transp)
        self.micro = QCheckBox(_("Fades curtos nas emendas de som"))
        self.micro.setChecked(bool(seq.micro_fade))
        self.micro.setToolTip(_("Um fade de 5 ms onde um clipe de som começa ou termina no meio do arquivo, "
                                "para não estalar. Não vale onde o clipe já tem fade ou transição, nem num corte "
                                "que não foi mexido (o som continua igual)."))
        form.addRow(_("Som"), self.micro)
        self.magnet = QCheckBox(_("Faixa principal magnética"))
        self.magnet.setChecked(bool(seq.magnetic))
        self.magnet.setToolTip(_("A faixa V1 nunca fica com buracos: apagar, aparar ou mover um clipe dela fecha o "
                                 "espaço, e alongar empurra o resto. Títulos, imagens e sons nas outras faixas "
                                 "acompanham a imagem da V1 que estava embaixo deles. Desligada, a linha do tempo "
                                 "é livre."))
        form.addRow(_("Montagem"), self.magnet)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(_("Aplicar"))
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self.w.setValue(seq.width)
        self.h.setValue(seq.height)
        self.res.setCurrentIndex(self.res.findData(self._match(seq.width, seq.height)))
        self.res.currentIndexChanged.connect(self._res_changed)
        self._res_changed()

    def _match(self, w: int, h: int) -> str:
        for key, _label, rw, rh in RESOLUTIONS:
            if (rw, rh) == (w, h):
                return key
        if self._first and self._first == (w, h):
            return "primeiro"
        return "custom"

    def _res_changed(self, *_args) -> None:
        key = self.res.currentData()
        custom = key == "custom"
        self.w.setEnabled(custom)
        self.h.setEnabled(custom)
        size = None
        if key == "primeiro":
            size = self._first
        else:
            size = next(((w, h) for k, _l, w, h in RESOLUTIONS if k == key), None)
        if size:
            self.w.setValue(size[0])
            self.h.setValue(size[1])

    def _pick_bg(self) -> None:
        c = QColorDialog.getColor(self.bg.color, self, _("Cor do fundo"))
        if c.isValid():
            self.bg.color = c
            self.bg.update()

    def values(self) -> tuple[int, int, str, tuple[float, float, float]]:
        c = self.bg.color
        return int(self.w.value()), int(self.h.value()), str(self.fps.currentData()), (c.redF(), c.greenF(), c.blueF())

    def micro_fade(self) -> bool:
        return self.micro.isChecked()

    def magnetic(self) -> bool:
        return self.magnet.isChecked()

    def transparent(self) -> bool:
        return self.transp.isChecked()


__all__ = ["SequenceDialog", "RESOLUTIONS", "fps_label"]
