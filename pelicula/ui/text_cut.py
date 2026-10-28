""""Cortar pelo texto" (aba do painel de legendas, módulo Beta `legendas_auto`): a transcrição como texto.

As palavras na tela (`subedit.words`, com o tempo de cada uma, que só a transcrição tem) viram um texto corrido.
Selecione um trecho e "Marcar" (de novo desmarca); clicar numa palavra leva o cursor até ela. "Cortar os
marcados" tira tudo de uma vez (`rangecut.text_ranges` → `TimelineModel.remove_ranges`), num passo de desfazer:
o que vem depois encosta em todas as faixas destravadas. Qualquer mudança na montagem ou nas legendas limpa as
marcas (as palavras mudam de lugar).
"""

from __future__ import annotations

import html

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from .. import rangecut, silences, subedit
from ..i18n import _, fmt_int
from ..platforms import fmt_seconds
from . import icons, theme


class TextCut(QWidget):
    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.words: list = []
        self.marked: set[int] = set()
        self._dirty = True
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)
        self.hint = QLabel(_("Selecione palavras no texto e marque o que sai; depois corte tudo de uma vez. Clicar "
                             "numa palavra leva o cursor até ela."))
        self.hint.setWordWrap(True)
        self.hint.setObjectName("Muted")
        lay.addWidget(self.hint)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setAcceptRichText(False)
        self.text.cursorPositionChanged.connect(self._clicked)
        self.text.selectionChanged.connect(self._sync)
        lay.addWidget(self.text, 1)
        self.empty = QLabel(_("O texto aparece aqui depois de \"Gerar legendas pela fala…\": as legendas escritas "
                              "ou importadas não têm o tempo de cada palavra."))
        self.empty.setWordWrap(True)
        self.empty.setObjectName("Faint")
        lay.addWidget(self.empty)
        row = QHBoxLayout()
        self.btn_mark = QPushButton(_("Marcar"))
        self.btn_mark.setToolTip(_("Marca (ou desmarca) as palavras selecionadas para cortar"))
        self.btn_mark.clicked.connect(self.toggle_selection)
        self.btn_clear = QPushButton(_("Limpar"))
        self.btn_clear.clicked.connect(self.clear)
        row.addWidget(self.btn_mark)
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        self.btn_cut = QPushButton(_("Cortar os marcados"))
        self.btn_cut.setObjectName("Primary")
        self.btn_cut.setIcon(icons.icon("scissors", "#1b1205", 15))
        self.btn_cut.clicked.connect(self.cut)
        row.addWidget(self.btn_cut)
        lay.addLayout(row)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        lay.addWidget(self.summary)
        ctl.changed.connect(self.refresh)

    # ------------------------------------------------------------ texto
    def refresh(self) -> None:
        """Relê as palavras (e limpa as marcas). Escondida, só na próxima vez que aparecer."""
        if not self.isVisible():
            self._dirty = True
            return
        self._dirty = False
        self.words = subedit.words(self.ctl.items())
        self.marked.clear()
        self._render()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._dirty:
            self.refresh()

    def _render(self) -> None:
        parts = []
        for i, w in enumerate(self.words):
            t = html.escape(w.text)
            if i in self.marked:
                t = f"<span style='color:{theme.ACCENT_HI}; text-decoration: line-through'>{t}</span>"
            parts.append(t)
        self.text.blockSignals(True)
        self.text.setHtml(" ".join(parts))   # o texto puro é `silences.transcript(words)`: as posições batem
        self.text.blockSignals(False)
        has = bool(self.words)
        self.text.setVisible(has)
        self.empty.setVisible(not has)
        self._sync()

    def selected(self) -> list[int]:
        cur = self.text.textCursor()
        if not cur.hasSelection():
            return []
        return silences.indices_for_text(self.words, [(cur.selectionStart(), cur.selectionEnd())])

    def select_text(self, a: int, b: int) -> None:
        """Seleciona o trecho [a, b) do texto (como o mouse faria)."""
        cur = self.text.textCursor()
        cur.setPosition(a)
        cur.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
        self.text.setTextCursor(cur)

    def _word_at(self, pos: int) -> int | None:
        for i, (a, b) in enumerate(silences.word_spans(self.words)):
            if a <= pos <= b:
                return i
        return None

    def _clicked(self) -> None:
        if self.text.textCursor().hasSelection():
            return
        i = self._word_at(self.text.textCursor().position())
        if i is not None:
            self.ctl.seekRequested.emit(self.ctl.frame_of(self.words[i].start))

    # ------------------------------------------------------------ marcas e corte
    def toggle_selection(self) -> None:
        sel = set(self.selected())
        if not sel:
            return
        if sel <= self.marked:
            self.marked -= sel
        else:
            self.marked |= sel
        self._render()

    def clear(self) -> None:
        self.marked.clear()
        self._render()

    def ranges(self) -> list[tuple[float, float]]:
        return rangecut.text_ranges(self.words, sorted(self.marked))

    def _sync(self) -> None:
        self.btn_mark.setEnabled(bool(self.selected()))
        self.btn_clear.setEnabled(bool(self.marked))
        cuts = self.ranges()
        self.btn_cut.setEnabled(bool(cuts))
        n, tempo = len(self.marked), fmt_seconds(rangecut.total(cuts))
        text = (_("1 palavra marcada • {tempo} a tirar").format(tempo=tempo) if n == 1 else
                _("{n} palavras marcadas • {tempo} a tirar").format(n=fmt_int(n), tempo=tempo))
        self.summary.setText(text if n else "")

    def cut(self) -> int:
        """Tira os trechos das palavras marcadas (um passo de desfazer). Devolve os quadros tirados."""
        model = self.ctl.model
        frames = rangecut.to_frames(model.seq, self.ranges())
        return model.remove_ranges(frames) if frames else 0
