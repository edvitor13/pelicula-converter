"""Pastas no painel de mídia do modo Edição (ARQUITETURA §39): a árvore (`FolderTree`) e as ações (`FolderActions`).

O modelo é `pastas.Folders` (em `Sequence.folders`); toda mudança passa por `TimelineModel.folder_*` e vira um
passo do desfazer (`changed("pastas")`). Aqui só se desenha e se ouve o usuário: nada muda a imagem, o som nem os
arquivos do disco. `edit_panels.MediaBin` só liga este módulo (a árvore no lugar da lista e os botões).
"""

from __future__ import annotations

import os

from PySide6.QtCore import QItemSelectionModel, QMimeData, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QActionGroup, QBrush, QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QMenu, QMessageBox, QToolButton, QTreeWidget,
                               QTreeWidgetItem)

from .. import media, pastas
from ..i18n import N_, _
from ..pastas import Folders
from ..timeline import MARKER_COLORS
from . import theme
from .timeline_view import MIME_SOURCE

MIME_FOLDERS = "application/x-pelicula-pastas"   # ids das pastas arrastadas (só dentro do painel)
FOLDER_ICON = 28
FOLDER_ROW = 36
SORTS = [("ordem", N_("Ordem de importação")), ("nome", N_("Nome")), ("tipo", N_("Tipo")), ("data", N_("Data"))]
KIND_ORDER = {"video": 0, "imagem": 1, "audio": 2, "gerado": 3, "sequencia": 4}
DEFAULT_COLOR = "#a39684"   # pasta sem cor escolhida


def color_hex(color: str) -> str:
    """O tom na tela de uma cor de pasta: id da paleta (os tons dos marcadores), `#rrggbb` ou o padrão."""
    return theme.MARKER_COLORS.get(color) or (color if color.startswith("#") else DEFAULT_COLOR)


def folder_pixmap(color: str, opened: bool = False, size: int = FOLDER_ICON) -> QPixmap:
    """O ícone da pasta pintado na cor dela (aberta: a frente inclinada)."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size * 2 / 24.0, size * 2 / 24.0)
    base = QColor(color_hex(color))
    p.setPen(Qt.PenStyle.NoPen)
    back = QPainterPath()
    back.moveTo(2.5, 5.5)
    back.lineTo(9.2, 5.5)
    back.lineTo(11.4, 7.8)
    back.lineTo(21.5, 7.8)
    back.lineTo(21.5, 19.5)
    back.lineTo(2.5, 19.5)
    back.closeSubpath()
    p.setBrush(base.darker(135))
    p.drawPath(back)
    front = QPainterPath()
    if opened:
        front.moveTo(5.0, 10.5)
        front.lineTo(23.0, 10.5)
        front.lineTo(20.2, 19.5)
        front.lineTo(2.5, 19.5)
    else:
        front.moveTo(2.5, 10.0)
        front.lineTo(21.5, 10.0)
        front.lineTo(21.5, 19.5)
        front.lineTo(2.5, 19.5)
    front.closeSubpath()
    p.setBrush(base)
    p.drawPath(front)
    p.end()
    pm.setDevicePixelRatio(2)
    return pm


def swatch(color: str, size: int = 14) -> QIcon:
    """Quadradinho da cor, para os menus."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color_hex(color)))
    p.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
    p.end()
    return QIcon(pm)


class FolderItem(QTreeWidgetItem):
    """Uma linha de pasta da árvore."""

    def __init__(self, folder: pastas.Folder):
        super().__init__([folder.name])
        self.fid = folder.id
        self.path = ""
        self.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
                      | Qt.ItemFlag.ItemIsDropEnabled | Qt.ItemFlag.ItemIsEditable)
        self.setSizeHint(0, QSize(0, FOLDER_ROW))
        self.paint(folder)

    def paint(self, folder: pastas.Folder) -> None:
        self.setText(0, folder.name)
        self.setIcon(0, QIcon(folder_pixmap(folder.color, self.isExpanded())))


