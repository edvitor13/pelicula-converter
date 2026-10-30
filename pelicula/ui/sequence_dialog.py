"""Janela "Configurar a sequência": resolução, proporção, quadros por segundo, cor do fundo, emendas de som e faixa
principal magnética."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget)

from .. import params, timeline
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

# Proporções do menu (1.7): as chaves e os rótulos são os de `params.PROPORCOES`, a "Moldura" do look.
RATIOS: tuple[str, ...] = ("1.33", "1.37", "1.43", "1.78", "1.85", "2.00", "2.20", "2.39", "2.76")
RATIO_LABELS = dict(params.PROPORCOES)
REAL, BARS = "real", "faixas"  # como a proporção sai


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
        ratio = QWidget()
        rl = QHBoxLayout(ratio)
        rl.setContentsMargins(0, 0, 0, 0)
        self.ratio = QComboBox()
        self.ratio.addItem(_("Do tamanho escolhido"), "")
        for key in RATIOS:
            self.ratio.addItem(_(RATIO_LABELS[key]), key)
        self.ratio.addItem(_("Personalizada"), "custom")
        self.ratio.setToolTip(_("A proporção da imagem do vídeo montado, como 2,39 (Scope)."))
        self.ratio_value = QDoubleSpinBox()
        self.ratio_value.setRange(1.0, 4.0)
        self.ratio_value.setDecimals(2)
        self.ratio_value.setSingleStep(0.01)
        self.ratio_value.setValue(2.39)
        rl.addWidget(self.ratio, 1)
        rl.addWidget(self.ratio_value)
        form.addRow(_("Proporção"), ratio)
        self.apply_as = QComboBox()
        self.apply_as.addItem(_("Quadro real"), REAL)
        self.apply_as.addItem(_("Faixas pretas no quadro"), BARS)
        self.apply_as.setToolTip(_("Quadro real: a largura ou a altura muda e o arquivo sai nesse tamanho, sem faixas. "
                                   "Faixas pretas no quadro: o tamanho fica e as faixas são gravadas na imagem; os "
                                   "clipes, títulos e legendas ficam dentro da janela que sobra."))
        form.addRow(_("Como aplicar"), self.apply_as)
        self.result = QLabel()
        self.result.setObjectName("Muted")
        self.result.setWordWrap(True)
        form.addRow("", self.result)
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
        if seq.window:  # a janela útil da sequência, no menu
            key = next((k for k in RATIOS if abs(float(k) - seq.window) < 1e-6), "custom")
            self.ratio.setCurrentIndex(self.ratio.findData(key))
            self.ratio_value.setValue(seq.window)
            self.apply_as.setCurrentIndex(self.apply_as.findData(BARS))
        for sig in (self.ratio.currentIndexChanged, self.ratio_value.valueChanged, self.apply_as.currentIndexChanged,
                    self.w.valueChanged, self.h.valueChanged):
            sig.connect(self._ratio_changed)
        self._res_changed()
        self._ratio_changed()

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

    def chosen_ratio(self) -> float:
        """A proporção escolhida no menu (0 = "Do tamanho escolhido")."""
        key = self.ratio.currentData()
        if not key:
            return 0.0
        return float(self.ratio_value.value()) if key == "custom" else float(key)

    def _ratio_changed(self, *_args) -> None:
        """Mostra na hora o que a proporção vai dar no tamanho escolhido em largura × altura."""
        ratio = self.chosen_ratio()
        self.ratio_value.setVisible(self.ratio.currentData() == "custom")
        self.apply_as.setEnabled(ratio > 0)
        self.result.setVisible(ratio > 0)
        if ratio <= 0:
            self.result.setText("")
            return
        fw, fh = int(self.w.value()), int(self.h.value())
        w, h = timeline.aspect_size(fw, fh, ratio)
        if (w, h) == (fw, fh):
            text = _("O quadro já tem essa proporção: {w} × {h}, sem faixas.").format(w=fw, h=fh)
        elif self.apply_as.currentData() == REAL:
            text = _("O quadro fica com {w} × {h}.").format(w=w, h=h)
        elif h < fh:
            text = _("Quadro de {w} × {h}, com faixas pretas em cima e embaixo: janela útil de {jw} × {jh}.").format(
                w=fw, h=fh, jw=w, jh=h)
        else:
            text = _("Quadro de {w} × {h}, com faixas pretas nas laterais: janela útil de {jw} × {jh}.").format(
                w=fw, h=fh, jw=w, jh=h)
        self.result.setText(text)

    def _pick_bg(self) -> None:
        c = QColorDialog.getColor(self.bg.color, self, _("Cor do fundo"))
        if c.isValid():
            self.bg.color = c
            self.bg.update()

    def values(self) -> tuple[int, int, str, tuple[float, float, float]]:
        c = self.bg.color
        w, h = int(self.w.value()), int(self.h.value())
        if self.apply_as.currentData() == REAL:  # "Quadro real" só preenche o tamanho: nada novo fica gravado
            w, h = timeline.aspect_size(w, h, self.chosen_ratio())
        return max(16, w), max(16, h), str(self.fps.currentData()), (c.redF(), c.greenF(), c.blueF())

    def window(self) -> float:
        """A janela útil da sequência (`Sequence.window`): só com "Faixas pretas no quadro" e se a proporção difere da
        do quadro; 0 = sem janela."""
        ratio = self.chosen_ratio()
        if ratio <= 0 or self.apply_as.currentData() != BARS:
            return 0.0
        size = (int(self.w.value()), int(self.h.value()))
        return ratio if timeline.aspect_size(*size, ratio) != size else 0.0

    def micro_fade(self) -> bool:
        return self.micro.isChecked()

    def magnetic(self) -> bool:
        return self.magnet.isChecked()

    def transparent(self) -> bool:
        return self.transp.isChecked()


__all__ = ["SequenceDialog", "RESOLUTIONS", "RATIOS", "fps_label"]
