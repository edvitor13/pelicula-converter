"""Painéis do modo Edição: a lista de mídia (à esquerda) e o inspetor do clipe (à direita)."""

from __future__ import annotations

import copy

from PySide6.QtCore import QMimeData, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import editparams
from ..i18n import N_, _, decimal_sep
from ..timeline import AUDIO, VIDEO, Clip, Source
from . import icons, theme
from .edit_model import TimelineModel
from .flow import flow_widget
from .store import ParamStore
from .timeline_view import MIME_SOURCE
from .widgets import SectionCard, Segmented, timecode

THUMB = QSize(72, 42)


def fmt_seconds(sec: float) -> str:
    """Duração curta: 0:42, 12:05, 1:02:03."""
    sec = max(0, int(round(sec)))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def source_kind(src: Source) -> str:
    if not src.is_file:
        return "gerado"  # clipe sem arquivo (título, cor, contagem…: `sequence.RENDERERS`)
    if src.is_image:
        return "imagem"
    if not src.has_video:
        return "audio"
    return "video"


KIND_LABELS = {"video": N_("vídeo"), "audio": N_("áudio"), "imagem": N_("imagem"), "gerado": N_("gerado")}


# ------------------------------------------------------------------ mídia
class _BinList(QListWidget):
    """Lista que arrasta os caminhos (para a linha do tempo) e aceita arquivos soltos."""

    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setIconSize(THUMB)
        self.setSpacing(2)
        self.setUniformItemSizes(True)
        self.setStyleSheet(f"QListWidget {{ background: transparent; border: none; }}"
                           f"QListWidget::item {{ padding: 4px; border-radius: 6px; color: {theme.TEXT}; }}"
                           f"QListWidget::item:selected {{ background: {theme.PANEL3}; color: {theme.ACCENT_HI}; }}"
                           f"QListWidget::item:hover {{ background: {theme.PANEL2}; }}")

    def mimeTypes(self):
        return [MIME_SOURCE, "text/uri-list"]

    def mimeData(self, items):
        md = QMimeData()
        paths = [it.data(Qt.ItemDataRole.UserRole) for it in items]
        md.setData(MIME_SOURCE, "\n".join(paths).encode("utf-8"))
        md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        return md

    def dragEnterEvent(self, e):
        if e.source() is self:
            super().dragEnterEvent(e)
        elif e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.source() is self:
            e.ignore()
        elif e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        if e.source() is self:
            e.ignore()
            return
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.filesDropped.emit(paths)


