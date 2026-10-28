"""Painel "Legendas" (modos Película e Edição): a lista, a edição de uma legenda, o estilo e o texto falado.

Aba **Lista**: início, fim e texto de cada legenda (no tempo da sequência; no modo Película, o do arquivo).
Clicar leva o cursor até ela; embaixo ficam o início, o fim, o texto, itálico e negrito da escolhida e, quando
ela veio da transcrição, o tempo de cada palavra. Buscar filtra a lista; "Substituir todas" troca em todas.
Os botões de cima criam uma legenda no cursor, dividem, juntam com a próxima, apagam, importam e exportam
.srt/.vtt e (módulo Beta `legendas_auto`) geram as legendas pela fala.

Toda mudança passa pelo `SubtitleController` (um passo de desfazer cada); os botões de desfazer daqui valem
nos dois modos (no modo Película o Ctrl+Z da janela é do look, menos com o foco neste painel).

Atalhos com o foco no painel: Ctrl+F busca, Ctrl+Enter aplica o texto, Delete apaga a legenda escolhida
(na lista) e Ctrl+Shift+Enter cria uma legenda no cursor.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QItemSelectionModel, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .. import subedit, subtitles as sb, textrender as tr
from ..i18n import N_, _, decimal_sep, fmt_decimal, fmt_int
from . import icons, theme
from .flow import FlowLayout
from .subtitle_style import StyleEditor, missing_text
from .subtitles_ui import SubtitleController

# Gravar no vídeo (chave de `subtitles.BURN_MODES`, rótulo)
BURN_LABELS = (("nao", N_("Não gravar no vídeo")), ("copia", N_("Gravada na cópia (antes do look)")),
               ("digital", N_("Digital (depois do look)")))


class _TextEdit(QPlainTextEdit):
    """Texto da legenda: aplica ao sair do campo ou com Ctrl+Enter."""
    committed = Signal()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.committed.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.committed.emit()
            return
        super().keyPressEvent(e)


def fmt_time(t: float) -> str:
    """00:01:02,500 (com o separador decimal do idioma)."""
    return sb.fmt_time(t, decimal_sep())


class SubtitlesPanel(QWidget):
    importRequested = Signal()
    exportRequested = Signal()
    generateRequested = Signal()
    previewToggled = Signal(bool)

    def __init__(self, ctl: SubtitleController, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setObjectName("Panel")
        self.setMinimumWidth(320)
        self._filling = False
        self._shown_ref: subedit.Ref | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 10, 8)
        lay.setSpacing(8)

        head = QHBoxLayout()
        k = QLabel(_("LEGENDAS"))
        k.setObjectName("Kicker")
        head.addWidget(k)
        self.count = QLabel("")
        self.count.setObjectName("Faint")
        head.addWidget(self.count, 1)
        self.btn_undo = self._btn("undo", _("Desfazer na edição das legendas"))
        self.btn_undo.clicked.connect(lambda: ctl.model.undo())
        self.btn_redo = self._btn("redo", _("Refazer na edição das legendas"))
        self.btn_redo.clicked.connect(lambda: ctl.model.redo())
        head.addWidget(self.btn_undo)
        head.addWidget(self.btn_redo)
        lay.addLayout(head)

        bar = QWidget()
        fl = FlowLayout(bar, 2, 2)
        fl.setContentsMargins(0, 0, 0, 0)
        self.btn_add = self._btn("plus", _("Nova legenda no cursor (Ctrl+Shift+Enter)"), _("Nova"))
        self.btn_add.clicked.connect(lambda: ctl.add_at() and self.focus_text())
        self.btn_split = self._btn("split", _("Dividir a legenda no cursor"))
        self.btn_split.clicked.connect(lambda: ctl.split())
        self.btn_merge = self._btn("link", _("Juntar com a próxima"))
        self.btn_merge.clicked.connect(lambda: ctl.merge_next())
        self.btn_delete = self._btn("trash", _("Apagar a legenda escolhida (Delete)"))
        self.btn_delete.clicked.connect(lambda: ctl.delete_selected())
        self.btn_import = self._btn("open", _("Importar legendas (.srt, .vtt)"), _("Importar"))
        self.btn_import.clicked.connect(self.importRequested)
        self.btn_export = self._btn("export", _("Exportar legendas (.srt, .vtt)"), _("Exportar"))
        self.btn_export.clicked.connect(self.exportRequested)
        self.btn_generate = self._btn("wand", _("Gerar legendas pela fala (neste computador)"), _("Gerar…"))
        self.btn_generate.clicked.connect(self.generateRequested)
        self.btn_generate.setVisible(False)
        for b in (self.btn_add, self.btn_split, self.btn_merge, self.btn_delete):
            fl.addWidget(b)
        fl.add_spacing(8)
        for b in (self.btn_import, self.btn_export, self.btn_generate):
            fl.addWidget(b)
        lay.addWidget(bar)

        row = QHBoxLayout()
        self.burn = QComboBox()
        for key, label in BURN_LABELS:
            self.burn.addItem(_(label), key)
        self.burn.setToolTip(_("Como as legendas saem na exportação quando elas vão no vídeo: gravadas na cópia "
                               "(antes do look: grão, halação e tremor passam por elas, como numa cópia de cinema "
                               "legendada) ou digitais (depois do look, nítidas). A janela Exportar também tem a "
                               "faixa de legenda e o arquivo .srt ao lado."))
        self.burn.currentIndexChanged.connect(self._burn_chosen)
        row.addWidget(self.burn, 1)
        self.chk_preview = QCheckBox(_("Ver na prévia"))
        self.chk_preview.setToolTip(_("Mostra as legendas na prévia mesmo sem gravar no vídeo (como num player)."))
        self.chk_preview.setChecked(True)
        self.chk_preview.toggled.connect(self.previewToggled)
        row.addWidget(self.chk_preview)
        lay.addLayout(row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._list_tab(), _("Lista"))
        self.style_tab = StyleEditor(ctl)
        self.tabs.addTab(self.style_tab, _("Estilo"))
        lay.addWidget(self.tabs, 1)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color: {theme.DANGER};")
        self.warn.setVisible(False)
        lay.addWidget(self.warn)

        sc = QShortcut(QKeySequence("Ctrl+F"), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self.focus_search)
        sc = QShortcut(QKeySequence("Ctrl+Shift+Return"), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(lambda: ctl.add_at() and self.focus_text())
        sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table)
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc.activated.connect(lambda: ctl.delete_selected())

        ctl.changed.connect(self.refresh)
        ctl.selectionChanged.connect(self._sync_selection)
        ctl.model.historyChanged.connect(self._sync_history)
        ctl.textRequested.connect(self.focus_text)
        self.refresh()
        self._sync_history()

    # ------------------------------------------------------------ partes
    def _btn(self, icon: str, tip: str, text: str = "") -> QToolButton:
        b = QToolButton()
        b.setObjectName("Flat")
        b.setIcon(icons.icon(icon, theme.TEXT, 16))
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if text:
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        return b

    def _list_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(6)
        srow = QHBoxLayout()
        self.find = QLineEdit()
        self.find.setPlaceholderText(_("Buscar"))
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self._filter)
        self.repl = QLineEdit()
        self.repl.setPlaceholderText(_("Substituir por"))
        self.btn_repl = QPushButton(_("Substituir todas"))
        self.btn_repl.clicked.connect(self._replace_all)
        srow.addWidget(self.find, 1)
        srow.addWidget(self.repl, 1)
        srow.addWidget(self.btn_repl)
        v.addLayout(srow)
        self.find_info = QLabel("")
        self.find_info.setObjectName("Faint")
        self.find_info.setVisible(False)
        v.addWidget(self.find_info)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([_("Início"), _("Fim"), _("Texto")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._rows_chosen)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.focus_text())
        v.addWidget(self.table, 1)

        self.editor = QWidget()
        form = QFormLayout(self.editor)
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        trow = QHBoxLayout()
        self.start = self._time_box()
        self.end = self._time_box()
        self.start.editingFinished.connect(lambda: self._times_edited(start=True))
        self.end.editingFinished.connect(lambda: self._times_edited(start=False))
        trow.addWidget(self.start)
        dash = QLabel("–")
        dash.setObjectName("Muted")
        trow.addWidget(dash)
        trow.addWidget(self.end)
        trow.addStretch(1)
        self.btn_italic = self._flag("I", _("Itálico"))
        self.btn_italic.toggled.connect(lambda on: self._flags(italic=on))
        self.btn_bold = self._flag("B", _("Negrito"))
        self.btn_bold.toggled.connect(lambda on: self._flags(bold=on))
        trow.addWidget(self.btn_italic)
        trow.addWidget(self.btn_bold)
        form.addRow(_("Tempo"), trow)
        self.text = _TextEdit()
        self.text.setPlaceholderText(_("Texto da legenda (Ctrl+Enter aplica)"))
        self.text.setFixedHeight(64)
        self.text.committed.connect(self._text_edited)
        form.addRow(_("Texto"), self.text)
        self.where = QLabel("")
        self.where.setObjectName("Faint")
        self.where.setWordWrap(True)
        form.addRow("", self.where)
        self.words = QLabel("")
        self.words.setObjectName("Muted")
        self.words.setWordWrap(True)
        self.words.setTextFormat(Qt.TextFormat.RichText)
        self.words.setToolTip(_("Tempo de cada palavra (da transcrição): é o que o destaque palavra por palavra usa."))
        form.addRow(_("Palavras"), self.words)
        self.form = form
        v.addWidget(self.editor)
        return w

    def _time_box(self) -> QDoubleSpinBox:
        b = QDoubleSpinBox()
        b.setDecimals(3)
        b.setRange(0.0, sb.MAX_TIME)
        b.setSingleStep(0.1)
        b.setSuffix(" s")
        b.setKeyboardTracking(False)
        return b

    def _flag(self, text: str, tip: str) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setCheckable(True)
        b.setToolTip(tip)
        b.setFixedWidth(28)
        f = b.font()
        f.setItalic(text == "I")
        f.setBold(text == "B")
        b.setFont(f)
        return b

    # ------------------------------------------------------------ mostrar
    def refresh(self) -> None:
        """Refaz a lista (as legendas ou a montagem mudaram)."""
        self._filling = True
        try:
            items = self.ctl.items()
            self.table.setRowCount(len(items))
            for r, it in enumerate(items):
                cells = (fmt_time(it.cue.start), fmt_time(it.cue.end), it.cue.text.replace("\n", " / "))
                for c, text in enumerate(cells):
                    cell = QTableWidgetItem(text)
                    if it.fixed and c < 2:
                        cell.setToolTip(_("Tempo fixo na sequência (não acompanha os cortes)"))
                    self.table.setItem(r, c, cell)
            self.count.setText(_("{n} legendas").format(n=fmt_int(len(items))) if items else _("nenhuma"))
            gone = missing_text(self.ctl.model.seq.subtitles, [it.cue for it in items])
            self.warn.setVisible(bool(gone))
            if gone:
                fam = tr.family(self.ctl.doc().style.text.family).name
                self.warn.setText(_("A fonte {fonte} não tem estes caracteres (aparecem como um retângulo no vídeo): "
                                    "{caracteres}. Escolha outra fonte na aba Estilo.").format(
                    fonte=fam, caracteres=" ".join(gone[:40])))
            doc = self.ctl.doc()
            i = self.burn.findData(doc.burn)
            self.burn.setCurrentIndex(max(0, i))
        finally:
            self._filling = False
        self._filter()
        self._sync_selection()

    def _sync_history(self) -> None:
        self.btn_undo.setEnabled(self.ctl.model.can_undo())
        self.btn_redo.setEnabled(self.ctl.model.can_redo())

    def _sync_selection(self) -> None:
        refs = set(self.ctl.selection)
        items = self.ctl.items()
        self._filling = True
        try:
            sel = self.table.selectionModel()
            self.table.clearSelection()
            first = None
            flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
            for r, it in enumerate(items):
                if it.ref in refs:
                    sel.select(self.table.model().index(r, 0), flags)
                    first = r if first is None else first
            if first is not None:
                sel.setCurrentIndex(self.table.model().index(first, 0), QItemSelectionModel.SelectionFlag.NoUpdate)
                self.table.scrollToItem(self.table.item(first, 0))
        finally:
            self._filling = False
        self._load_editor()

    def _load_editor(self) -> None:
        it = self.ctl.current()
        cue = self.ctl.source_cue(it)
        on = it is not None and cue is not None
        for w in (self.start, self.end, self.text, self.btn_italic, self.btn_bold):
            w.setEnabled(on)
        self.btn_split.setEnabled(bool(self.ctl.items()))
        self.btn_delete.setEnabled(bool(self.ctl.selection))
        nxt = subedit.neighbor(self.ctl.items(), it, 1) if it is not None else None
        self.btn_merge.setEnabled(nxt is not None and nxt.ref.path == it.ref.path)
        self._filling = True
        try:
            self._shown_ref = it.ref if on else None
            self.start.setValue(it.cue.start if on else 0.0)
            self.end.setValue(it.cue.end if on else 0.0)
            if not self.text.hasFocus() or not on:
                self.text.setPlainText(cue.text if on else "")
            self.btn_italic.setChecked(bool(on and cue.italic))
            self.btn_bold.setChecked(bool(on and cue.bold))
            if not on:
                self.where.setText("")
            elif it.fixed:
                self.where.setText(_("Tempo fixo na sequência: não acompanha os cortes."))
            else:
                self.where.setText(_("Presa a {arquivo}: acompanha os cortes.").format(
                    arquivo=os.path.basename(it.ref.path)))
            words = it.cue.words if on else ()
            self.words.setText(" ".join(f"<span style='color:{theme.FAINT}'>{fmt_decimal(w.start, 2)}</span> "
                                        f"{_escape(w.text)}" for w in words) if words else "")
            self.form.setRowVisible(self.words, bool(words))
        finally:
            self._filling = False

    def _filter(self) -> None:
        q = self.find.text()
        items = self.ctl.items()
        shown = {id(it) for it in subedit.matches(items, q)}
        for r, it in enumerate(items):
            self.table.setRowHidden(r, id(it) not in shown)
        self.find_info.setVisible(bool(q))
        if q:
            self.find_info.setText(_("{n} encontradas").format(n=fmt_int(len(shown))))

    # ------------------------------------------------------------ ações
    def focus_search(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.find.setFocus()
        self.find.selectAll()

    def focus_text(self) -> None:
        self.tabs.setCurrentIndex(0)
        if self.text.isEnabled():
            self.text.setFocus()
            self.text.selectAll()

    def _rows_chosen(self) -> None:
        if self._filling:
            return
        items = self.ctl.items()
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        refs = [items[r].ref for r in rows if 0 <= r < len(items)]
        self.ctl.select(refs, seek=len(refs) == 1)

    def _current(self) -> subedit.Item | None:
        it = self.ctl.current()
        return it if it is not None and it.ref == self._shown_ref else None

    def _times_edited(self, start: bool) -> None:
        if self._filling:
            return
        it = self._current()
        if it is None:
            return
        box = self.start if start else self.end
        v = box.value()
        old = it.cue.start if start else it.cue.end
        if abs(v - old) < 5e-4:
            return
        self.ctl.set_times(it, start=v) if start else self.ctl.set_times(it, end=v)

    def _text_edited(self) -> None:
        if self._filling:
            return
        it = self._current()
        cue = self.ctl.source_cue(it)
        if it is None or cue is None:
            return
        text = self.text.toPlainText()
        if sb.clean_text(text) == cue.text:
            return
        self.ctl.set_text(it, text)

    def _flags(self, italic: bool | None = None, bold: bool | None = None) -> None:
        if self._filling:
            return
        it = self._current()
        if it is not None:
            self.ctl.set_flags(it, italic=italic, bold=bold)

    def _burn_chosen(self) -> None:
        if self._filling:
            return
        mode = self.burn.currentData()
        if mode in sb.BURN_MODES and mode != self.ctl.doc().burn:
            self.ctl.set_options(burn=mode)

    def _replace_all(self) -> None:
        q = self.find.text()
        if not q:
            self.focus_search()
            return
        n = self.ctl.replace_all(q, self.repl.text())
        self.find_info.setVisible(True)
        self.find_info.setText(_("{n} trocas").format(n=fmt_int(n)) if n else _("Nada para trocar."))


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
