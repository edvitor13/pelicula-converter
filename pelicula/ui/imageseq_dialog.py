"""Importar imagens numeradas (plano_0001.png, plano_0002.png…) como uma sequência: um clipe só, um quadro por
arquivo, na velocidade escolhida (padrão: a da montagem). A detecção fica em `media.find_sequence`."""

from __future__ import annotations

from fractions import Fraction

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPushButton,
                               QVBoxLayout)

from .. import media
from ..i18n import _, fmt_decimal
from . import theme
from .widgets import compact

# Velocidades da lista (a da montagem entra se não estiver aqui).
RATES = ("24000/1001", "24/1", "25/1", "30000/1001", "30/1", "48/1", "50/1", "60000/1001", "60/1")
SEQUENCE = "sequencia"
IMAGE = "imagem"


def rate_label(fps_str: str) -> str:
    try:
        v = float(Fraction(fps_str))
    except (ValueError, ZeroDivisionError):
        return fps_str
    return _("{fps} quadros/s").format(fps=fmt_decimal(v, 3).rstrip("0").rstrip(",.") if v % 1 else str(int(v)))


def gaps_text(found: media.ImageSequence, most: int = 4) -> str:
    """Os buracos da numeração em texto curto (12–14, 30…)."""
    parts = [str(a) if a == b else f"{a}–{b}" for a, b in found.gaps[:most]]
    if len(found.gaps) > most:
        parts.append("…")
    return ", ".join(parts)


class ImageSequenceDialog(QDialog):
    """Pergunta se as imagens numeradas entram como sequência (e em que velocidade) ou como imagem parada."""

    def __init__(self, parent, found: media.ImageSequence, fps_default: str = "24/1", single: bool = True):
        super().__init__(parent)
        self.found = found
        self.choice: str | None = None
        self.setWindowTitle(_("Sequência de imagens"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        head = QLabel(_("Estas imagens são numeradas: quer usá-las como os quadros de um vídeo?"))
        head.setWordWrap(True)
        lay.addWidget(head)
        form = QFormLayout()
        form.addRow(_("Arquivos"), QLabel(found.label))
        form.addRow(_("Quadros"), QLabel(_("{n} (do {a} ao {b})").format(n=found.count, a=found.first,
                                                                        b=found.last)))
        self.fps = compact(QComboBox())
        rates = list(RATES)
        if fps_default not in rates:
            rates.insert(0, fps_default)
        for r in rates:
            self.fps.addItem(rate_label(r), r)
        self.fps.setCurrentIndex(max(0, self.fps.findData(fps_default)))
        self.fps.setToolTip(_("Cada imagem é um quadro: a velocidade diz quantos quadros passam por segundo."))
        form.addRow(_("Velocidade"), self.fps)
        lay.addLayout(form)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color: {theme.DANGER};")
        if found.gaps:
            self.warn.setText("⚠ " + _("A numeração tem buracos (faltam {lista}). Entram só os {n} quadros seguidos, "
                                       "do {a} ao {b}; para usar os outros, importe a partir de um arquivo depois do "
                                       "buraco.").format(lista=gaps_text(found), n=found.count, a=found.first,
                                                         b=found.last))
        self.warn.setVisible(bool(found.gaps))
        lay.addWidget(self.warn)
        btns = QDialogButtonBox()
        self.btn_seq = QPushButton(_("Importar como sequência"))
        self.btn_seq.setObjectName("Primary")
        self.btn_seq.setDefault(True)
        btns.addButton(self.btn_seq, QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_image = QPushButton(_("Só esta imagem") if single else _("Imagens separadas"))
        btns.addButton(self.btn_image, QDialogButtonBox.ButtonRole.ActionRole)
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.btn_seq.clicked.connect(lambda: self._pick(SEQUENCE))
        self.btn_image.clicked.connect(lambda: self._pick(IMAGE))
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _pick(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def fps_str(self) -> str:
        return str(self.fps.currentData() or "24/1")


def ask(parent, found: media.ImageSequence, fps_default: str = "24/1", single: bool = True) -> tuple[str, str] | None:
    """(SEQUENCE ou IMAGE, velocidade) ou None (cancelou). Os testes trocam esta função para não abrir a janela."""
    dlg = ImageSequenceDialog(parent, found, fps_default, single)
    if not dlg.exec() or dlg.choice is None:
        return None
    return dlg.choice, dlg.fps_str()