class MediaItem(QTreeWidgetItem):
    """Uma linha de mídia da árvore (o item da lista de antes): `path` é a chave da fonte."""

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.fid = ""
        self.kind = "video"
        self.name = ""
        self.mtime = 0.0
        self.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)

    def text(self, column: int = 0) -> str:   # como o item da lista de antes (uma coluna só)
        return super().text(column)

    def data(self, *args):
        """Como o item da lista de antes: `data(UserRole)` é o caminho e `data(UserRole + 1)` o tipo."""
        if len(args) == 1:
            role = int(getattr(args[0], "value", args[0]))
            user = Qt.ItemDataRole.UserRole.value
            if role == user:
                return self.path
            if role == user + 1:
                return self.kind
            return super().data(0, args[0])
        return super().data(*args)


class FolderTree(QTreeWidget):
    """A Mídia como árvore: pastas que abrem e fecham e, dentro delas, os itens com miniatura. Sem nenhuma pasta
    é a lista de sempre. Arrasta os caminhos para a linha do tempo (o mesmo `MIME_SOURCE`), aceita arquivos do
    sistema e mexe nas pastas arrastando dentro do painel. O API de lista (`count`, `item`, `row`,
    `setCurrentRow`) conta só os itens de mídia, na ordem em que aparecem."""

    filesDropped = Signal(list)              # arquivos do sistema soltos fora de uma pasta
    filesDroppedIn = Signal(list, str)       # … soltos sobre uma pasta (id)
    moved = Signal(list, list, str)          # (caminhos, ids de pastas, pasta de destino ou "")
    renamed = Signal(str, str)               # (id da pasta, nome novo) — o nome editado na linha

    def __init__(self, icon_size: QSize, parent=None):
        super().__init__(parent)
        self.folders: Folders = Folders()
        self.sort_mode = "ordem"
        self._media: dict[str, MediaItem] = {}    # na ordem de importação
        self._folder_items: dict[str, FolderItem] = {}
        self._expanded: dict[str, bool] = {}      # aberta/fechada: vale enquanto o painel vive (não vai ao projeto)
        self._building = False
        self._drop: QTreeWidgetItem | None = None
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setIndentation(14)
        self.setRootIsDecorated(False)
        self.setExpandsOnDoubleClick(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setUniformRowHeights(False)
        self.setIconSize(icon_size)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setStyleSheet(f"QTreeWidget {{ background: transparent; border: none; outline: 0; }}"
                           f"QTreeWidget::item {{ padding: 4px; border-radius: 6px; color: {theme.TEXT}; }}"
                           f"QTreeWidget::item:selected {{ background: {theme.PANEL3}; color: {theme.ACCENT_HI}; }}"
                           f"QTreeWidget::item:hover {{ background: {theme.PANEL2}; }}")
        self.itemExpanded.connect(lambda it: self._opened(it, True))
        self.itemCollapsed.connect(lambda it: self._opened(it, False))
        self.itemChanged.connect(self._edited)

    # -------------------------------------------------------- API de lista (só a mídia)
    def media_items(self) -> list[MediaItem]:
        """Os itens de mídia na ordem em que aparecem (subpastas antes dos itens de cada pasta)."""
        out: list[MediaItem] = []

        def walk(parent: QTreeWidgetItem) -> None:
            for i in range(parent.childCount()):
                ch = parent.child(i)
                if isinstance(ch, MediaItem):
                    out.append(ch)
                else:
                    walk(ch)
        walk(self.invisibleRootItem())
        return out

    def count(self) -> int:
        return len(self._media)

    def item(self, i: int) -> MediaItem | None:
        items = self.media_items()
        return items[i] if 0 <= i < len(items) else None

    def row(self, item: QTreeWidgetItem) -> int:
        items = self.media_items()
        return items.index(item) if item in items else -1

    def setCurrentRow(self, i: int) -> None:
        it = self.item(i)
        if it is not None:
            self.setCurrentItem(it)

    def selected_media(self) -> list[MediaItem]:
        order = {id(it): i for i, it in enumerate(self.media_items())}
        return sorted((it for it in self.selectedItems() if isinstance(it, MediaItem)), key=lambda it: order[id(it)])

    def selected_folders(self) -> list[str]:
        return [it.fid for it in self.selectedItems() if isinstance(it, FolderItem)]

    def media(self, path: str) -> MediaItem | None:
        return self._media.get(path)

    def folder_item(self, fid: str) -> FolderItem | None:
        return self._folder_items.get(fid)

    # -------------------------------------------------------- itens
    def add_media(self, item: MediaItem) -> None:
        """Item novo na árvore (na pasta dele, no fim da ordem de importação)."""
        self._media[item.path] = item
        if self.sort_mode != "ordem":
            self.relayout()
        else:
            self._attach(item)

    def remove_media(self, path: str) -> None:
        it = self._media.pop(path, None)
        if it is not None:
            self._detach(it)

    def clear_all(self) -> None:
        """Tira tudo (mídia e linhas de pasta); a abertura das pastas é lembrada."""
        self._media.clear()
        self._folder_items.clear()
        self.clear()

    def _detach(self, it: QTreeWidgetItem) -> None:
        parent = it.parent()
        if parent is None:
            idx = self.indexOfTopLevelItem(it)
            if idx >= 0:
                self.takeTopLevelItem(idx)
        else:
            parent.takeChild(parent.indexOfChild(it))

    def _folder_row(self, fid: str) -> QTreeWidgetItem:
        """A linha da pasta (criada, com as de cima, se ainda não existe) ou a raiz."""
        if not fid or self.folders.get(fid) is None:
            return self.invisibleRootItem()
        row = self._folder_items.get(fid)
        if row is None:
            f = self.folders.get(fid)
            row = FolderItem(f)
            self._building = True
            try:
                self._folder_row(f.parent).addChild(row)
                self._folder_items[fid] = row
                row.setExpanded(self._expanded.get(fid, True))
                row.paint(f)
            finally:
                self._building = False
        return row

    def _attach(self, it: MediaItem) -> None:
        self._building = True
        try:
            parent = self._folder_row(self.folders.folder_of(it.path))
            parent.addChild(it)
        finally:
            self._building = False
        self.setRootIsDecorated(self.folders.has_folders())

    def _sorted(self, items: list[MediaItem]) -> list[MediaItem]:
        mode = self.sort_mode
        if mode == "nome":
            return sorted(items, key=lambda i: (i.name.casefold(), i.path))
        if mode == "tipo":
            return sorted(items, key=lambda i: (KIND_ORDER.get(i.kind, 9), i.name.casefold()))
        if mode == "data":
            return sorted(items, key=lambda i: (-i.mtime, i.name.casefold()))
        return items

    def relayout(self) -> None:
        """Refaz a árvore a partir de `self.folders`: as linhas de pasta e onde cada item fica. Mantém os mesmos
        itens (e a escolha); só o que a pasta tem de novo ou de menos muda de lugar."""
        sel = [it.path for it in self.selected_media()]
        sel_folders = self.selected_folders()
        cur = self.currentItem()
        cur_key = (cur.path, cur.fid) if cur is not None else None
        self._building = True
        self._drop = None
        try:
            for it in self._media.values():
                self._detach(it)
            self._folder_items.clear()
            self.clear()
            folders = self.folders

            def fill(fid: str, parent: QTreeWidgetItem) -> None:
                kids = folders.children(fid)
                if self.sort_mode != "ordem":
                    kids = sorted(kids, key=lambda f: f.name.casefold())
                for f in kids:
                    row = FolderItem(f)
                    parent.addChild(row)
                    self._folder_items[f.id] = row
                    fill(f.id, row)
                    row.setExpanded(self._expanded.get(f.id, True))
                    row.paint(f)
                here = [it for it in self._media.values() if folders.folder_of(it.path) == fid
                        or (fid == "" and folders.get(folders.folder_of(it.path)) is None)]
                for it in self._sorted(here):
                    parent.addChild(it)

            fill("", self.invisibleRootItem())
        finally:
            self._building = False
        self.setRootIsDecorated(self.folders.has_folders())
        for it in self._media.values():
            it.setSelected(it.path in sel)
        for fid in sel_folders:
            row = self._folder_items.get(fid)
            if row is not None:
                row.setSelected(True)
        if cur_key is not None:
            target = self._media.get(cur_key[0]) if cur_key[0] else self._folder_items.get(cur_key[1])
            if target is not None:
                self.setCurrentItem(target, 0, QItemSelectionModel.SelectionFlag.NoUpdate)

    def _opened(self, it: QTreeWidgetItem, opened: bool) -> None:
        if isinstance(it, FolderItem) and not self._building:
            self._expanded[it.fid] = opened
            f = self.folders.get(it.fid)
            if f is not None:
                it.paint(f)

    def _edited(self, it: QTreeWidgetItem, _col: int) -> None:
        if isinstance(it, FolderItem) and not self._building:
            f = self.folders.get(it.fid)
            if f is not None and it.text(0) != f.name:
                self.renamed.emit(it.fid, it.text(0))

    def edit_folder(self, fid: str) -> None:
        row = self._folder_items.get(fid)
        if row is not None:
            self.setCurrentItem(row)
            self.editItem(row, 0)

    # -------------------------------------------------------- arrastar
    def mimeTypes(self):
        return [MIME_SOURCE, MIME_FOLDERS, "text/uri-list"]

    def mimeData(self, items):
        md = QMimeData()
        fids = [it.fid for it in items if isinstance(it, FolderItem)]
        under = {i for f in fids for i in self.folders.descendants(f)} | set(fids)
        # item dentro de uma pasta que vai junto não é arrastado à parte (a pasta já leva ele)
        paths = [it.path for it in items if isinstance(it, MediaItem) and self.folders.folder_of(it.path) not in under]
        if paths:
            md.setData(MIME_SOURCE, "\n".join(paths).encode("utf-8"))
            md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        if fids:
            md.setData(MIME_FOLDERS, "\n".join(fids).encode("utf-8"))
        return md

    def _target(self, pos) -> str:
        """A pasta sob o cursor: a própria linha de pasta, a pasta do item de mídia, ou "" (raiz)."""
        it = self.itemAt(pos)
        if isinstance(it, FolderItem):
            return it.fid
        if isinstance(it, MediaItem):
            return self.folders.folder_of(it.path)
        return ""

    def _mark(self, fid: str) -> None:
        """Pinta a pasta de destino enquanto se arrasta."""
        row = self._folder_items.get(fid) if fid else None
        if row is self._drop:
            return
        self._unmark()
        if row is not None:
            row.setBackground(0, QBrush(QColor(theme.ACCENT_DIM)))
            self._drop = row

    def _unmark(self) -> None:
        if self._drop is not None:
            try:
                self._drop.setBackground(0, QBrush())
            except RuntimeError:   # a linha foi apagada no meio do arrasto
                pass
            self._drop = None

    def _internal(self, e) -> bool:
        """O arrasto começou neste painel (mexer nas pastas) e não veio de fora (importar arquivos)."""
        return e.source() is self

    def _accepts(self, e) -> bool:
        md = e.mimeData()
        if self._internal(e):
            return md.hasFormat(MIME_SOURCE) or md.hasFormat(MIME_FOLDERS)
        return md.hasUrls() and not md.hasFormat(MIME_SOURCE)

    def dragEnterEvent(self, e):
        if self._accepts(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if not self._accepts(e):
            e.ignore()
            return
        target = self._target(e.position().toPoint())
        fids = bytes(e.mimeData().data(MIME_FOLDERS)).decode("utf-8").split("\n") if self._internal(e) \
            and e.mimeData().hasFormat(MIME_FOLDERS) else []
        if target and any(target == f or target in self.folders.descendants(f) for f in fids if f):
            self._unmark()
            e.ignore()      # uma pasta dentro dela mesma
            return
        self._mark(target)
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._unmark()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._unmark()
        if not self._accepts(e):
            e.ignore()
            return
        target = self._target(e.position().toPoint())
        md = e.mimeData()
        if self._internal(e):
            paths = bytes(md.data(MIME_SOURCE)).decode("utf-8").split("\n") if md.hasFormat(MIME_SOURCE) else []
            fids = bytes(md.data(MIME_FOLDERS)).decode("utf-8").split("\n") if md.hasFormat(MIME_FOLDERS) else []
            e.setDropAction(Qt.DropAction.CopyAction)   # nunca "mover": o Qt apagaria os itens arrastados
            e.accept()
            self.moved.emit([p for p in paths if p], [f for f in fids if f], target)
            return
        paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            if target:
                self.filesDroppedIn.emit(paths, target)
            else:
                self.filesDropped.emit(paths)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_F2 and isinstance(self.currentItem(), FolderItem):
            self.edit_folder(self.currentItem().fid)
            return
        super().keyPressEvent(e)


class FolderActions:
    """As ações das pastas do painel (botões, menus, atalhos), ligadas ao modelo da linha do tempo
    (`TimelineModel.folder_*`). `bin` é o `edit_panels.MediaBin`."""

    def __init__(self, bin_, model):
        self.bin = bin_
        self.model = model
        self.tree: FolderTree = bin_.list
        self.btn_folder = bin_._flat("folder", _("Nova pasta (Ctrl+Shift+N)"))
        self.btn_folder.clicked.connect(lambda: self.new_folder())
        self.btn_sort = bin_._flat("chapters", _("Ordenar a Mídia"))
        self.btn_sort.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sort_group = QActionGroup(bin_)
        self.sort_menu = QMenu(bin_)
        for key, label in SORTS:
            act = self.sort_menu.addAction(_(label))
            act.setCheckable(True)
            act.setChecked(key == self.tree.sort_mode)
            act.triggered.connect(lambda _c=False, k=key: self.set_sort(k))
            self.sort_group.addAction(act)
        self.btn_sort.setMenu(self.sort_menu)
        self.tree.filesDroppedIn.connect(bin_.filesDroppedIn)
        self.tree.moved.connect(self._moved)
        self.tree.renamed.connect(self._renamed)
        self.tree.itemDoubleClicked.connect(self._double_click)
        model.changed.connect(self._model_changed)
        self.refresh()

    # -------------------------------------------------------- modelo → painel
    @property
    def folders(self) -> Folders:
        return self.model.seq.folders

    def _model_changed(self, kind: str) -> None:
        if kind in ("pastas", "*"):
            self.refresh()

    def refresh(self) -> None:
        """Mostra as pastas do modelo (depois de qualquer mudança nelas, de desfazer ou de abrir um projeto)."""
        self.tree.folders = self.folders
        self.tree.relayout()
        self.bin._sync()

    def set_sort(self, key: str) -> None:
        if key != self.tree.sort_mode:
            self.tree.sort_mode = key
            self.tree.relayout()
        for act, (k, _label) in zip(self.sort_group.actions(), SORTS):
            act.setChecked(k == key)

    # -------------------------------------------------------- operações
    def new_folder(self, parent: str = "", name: str = "") -> str:
        """"Nova pasta": dentro de `parent`, ou da pasta escolhida; abre o nome para digitar."""
        if not parent:
            sel = self.tree.selected_folders()
            parent = sel[0] if len(sel) == 1 else ""
        if parent:   # pasta de dentro de uma pasta fechada aparece aberta
            self.tree._expanded[parent] = True
        fid = self.model.folder_create(name or _("Nova pasta"), parent)
        if not name:
            self.tree.edit_folder(fid)
        return fid

    def rename(self, fid: str) -> None:
        self.tree.edit_folder(fid)

    def _renamed(self, fid: str, name: str) -> None:
        # depois que o editor da linha fecha: refazer a árvore agora a apagaria por baixo dele
        QTimer.singleShot(0, lambda: self._apply_rename(fid, name))

    def _apply_rename(self, fid: str, name: str) -> None:
        if not self.model.folder_rename(fid, name):
            self.refresh()   # nome vazio ou igual: volta o que estava

    def set_color(self, fid: str, color: str) -> None:
        self.model.folder_color(fid, color)

    def pick_color(self, fid: str) -> None:
        f = self.folders.get(fid)
        if f is None:
            return
        c = QColorDialog.getColor(QColor(color_hex(f.color)), self.bin, _("Cor da pasta"))
        if c.isValid():
            self.set_color(fid, c.name())

    def confirm_delete(self, fid: str) -> bool:
        """Pasta com algo dentro: pergunta (a mídia sobe para a pasta de cima, nada sai do projeto)."""
        box = QMessageBox(self.bin)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Apagar pasta"))
        box.setText(_("A pasta tem itens ou subpastas. Eles sobem para a pasta de cima; nenhum arquivo sai do "
                      "projeto nem do disco."))
        ok = box.addButton(_("Apagar só a pasta"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is ok

    def delete(self, fid: str, ask: bool = True) -> bool:
        f = self.folders.get(fid)
        if f is None:
            return False
        full = bool(self.folders.items_in(fid) or self.folders.children(fid))
        if ask and full and not self.confirm_delete(fid):
            return False
        return self.model.folder_delete(fid)

    def delete_selected(self) -> None:
        for fid in self.tree.selected_folders():
            self.delete(fid)

    def move_media(self, paths: list[str], fid: str) -> None:
        self.model.media_to_folder(paths, fid, self.bin._sources)

    def _moved(self, paths: list, fids: list, target: str) -> None:
        self.model.folder_drop(paths, fids, target, self.bin._sources)

    def _double_click(self, it: QTreeWidgetItem, _col: int) -> None:
        if isinstance(it, FolderItem):
            self.tree.edit_folder(it.fid)
        elif isinstance(it, MediaItem):
            (self.bin.openRequested if it.kind == "sequencia" else self.bin.addRequested).emit(it.path)

    # -------------------------------------------------------- menus
    def menu(self, pos) -> None:
        """Menu do botão direito: na pasta, no item ou no vazio."""
        it = self.tree.itemAt(pos)
        if it is not None and not it.isSelected():
            self.tree.clearSelection()
            it.setSelected(True)
            self.tree.setCurrentItem(it)
        menu = QMenu(self.bin)
        if isinstance(it, FolderItem):
            self._folder_menu(menu, it.fid)
        elif isinstance(it, MediaItem):
            self.bin.fill_media_menu(menu)
            menu.addSeparator()
            self._move_menu(menu)
            menu.addAction(_("Nova pasta"), self.new_folder).setShortcut(QKeySequence("Ctrl+Shift+N"))
        else:
            menu.addAction(_("Nova pasta"), self.new_folder).setShortcut(QKeySequence("Ctrl+Shift+N"))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _folder_menu(self, menu: QMenu, fid: str) -> None:
        f = self.folders.get(fid)
        menu.addAction(_("Renomear"), lambda: self.rename(fid)).setShortcut(QKeySequence("F2"))
        colors = menu.addMenu(_("Cor"))
        self.fill_color_menu(colors, fid, f.color if f else "")
        menu.addAction(_("Nova subpasta"), lambda: self.new_folder(fid))
        menu.addSeparator()
        menu.addAction(_("Apagar pasta"), lambda: self.delete(fid))

    def fill_color_menu(self, menu: QMenu, fid: str, current: str) -> None:
        act = menu.addAction(swatch(""), _("Padrão"))
        act.setCheckable(True)
        act.setChecked(current == "")
        act.triggered.connect(lambda _c=False: self.set_color(fid, ""))
        for key, label in MARKER_COLORS:
            act = menu.addAction(swatch(key), _(label))
            act.setCheckable(True)
            act.setChecked(current == key)
            act.triggered.connect(lambda _c=False, k=key: self.set_color(fid, k))
        menu.addSeparator()
        custom = current.startswith("#")
        act = menu.addAction(swatch(current) if custom else QIcon(), _("Personalizada…"))
        act.setCheckable(True)
        act.setChecked(custom)
        act.triggered.connect(lambda _c=False: self.pick_color(fid))

    def _move_menu(self, menu: QMenu) -> None:
        """"Mover para ▸": a raiz e cada pasta (com o caminho dela)."""
        if not self.folders.has_folders():
            return
        sub = menu.addMenu(_("Mover para"))
        sub.addAction(_("Raiz da Mídia"), lambda: self.move_media(self.bin.selected_paths(), ""))
        for f in self.folders.folders.values():
            sub.addAction(folder_icon(f.color), " ▸ ".join(self.folders.path_of(f.id)),
                          lambda fid=f.id: self.move_media(self.bin.selected_paths(), fid))


def folder_icon(color: str) -> QIcon:
    return QIcon(folder_pixmap(color, size=16))


def media_in_dir(path: str) -> list[str]:
    """Os arquivos de mídia de uma pasta do sistema (vídeo, imagem e áudio; sem descer nas subpastas), por nome."""
    ok = media.VIDEO_EXT | media.IMAGE_EXT | media.AUDIO_EXT
    try:
        names = sorted(os.listdir(path), key=str.casefold)
    except OSError:
        return []
    return [os.path.join(path, n) for n in names
            if os.path.splitext(n)[1].lower() in ok and os.path.isfile(os.path.join(path, n))]
