"""Marcadores e capítulos na interface: editar um marcador e copiar os capítulos para o YouTube."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout, QWidget)

from .. import chapters, timeline
from ..i18n import _
from . import theme
from .widgets import timecode


def marker_color(key: str) -> QColor:
    return QColor(theme.MARKER_COLORS.get(key, theme.MARKER_COLORS[timeline.MARKER_COLOR_KEYS[0]]))


def marker_tooltip(mk: timeline.Marker, fps: float) -> str:
    """Texto do marcador ao passar o mouse: tempo, nome, capítulo e nota."""
    head = timecode(mk.frame, fps)
    if mk.name:
        head += "  •  " + mk.name
    if mk.chapter:
        head += "  •  " + _("capítulo")
    lines = [head]
    if mk.note:
        lines.append(mk.note)
    lines.append(_("Dois cliques: editar • arraste para mover • Delete apaga"))
    return "\n".join(lines)


class MarkerDialog(QDialog):
    """Nome, cor, nota e "Capítulo" de um marcador. `removed` fica True se a pessoa pediu para apagar."""

    def __init__(self, parent, mk: timeline.Marker, fps: float):
        super().__init__(parent)
        self.setWindowTitle(_("Marcador em {tempo}").format(tempo=timecode(mk.frame, fps)))
        self.setMinimumWidth(420)
        self.removed = False
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(8)
        self.name = QLineEdit(mk.name)
        self.name.setMaxLength(timeline.MARKER_TEXT_MAX)
        self.name.setPlaceholderText(_("Por exemplo: Abertura"))
        form.addRow(_("Nome"), self.name)
        colors = QWidget()
        cl = QHBoxLayout(colors)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        self.color_group = QButtonGroup(self)
        self.color_group.setExclusive(True)
        self.color_buttons: dict[str, QToolButton] = {}
        for key, label in timeline.MARKER_COLORS:
            b = QToolButton()
            b.setCheckable(True)
            b.setToolTip(_(label))
            b.setFixedSize(QSize(24, 24))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            hexc = theme.MARKER_COLORS[key]
            b.setStyleSheet(f"QToolButton {{ background: {hexc}; border: 2px solid {theme.PANEL}; border-radius: 12px; }}"
                            f"QToolButton:checked {{ border: 2px solid {theme.TEXT}; }}")
            b.setChecked(key == mk.color)
            self.color_group.addButton(b)
            self.color_buttons[key] = b
            cl.addWidget(b)
        cl.addStretch(1)
        form.addRow(_("Cor"), colors)
        self.note = QPlainTextEdit(mk.note)
        self.note.setPlaceholderText(_("Lembrete para você (não vai para o vídeo)"))
        self.note.setFixedHeight(72)
        form.addRow(_("Nota"), self.note)
        self.chapter = QCheckBox(_("Capítulo (YouTube e arquivo exportado)"))
        self.chapter.setChecked(mk.chapter)
        self.chapter.setToolTip(_("Marcadores com esta opção viram os capítulos do vídeo: o texto para a descrição "
                                  "do YouTube e os capítulos gravados em MP4, MOV e MKV."))
        form.addRow("", self.chapter)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(_("Aplicar"))
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        self.btn_remove = btns.addButton(_("Remover marcador"), QDialogButtonBox.ButtonRole.DestructiveRole)
        self.btn_remove.clicked.connect(self._remove)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self.name.setFocus()

    def _remove(self) -> None:
        self.removed = True
        self.accept()

    def color(self) -> str:
        return next((k for k, b in self.color_buttons.items() if b.isChecked()), timeline.MARKER_COLOR_KEYS[0])

    def values(self) -> dict:
        return {"name": self.name.text().strip(), "note": self.note.toPlainText().strip(), "color": self.color(),
                "chapter": self.chapter.isChecked()}


def youtube_chapters(seq: timeline.Sequence, start: int = 0, end: int | None = None) -> tuple[str, list[str]]:
    """(texto para a descrição do YouTube, problemas) dos capítulos no trecho [start, end) da sequência."""
    end = seq.duration if end is None else end
    fps = seq.fps
    total = max(0, end - start) / fps
    chs = chapters.relative(chapters.points(seq), start, end, fps)
    return chapters.youtube_text(chs, total), chapters.youtube_problems(chs, total)


class ChaptersDialog(QDialog):
    """Mostra o texto dos capítulos, o que falta para o YouTube aceitar e copia para a área de transferência."""

    def __init__(self, parent, text: str, problems: list[str], note: str = ""):
        super().__init__(parent)
        self.setWindowTitle(_("Capítulos para o YouTube"))
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        intro = QLabel(_("Cole na descrição do vídeo no YouTube. Os capítulos saem dos marcadores marcados como "
                         "capítulo.") + (("\n" + note) if note else ""))
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.text = QPlainTextEdit(text)
        self.text.setReadOnly(True)
        self.text.setFont(theme.mono_font(10))
        self.text.setMinimumHeight(140)
        lay.addWidget(self.text, 1)
        if problems:
            msg = _("O YouTube ainda não vai mostrar estes capítulos:") + "\n• " + "\n• ".join(problems)
            color = theme.ACCENT_HI
        else:
            msg = _("Tudo certo: o YouTube aceita estes capítulos.")
            color = theme.OK
        self.status = QLabel(msg)
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {color};")
        lay.addWidget(self.status)
        self.problems = list(problems)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_copy = QPushButton(_("Copiar"))
        self.btn_copy.setObjectName("Primary")
        self.btn_copy.setEnabled(bool(text))
        self.btn_copy.clicked.connect(self.copy)
        close = QPushButton(_("Fechar"))
        close.clicked.connect(self.reject)
        row.addWidget(close)
        row.addWidget(self.btn_copy)
        lay.addLayout(row)

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text.toPlainText())
        self.btn_copy.setText(_("Copiado"))


__all__ = ["MarkerDialog", "ChaptersDialog", "marker_color", "marker_tooltip", "youtube_chapters"]