def _kind_pixmap(kind: str, thumb: QImage | None) -> QPixmap:
    pm = QPixmap(THUMB)
    pm.fill(QColor(theme.PANEL3))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if thumb is not None and not thumb.isNull():
        img = thumb.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
        x = (img.width() - THUMB.width()) // 2
        y = (img.height() - THUMB.height()) // 2
        p.drawImage(0, 0, img, x, y, THUMB.width(), THUMB.height())
    else:
        name = {"video": "film_mode", "audio": "music", "imagem": "image", "gerado": "wand"}[kind]
        color = theme.CLIP_AUDIO_HI if kind == "audio" else theme.ACCENT
        ic = icons.icon(name, color, 22).pixmap(QSize(22, 22))
        p.drawPixmap((THUMB.width() - 22) // 2, (THUMB.height() - 22) // 2, ic)
    p.end()
    return pm


class MediaBin(QWidget):
    """Arquivos importados para a edição. Arraste para a linha do tempo ou use "Adicionar"."""

    importRequested = Signal()
    addRequested = Signal(str)
    removeRequested = Signal(str)
    filesDropped = Signal(list)
    placeRequested = Signal(list, bool)   # (caminhos, inserir): no cursor, empurrando (True) ou cobrindo (False)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setMinimumWidth(220)
        self._sources: dict[str, Source] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 8, 8)
        lay.setSpacing(8)
        k = QLabel(_("MÍDIA"))
        k.setObjectName("Kicker")
        lay.addWidget(k)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_import = QPushButton("  " + _("Importar…"))
        self.btn_import.setObjectName("Primary")
        self.btn_import.setIcon(icons.icon("open", "#1b1205", 16))
        self.btn_import.setToolTip(_("Importar vídeos, imagens e músicas (Ctrl+I)"))
        self.btn_import.clicked.connect(self.importRequested)
        row.addWidget(self.btn_import, 1)
        self.btn_new = QToolButton()  # "Novo ▸": cor sólida, degradê, ponta, título (`set_new_menu`)
        self.btn_new.setObjectName("Flat")
        self.btn_new.setText(_("Novo"))
        self.btn_new.setIcon(icons.icon("wand", theme.TEXT, 16))
        self.btn_new.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_new.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_new.setToolTip(_("Criar um clipe sem arquivo: cor sólida, degradê, ponta com contagem ou título"))
        self.btn_new.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_new.setVisible(False)
        row.addWidget(self.btn_new)
        self.btn_add = self._flat("plus", _("Adicionar o item escolhido ao fim da linha do tempo"))
        self.btn_add.clicked.connect(self._add_current)
        row.addWidget(self.btn_add)
        self.btn_remove = self._flat("trash", _("Tirar da lista (os clipes já na linha do tempo ficam)"))
        self.btn_remove.clicked.connect(self._remove_current)
        row.addWidget(self.btn_remove)
        lay.addLayout(row)
        self.stack = QStackedWidget()
        self.empty = QLabel(_("Importe vídeos, imagens e músicas, ou arraste os arquivos para cá.\n\n"
                              "Depois arraste cada item para a linha do tempo (ou dê dois cliques nele)."))
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.empty.setAcceptDrops(False)
        self.list = _BinList()
        self.list.itemDoubleClicked.connect(lambda it: self.addRequested.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.list.itemSelectionChanged.connect(self._sync)
        self.list.filesDropped.connect(self.filesDropped)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.list)
        lay.addWidget(self.stack, 1)
        self.setAcceptDrops(True)
        self._sync()

    def _flat(self, icon: str, tip: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("Flat")
        b.setIcon(icons.icon(icon, theme.TEXT, 18))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    # -------------------------------------------------------- API
    def set_new_menu(self, menu: QMenu) -> None:
        """Liga o botão "Novo" ao menu dos clipes sem arquivo (`ui/generators_ui.new_menu`)."""
        self.btn_new.setMenu(menu)
        self.btn_new.setVisible(True)

    def add_source(self, src: Source, thumb: QImage | None = None) -> None:
        self._sources[src.path] = src
        item = self._item(src.path)
        if item is None:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, src.path)
            self.list.addItem(item)
        kind = source_kind(src)
        if kind == "gerado" and src.unbounded:
            item.setText(f"{src.name}\n{_(KIND_LABELS[kind])}")
        else:
            dur = _("imagem") if kind == "imagem" else fmt_seconds(src.length)
            item.setText(f"{src.name}\n{_(KIND_LABELS[kind])} • {dur}")
        item.setToolTip(src.path)
        item.setData(Qt.ItemDataRole.UserRole + 1, kind)
        item.setIcon(QIcon(_kind_pixmap(kind, thumb)))
        item.setSizeHint(QSize(0, THUMB.height() + 12))
        self._sync()

    def set_thumb(self, path: str, thumb: QImage) -> None:
        item = self._item(path)
        if item is not None:
            item.setIcon(QIcon(_kind_pixmap(item.data(Qt.ItemDataRole.UserRole + 1) or "video", thumb)))

    def remove(self, path: str) -> None:
        item = self._item(path)
        if item is not None:
            self.list.takeItem(self.list.row(item))
        self._sources.pop(path, None)
        self._sync()

    def clear(self) -> None:
        self.list.clear()
        self._sources.clear()
        self._sync()

    def paths(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def source(self, path: str) -> Source | None:
        return self._sources.get(path)

    def current_path(self) -> str | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def selected_paths(self) -> list[str]:
        """Itens escolhidos, na ordem da lista."""
        rows = sorted(self.list.row(it) for it in self.list.selectedItems())
        return [self.list.item(r).data(Qt.ItemDataRole.UserRole) for r in rows]

    def place(self, insert: bool) -> None:
        """"Inserir no cursor" (`,`) / "Sobrescrever no cursor" (`.`) com os itens escolhidos."""
        paths = self.selected_paths()
        if paths:
            self.placeRequested.emit(paths, bool(insert))

    def _menu(self, pos) -> None:
        if self.list.itemAt(pos) is None or not self.list.selectedItems():
            return
        menu = QMenu(self)
        menu.addAction(_("Adicionar ao fim da linha do tempo"), self._add_current)
        menu.addAction(_("Inserir no cursor (,)"), lambda: self.place(True))
        menu.addAction(_("Sobrescrever no cursor (.)"), lambda: self.place(False))
        menu.addSeparator()
        menu.addAction(_("Tirar da lista"), self._remove_current)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    # -------------------------------------------------------- interno
    def _item(self, path: str) -> QListWidgetItem | None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == path:
                return it
        return None

    def _sync(self) -> None:
        has = self.list.count() > 0
        self.stack.setCurrentWidget(self.list if has else self.empty)
        sel = bool(self.list.selectedItems())
        self.btn_add.setEnabled(sel)
        self.btn_remove.setEnabled(sel)

    def _add_current(self) -> None:
        for it in self.list.selectedItems():
            self.addRequested.emit(it.data(Qt.ItemDataRole.UserRole))

    def _remove_current(self) -> None:
        for it in list(self.list.selectedItems()):
            self.removeRequested.emit(it.data(Qt.ItemDataRole.UserRole))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and not e.mimeData().hasFormat(MIME_SOURCE):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.filesDropped.emit(paths)


# ------------------------------------------------------------------ inspetor
class _Chip(QToolButton):
    def __init__(self, text: str, tip: str = "", icon: str = "", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if icon:
            self.setIcon(icons.icon(icon, theme.ACCENT_HI, 14))
            self.setIconSize(QSize(14, 14))
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setStyleSheet(
            f"QToolButton {{ background: {theme.PANEL2}; border: 1px solid {theme.BORDER}; border-radius: 11px;"
            f" padding: 3px 9px; font-size: 8.5pt; }}"
            f"QToolButton:hover {{ border-color: {theme.ACCENT_DIM}; color: {theme.ACCENT_HI}; }}")


def _FlowRow(widgets: list[QWidget], per_row: int = 4) -> QWidget:
    """Botões lado a lado que quebram em quantas linhas a largura do painel pedir."""
    return flow_widget(widgets, 4, 4)


class ClipInspector(QWidget):
    """Ajustes do clipe selecionado (imagem ou som), gerados a partir de `editparams`."""

    autoRequested = Signal(str)

    OPEN_VIDEO = {"luz", "cor"}
    OPEN_AUDIO = {"som"}

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.setObjectName("Panel")
        self.setMinimumWidth(270)
        self.clip_id: str | None = None
        self.kind = VIDEO
        self._loading = False
        self.vstore = ParamStore(None, schema=editparams.VIDEO)
        self.astore = ParamStore(None, schema=editparams.AUDIO)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 6, 8)
        lay.setSpacing(8)
        k = QLabel(_("CLIPE"))
        k.setObjectName("Kicker")
        lay.addWidget(k)
        self.title = QLabel()
        self.title.setObjectName("PanelTitle")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.info = QLabel()
        self.info.setObjectName("Faint")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.kind_seg = Segmented([(VIDEO, _("Imagem"), _("Ajustes da imagem do clipe")),
                                   (AUDIO, _("Som"), _("Ajustes do som ligado ao clipe"))])
        self.kind_seg.changed.connect(self._kind_chosen)
        lay.addWidget(self.kind_seg)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.empty = QLabel(_("Selecione um clipe na linha do tempo para ajustar a cor, a luz, o enquadramento, "
                              "a velocidade, as transições e o som."))
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.stack.addWidget(self.empty)
        self.video_page, self.vcards = self._page(editparams.VIDEO_SECTIONS, self.vstore, self.OPEN_VIDEO, True)
        self.audio_page, self.acards = self._page(editparams.AUDIO_SECTIONS, self.astore, self.OPEN_AUDIO, False)
        self.stack.addWidget(self.video_page)
        self.stack.addWidget(self.audio_page)
        self.vstore.changed.connect(lambda key: self._store_changed(self.vstore, self.vcards, key))
        self.astore.changed.connect(lambda key: self._store_changed(self.astore, self.acards, key))
        model.selectionChanged.connect(self._selection_changed)
        model.changed.connect(self._model_changed)
        self._selection_changed()

    # -------------------------------------------------------- montagem
    def _page(self, sections, store: ParamStore, open_keys: set[str], video: bool):
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        if video:
            pl.addWidget(self._tools())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 8, 8)
        il.setSpacing(8)
        cards = []
        for sec in sections:
            card = SectionCard(sec, store, expanded=sec.key in open_keys)
            cards.append(card)
            il.addWidget(card)
        il.addStretch(1)
        scroll.setWidget(inner)
        pl.addWidget(scroll, 1)
        return page, cards

    def add_source_editor(self, widget: QWidget) -> None:
        """Painel no alto da página de imagem para os campos de um clipe sem arquivo (gerador, título); o próprio
        painel aparece ou some conforme o clipe escolhido (`ui/generators_ui.py`, `ui/titles_panel.py`)."""
        self.video_page.layout().insertWidget(0, widget)

    def _tools(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(6)
        lab = QLabel(_("Ajustes rápidos"))
        lab.setObjectName("Muted")
        vl.addWidget(lab)
        chips: list[QWidget] = []
        auto = _Chip(_("Automático"), _("Corrige a exposição, o contraste e o balanço de branco olhando o quadro "
                                        "atual"), "wand")
        auto.clicked.connect(self._auto)
        chips.append(auto)
        for key, label, values in editparams.QUICK_LOOKS:
            b = _Chip(_(label))
            b.clicked.connect(lambda _c=False, v=values: self._look(v))
            b.setObjectName(f"look_{key}")
            chips.append(b)
        reset = _Chip(_("Restaurar cor"), _("Zera a cor e a luz deste clipe"), "reset")
        reset.clicked.connect(self._reset_color)
        chips.append(reset)
        self.chip_auto = auto
        self.chip_reset = reset
        self.look_chips = chips
        vl.addWidget(_FlowRow(chips, 4))
        self.btn_copy = QPushButton(_("Copiar ajustes"))
        self.btn_copy.setIcon(icons.icon("copy", theme.TEXT, 14))
        self.btn_copy.setToolTip(_("Copia a cor e a luz deste clipe (Ctrl+Alt+C)"))
        self.btn_copy.clicked.connect(self.copy_values)
        self.btn_paste = QPushButton(_("Colar"))
        self.btn_paste.setIcon(icons.icon("paste", theme.TEXT, 14))
        self.btn_paste.setToolTip(_("Cola a cor e a luz nos clipes selecionados (Ctrl+Alt+V)"))
        self.btn_paste.clicked.connect(self.paste_values)
        self.btn_all = QPushButton(_("Aplicar a todos"))
        self.btn_all.setToolTip(_("Usa a cor e a luz deste clipe em todos os clipes de vídeo da sequência"))
        self.btn_all.clicked.connect(self.apply_all)
        for b in (self.btn_copy, self.btn_paste, self.btn_all):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        vl.addWidget(flow_widget([self.btn_copy, self.btn_paste, self.btn_all], 4, 4))
        return w

    # -------------------------------------------------------- seleção e valores
    def _current_group(self) -> tuple[Clip | None, Clip | None]:
        """(vídeo, áudio) do clipe principal selecionado e do seu par ligado."""
        c = self.model.primary()
        if c is None:
            return None, None
        group = self.model.seq.group(c)
        v = c if c.kind == VIDEO else next((g for g in group if g.kind == VIDEO), None)
        a = c if c.kind == AUDIO else next((g for g in group if g.kind == AUDIO), None)
        return v, a

    def current_clip(self) -> Clip | None:
        return self.model.seq.find(self.clip_id) if self.clip_id else None

    def _selection_changed(self) -> None:
        c = self.model.primary()
        if c is None:
            self.clip_id = None
            self._show()
            return
        v, a = self._current_group()
        kind = c.kind
        self.kind_seg.setVisible(v is not None and a is not None)
        self._set_kind(kind, v if kind == VIDEO else a)

    def _kind_chosen(self, kind: str) -> None:
        v, a = self._current_group()
        target = v if kind == VIDEO else a
        if target is not None:
            self._set_kind(kind, target)

    def _set_kind(self, kind: str, clip: Clip | None) -> None:
        self.kind = kind
        self.clip_id = clip.id if clip is not None else None
        self.kind_seg.set_current(kind)
        self._load()
        self._show()

    def _show(self) -> None:
        c = self.current_clip()
        if c is None:
            self.stack.setCurrentWidget(self.empty)
            self.title.setText(_("Nenhum clipe selecionado"))
            self.info.setText("")
            self.kind_seg.setVisible(False)
            return
        self.stack.setCurrentWidget(self.video_page if c.kind == VIDEO else self.audio_page)
        src = self.model.seq.sources.get(c.src)
        self.title.setText(c.name or (src.name if src else ""))
        kind = _("Imagem parada") if (src is not None and src.is_image) else (
            _("Vídeo") if c.kind == VIDEO else _("Som"))
        fps = self.model.seq.fps
        speed = "" if abs(c.speed - 1) < 1e-6 else "  •  " + f"{c.speed:g}".replace(".", decimal_sep()) + "×"
        n = len({(x.link or x.id) for x in self.model.selected_clips()})
        many = "" if n <= 1 else "  •  " + _("{n} selecionados").format(n=n)
        self.info.setText(_("{tipo} • {duracao} • começa em {inicio}").format(
            tipo=kind, duracao=timecode(c.dur, fps), inicio=timecode(c.start, fps)) + speed + many)
        if c.kind == VIDEO:
            self.btn_paste.setEnabled(self.model.has_clipboard())

    def _load(self) -> None:
        """Copia os valores do clipe para o store certo (sem gerar edições)."""
        c = self.current_clip()
        if c is None:
            return
        store = self.vstore if c.kind == VIDEO else self.astore
        if store.values == c.values:
            return
        self._loading = True
        try:
            store.set_all(copy.deepcopy(c.values), record=False)
        finally:
            self._loading = False

    def _store_changed(self, store: ParamStore, cards: list[SectionCard], key: str) -> None:
        for card in cards:
            if key == "*" or key in card.keys():
                card.refresh(key)
        if self._loading or self.clip_id is None:
            return
        c = self.current_clip()
        if c is None or (store is self.vstore) != (c.kind == VIDEO):
            return
        self.model.set_clip_values(c.id, copy.deepcopy(store.values), record=False)

    def _model_changed(self, _kind: str) -> None:
        if self.clip_id is not None and self.current_clip() is None:
            self._selection_changed()
            return
        self._load()
        self._show()

    # -------------------------------------------------------- ações
    def _auto(self) -> None:
        c = self.current_clip()
        if c is not None and c.kind == VIDEO:
            self.autoRequested.emit(c.id)

    def _look(self, values: dict) -> None:
        c = self.current_clip()
        if c is not None and c.kind == VIDEO:
            self.model.apply_look(c.id, values)

    def _reset_color(self) -> None:
        c = self.current_clip()
        if c is not None and c.kind == VIDEO:
            self.model.reset_color(c.id)

    def copy_values(self) -> None:
        c = self.current_clip()
        if c is not None and self.model.copy_values(c.id):
            self.btn_paste.setEnabled(True)

    def paste_values(self) -> None:
        ids = list(self.model.selection) or ([self.clip_id] if self.clip_id else [])
        self.model.paste_values(ids)

    def apply_all(self) -> None:
        c = self.current_clip()
        if c is not None:
            self.model.apply_values_to_all(c.id)

    def sizeHint(self) -> QSize:
        return QSize(380, 600)


__all__ = ["MediaBin", "ClipInspector", "fmt_seconds", "source_kind"]
