"""Casos da interface das pastas da Mídia (1.7, #58): criar, renomear, cor, arrastar para dentro e para fora,
apagar, desfazer, reabrir o projeto, painel sem pastas igual ao de antes.

Rodados por test_pastas_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de uma
QApplication própria. Este arquivo não é coletado sozinho pelo pytest.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent, QShortcut  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import project, timeline as tl  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.edit_panels import MediaBin  # noqa: E402
from pelicula.ui.pastas_ui import MIME_FOLDERS, FolderItem, MediaItem  # noqa: E402
from pelicula.ui.timeline_view import MIME_SOURCE  # noqa: E402

LMB = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier


def src(path, frames=48, **kw) -> tl.Source:
    return tl.Source(path, 640, 360, 24.0, "24/1", frames, frames / 24.0, has_audio=True, **kw)


def bin_with(*paths) -> tuple[MediaBin, TimelineModel]:
    """A Mídia ligada a um modelo, com os arquivos importados (nenhum na linha do tempo)."""
    m = TimelineModel(tl.Sequence(640, 360, "24/1"))
    b = MediaBin(model=m)
    for p in paths:
        b.add_source(src(p))
    return b, m


def rows(b: MediaBin) -> list[str]:
    """A árvore em texto: "pasta:" para pastas, o caminho dos itens, com recuo de dois espaços por nível."""
    out: list[str] = []

    def walk(parent, depth):
        for i in range(parent.childCount()):
            ch = parent.child(i)
            out.append("  " * depth + (f"[{ch.text(0)}]" if isinstance(ch, FolderItem) else ch.path))
            walk(ch, depth + 1)
    walk(b.list.invisibleRootItem(), 0)
    return out


def center(b: MediaBin, item) -> QPoint:
    return b.list.visualItemRect(item).center()


def drop_urls(b: MediaBin, item, paths) -> None:
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    pos = QPointF(center(b, item)) if item is not None else QPointF(b.list.viewport().width() / 2, 4000)
    ev = QDropEvent(pos, Qt.DropAction.CopyAction, md, LMB, NOMOD)
    b.list.dropEvent(ev)


# ------------------------------------------------------------------ painel sem pastas
def test_panel_without_folders_is_the_flat_list():
    b, _m = bin_with("C:/v/a.mp4", "C:/v/b.mp4", "C:/v/c.mp4")
    assert rows(b) == ["C:/v/a.mp4", "C:/v/b.mp4", "C:/v/c.mp4"]
    assert not b.list.rootIsDecorated() and b.list.topLevelItemCount() == 3
    assert b.paths() == ["C:/v/a.mp4", "C:/v/b.mp4", "C:/v/c.mp4"] and b.stack.currentWidget() is b.list
    assert b.list.count() == 3 and b.list.item(2).path == "C:/v/c.mp4" and b.list.row(b.list.item(1)) == 1
    assert not any(isinstance(b.list.topLevelItem(i), FolderItem) for i in range(3))
    b.remove("C:/v/b.mp4")
    assert rows(b) == ["C:/v/a.mp4", "C:/v/c.mp4"]
    b.clear()
    assert rows(b) == [] and b.stack.currentWidget() is b.empty


# ------------------------------------------------------------------ criar, renomear, cor, apagar
def test_create_rename_color_and_delete_a_folder():
    b, m = bin_with("C:/v/a.mp4", "C:/v/b.mp4")
    fid = b.pastas.new_folder(name="Cenas")
    assert rows(b) == ["[Cenas]", "C:/v/a.mp4", "C:/v/b.mp4"] and b.list.rootIsDecorated()
    sub = b.pastas.new_folder(fid, name="Takes")
    assert rows(b)[:2] == ["[Cenas]", "  [Takes]"]
    row = b.list.folder_item(fid)
    row.setText(0, "Externas")       # o nome editado na linha
    APP.processEvents()
    assert m.seq.folders.get(fid).name == "Externas" and rows(b)[0] == "[Externas]"
    row = b.list.folder_item(fid)
    row.setText(0, "   ")           # nome vazio volta ao que era
    APP.processEvents()
    assert m.seq.folders.get(fid).name == "Externas" and rows(b)[0] == "[Externas]"
    b.pastas.set_color(sub, "verde")
    assert m.seq.folders.get(sub).color == "verde" and not b.list.folder_item(sub).icon(0).isNull()
    b.pastas.set_color(sub, "#123abc")
    assert m.seq.folders.get(sub).color == "#123abc"
    m.undo()
    assert m.seq.folders.get(sub).color == "verde"
    m.undo()
    assert m.seq.folders.get(sub).color == ""
    b.pastas.move_media(["C:/v/a.mp4"], sub)
    assert rows(b) == ["[Externas]", "  [Takes]", "    C:/v/a.mp4", "C:/v/b.mp4"]
    # apagar uma pasta cheia pergunta; "Cancelar" não faz nada
    asked = []
    b.pastas.confirm_delete = lambda f: asked.append(f) or False
    assert not b.pastas.delete(sub) and asked == [sub] and m.seq.folders.get(sub)
    b.pastas.confirm_delete = lambda f: True
    assert b.pastas.delete(sub)
    assert m.seq.folders.get(sub) is None and m.seq.folders.folder_of("C:/v/a.mp4") == fid   # sobe para a mãe
    assert b.paths() == ["C:/v/a.mp4", "C:/v/b.mp4"] and "C:/v/a.mp4" in m.seq.sources
    empty = b.pastas.new_folder(name="Vazia")
    asked.clear()
    assert b.pastas.delete(empty) and asked == []   # vazia: sem pergunta
    m.undo()
    assert m.seq.folders.get(empty) is not None and "[Vazia]" in rows(b)


def test_color_menu_and_context_menu_build():
    from PySide6.QtWidgets import QMenu
    b, m = bin_with("C:/v/a.mp4")
    fid = b.pastas.new_folder(name="X")
    menu = QMenu()
    b.pastas.fill_color_menu(menu, fid, "")
    labels = [a.text() for a in menu.actions() if a.text()]
    assert labels[0] == "Padrão" and "Laranja" in labels and labels[-1] == "Personalizada…" and len(labels) == 10
    next(a for a in menu.actions() if a.text() == "Azul").trigger()
    assert m.seq.folders.get(fid).color == "azul"
    cx = QMenu()
    b.pastas._folder_menu(cx, fid)
    assert [a.text() for a in cx.actions() if a.text()] == ["Renomear", "Cor", "Nova subpasta", "Apagar pasta"]


# ------------------------------------------------------------------ arrastar
def test_drag_media_and_folders_in_and_out():
    b, m = bin_with("C:/v/a.mp4", "C:/v/b.mp4", "C:/v/c.mp4")
    f1, f2 = b.pastas.new_folder(name="Um"), b.pastas.new_folder(name="Dois")
    t = b.list
    t.moved.emit(["C:/v/a.mp4", "C:/v/b.mp4"], [], f1)           # o que o drop interno emite
    assert rows(b) == ["[Um]", "  C:/v/a.mp4", "  C:/v/b.mp4", "[Dois]", "C:/v/c.mp4"]
    t.moved.emit([], [f2], f1)                                   # pasta para dentro de pasta
    assert rows(b) == ["[Um]", "  [Dois]", "  C:/v/a.mp4", "  C:/v/b.mp4", "C:/v/c.mp4"]
    t.moved.emit([], [f1], f2)                                   # ciclo: nada muda
    assert m.seq.folders.get(f1).parent == ""
    n = len(m.history._states)
    t.moved.emit(["C:/v/a.mp4"], [], "")                         # para fora
    assert m.seq.folders.folder_of("C:/v/a.mp4") == "" and len(m.history._states) == n + 1
    m.undo()
    assert m.seq.folders.folder_of("C:/v/a.mp4") == f1 and rows(b)[2] == "  C:/v/a.mp4"
    # a posição do cursor decide o destino: sobre a pasta, sobre um item (a pasta dele) ou no vazio (raiz)
    assert t._target(center(b, t.folder_item(f2))) == f2
    assert t._target(center(b, t.media("C:/v/b.mp4"))) == f1
    assert t._target(center(b, t.media("C:/v/c.mp4"))) == ""
    assert t._target(QPoint(5, t.viewport().height() - 2)) in ("", f1, f2)


def test_internal_drop_uses_the_mime_and_never_removes_items():
    b, m = bin_with("C:/v/a.mp4", "C:/v/b.mp4")
    f1 = b.pastas.new_folder(name="Um")
    t = b.list
    md = t.mimeData([t.media("C:/v/a.mp4")])
    assert bytes(md.data(MIME_SOURCE)).decode() == "C:/v/a.mp4" and not md.hasFormat(MIME_FOLDERS)
    md = t.mimeData([t.folder_item(f1)])
    assert not md.hasFormat(MIME_SOURCE) and bytes(md.data(MIME_FOLDERS)).decode() == f1
    got = []
    t.moved.connect(lambda p, f, tg: got.append((p, f, tg)))
    pos = QPointF(center(b, t.folder_item(f1)))
    md = t.mimeData([t.media("C:/v/b.mp4")])
    ev = QDropEvent(pos, Qt.DropAction.CopyAction, md, LMB, NOMOD)
    assert t._accepts(ev) is False        # um evento de fora (sem o painel como origem) não mexe nas pastas
    t._internal = lambda e: True          # o que o Qt diz num arrasto que começou aqui
    t.dropEvent(QDropEvent(pos, Qt.DropAction.CopyAction, md, LMB, NOMOD))
    assert got == [(["C:/v/b.mp4"], [], f1)]
    assert sorted(b.paths()) == ["C:/v/a.mp4", "C:/v/b.mp4"] and m.seq.folders.folder_of("C:/v/b.mp4") == f1
    fm = t.mimeData([t.folder_item(f1)])
    t.dropEvent(QDropEvent(QPointF(5, t.viewport().height() - 2), Qt.DropAction.CopyAction, fm, LMB, NOMOD))
    assert got[-1][1] == [f1]


def test_drag_mime_is_unchanged_with_folders_and_multi_selection():
    b, m = bin_with("C:/v/a.mp4", "C:/v/b.mp4", "C:/v/c.mp4")
    f1 = b.pastas.new_folder(name="Um")
    b.pastas.move_media(["C:/v/b.mp4"], f1)
    t = b.list
    assert rows(b) == ["[Um]", "  C:/v/b.mp4", "C:/v/a.mp4", "C:/v/c.mp4"]
    t.item(0).setSelected(True)       # b (dentro da pasta)
    t.item(2).setSelected(True)       # c
    t.folder_item(f1).setSelected(True)
    assert b.selected_paths() == ["C:/v/b.mp4", "C:/v/c.mp4"]      # pasta escolhida não é item
    md = t.mimeData(t.selectedItems())
    # a pasta escolhida leva o b junto: o b não vai duas vezes
    assert bytes(md.data(MIME_SOURCE)).decode() == "C:/v/c.mp4" and bytes(md.data(MIME_FOLDERS)).decode() == f1
    t.folder_item(f1).setSelected(False)
    md = t.mimeData(t.selectedItems())
    assert sorted(bytes(md.data(MIME_SOURCE)).decode().split("\n")) == ["C:/v/b.mp4", "C:/v/c.mp4"]
    assert [u.toLocalFile() for u in md.urls()] and md.hasFormat("text/uri-list")
    got = []
    b.placeRequested.connect(lambda p, ins: got.append((p, ins)))
    b.place(True)
    assert got == [(["C:/v/b.mp4", "C:/v/c.mp4"], True)]
    addr = []
    b.addRequested.connect(addr.append)
    b.btn_add.click()
    assert addr == ["C:/v/b.mp4", "C:/v/c.mp4"]
    t.clearSelection()
    t.folder_item(f1).setSelected(True)
    b.place(False)
    assert len(got) == 1 and not b.btn_add.isEnabled()


def test_system_files_dropped_on_a_folder_import_into_it():
    b, m = bin_with("C:/v/a.mp4")
    f1 = b.pastas.new_folder(name="Um")
    into, plain = [], []
    b.filesDroppedIn.connect(lambda p, f: into.append((p, f)))
    b.filesDropped.connect(plain.append)
    drop_urls(b, b.list.folder_item(f1), ["C:/x/novo.mp4"])
    assert into == [(["C:/x/novo.mp4"], f1)] and plain == []
    drop_urls(b, None, ["C:/x/outro.mp4"])
    assert plain == [["C:/x/outro.mp4"]]


# ------------------------------------------------------------------ desfazer, ordem, aberta/fechada
def test_undo_redo_refresh_the_panel():
    b, m = bin_with("C:/v/a.mp4", "C:/v/b.mp4")
    f1 = b.pastas.new_folder(name="Um")
    b.pastas.move_media(["C:/v/a.mp4"], f1)
    assert rows(b) == ["[Um]", "  C:/v/a.mp4", "C:/v/b.mp4"]
    m.undo()
    assert rows(b) == ["[Um]", "C:/v/a.mp4", "C:/v/b.mp4"]
    m.undo()
    assert rows(b) == ["C:/v/a.mp4", "C:/v/b.mp4"] and not b.list.rootIsDecorated()
    m.redo()
    m.redo()
    assert rows(b) == ["[Um]", "  C:/v/a.mp4", "C:/v/b.mp4"]


def test_sort_and_expanded_state():
    b, m = bin_with("C:/v/zeta.mp4", "C:/v/alfa.mp4")
    b.add_source(src("C:/v/musica.mp3", has_video=False))
    f1 = b.pastas.new_folder(name="Um")
    assert b.paths() == ["C:/v/zeta.mp4", "C:/v/alfa.mp4", "C:/v/musica.mp3"] and b.list.sort_mode == "ordem"
    b.pastas.set_sort("nome")
    assert b.paths() == ["C:/v/alfa.mp4", "C:/v/musica.mp3", "C:/v/zeta.mp4"]
    b.pastas.set_sort("tipo")
    assert b.paths()[-1] == "C:/v/musica.mp3"
    b.pastas.set_sort("ordem")
    assert b.paths() == ["C:/v/zeta.mp4", "C:/v/alfa.mp4", "C:/v/musica.mp3"]
    b.pastas.move_media(["C:/v/zeta.mp4"], f1)
    row = b.list.folder_item(f1)
    assert row.isExpanded()
    row.setExpanded(False)
    b.pastas.new_folder(name="Outra")          # refaz a árvore: a pasta continua fechada
    assert not b.list.folder_item(f1).isExpanded()
    b.list.folder_item(f1).setExpanded(True)
    b.pastas.set_sort("nome")
    assert b.list.folder_item(f1).isExpanded()
    assert m.seq.folders.has_folders() and m.seq.to_json()["formato"] == tl.FORMAT


# ------------------------------------------------------------------ projeto e janela
def test_reopen_brings_folders_and_unused_media_back(tmp_path):
    """Pasta com um arquivo que nenhum clipe usa: volta ao reabrir o projeto."""
    used, loose = str(tmp_path / "usado.mp4"), str(tmp_path / "solto.mp4")
    for p in (used, loose):
        open(p, "wb").close()
    b, m = bin_with()
    seq = tl.Sequence.for_source(src(used))
    m.set_sequence(seq)
    b.add_source(src(used))
    b.add_source(src(loose))
    f1 = b.pastas.new_folder(name="Sobras")
    b.pastas.move_media([loose], f1)
    p = project.Project(media_path=used, sequence=m.seq.to_json(), mode="edicao")
    project.save(p, str(tmp_path / "p.plc"))
    back = tl.Sequence.from_json(project.load(str(tmp_path / "p.plc")).sequence)
    b2 = MediaBin(model=TimelineModel(tl.Sequence()))
    b2.clear()
    for s in back.sources.values():    # o que a janela faz ao abrir um projeto
        b2.add_source(s)
    b2.pastas.model.set_sequence(back)
    assert rows(b2) == ["[Sobras]", f"  {loose}", used]


@pytest.fixture
def win():
    from pelicula.ui import prefs
    from pelicula.ui.main_window import MainWindow
    prefs.settings().setValue("auto_update", "false")
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


def test_folder_buttons_sit_on_the_title_row():
    """A fila de Importar é a de antes das pastas: com mais dois botões, "Importar…" saía cortado na largura do painel."""
    b, _m = bin_with()
    b.btn_new.setVisible(True)
    b.resize(310, 500)
    b.show()
    APP.processEvents()
    try:
        assert b.pastas.btn_folder.isVisible() and b.pastas.btn_sort.isVisible()
        assert b.pastas.btn_folder.y() == b.pastas.btn_sort.y()
        assert b.pastas.btn_folder.geometry().bottom() < b.btn_import.y()
        fila = b.btn_import.geometry()
        for w in (b.btn_new, b.btn_add, b.btn_remove):
            assert fila.top() <= w.geometry().center().y() <= fila.bottom()  # centralizados na mesma fila
    finally:
        b.close()


def test_window_open_project_with_unused_media_in_a_folder(win, tmp_path):
    used, loose = str(tmp_path / "usado.mp4"), str(tmp_path / "solto.mp4")
    for p in (used, loose):
        open(p, "wb").close()
    seq = tl.Sequence.for_source(src(used))
    seq.sources[loose] = src(loose)
    f = seq.folders.create("Entrada")
    seq.folders.assign([loose], f.id)
    path = str(tmp_path / "p.plc")
    project.save(project.Project(media_path=used, sequence=seq.to_json(), mode="edicao"), path)
    win.show_project(project.load(path))
    APP.processEvents()
    assert win.bin.paths() == [loose, used] and rows(win.bin)[0] == "[Entrada]"
    assert win.model.seq.folders.folder_of(loose) == f.id
    # salvar de novo mantém a pasta e o arquivo solto; o projeto fica no formato 5
    assert win._seq_json()["pastas"]["fontes"][0]["caminho"] == loose
    out = str(tmp_path / "q.plc")
    project.save(project.Project(media_path=used, sequence=win._seq_json(), mode="edicao"), out)
    assert project.load(out).to_json()["formato"] == 5


def test_window_folders_without_clips_are_saved(win):
    win.set_mode("edicao")
    win.model.folder_create("Só pasta")
    assert win._seq_json() is not None and "pastas" in win._seq_json()


def test_window_remove_media_leaves_its_folder(win, monkeypatch):
    win.set_mode("edicao")
    s = src("C:/nao_existe/a.mp4")
    win.adopt_source(s)
    fid = win.model.folder_create("Um")
    win.model.media_to_folder([s.path], fid, win._sources)
    assert rows(win.bin) == ["[Um]", f"  {s.path}"]
    win._bin_remove(s.path)
    assert rows(win.bin) == ["[Um]"] and win.model.seq.folders.items == {}


def test_window_dropping_a_system_folder_makes_a_folder(win, tmp_path, monkeypatch):
    win.set_mode("edicao")
    d = tmp_path / "Takes"
    d.mkdir()
    for n in ("b.mp4", "a.mov", "nota.txt"):
        (d / n).write_bytes(b"")
    monkeypatch.setattr(win, "_probe_source", lambda p: win.adopt_source(src(p)))
    n = len(win.model.history._states)
    win._bin_files([str(d)])
    assert rows(win.bin) == ["[Takes]", f"  {d / 'a.mov'}", f"  {d / 'b.mp4'}"]
    assert len(win.model.history._states) == n + 1
    sub = win.model.seq.folders.children("")[0].id
    extra = tmp_path / "c.mp4"
    extra.write_bytes(b"")
    win._bin_files([str(extra)], sub)
    assert win.model.seq.folders.folder_of(str(extra)) == sub


def test_window_new_folder_shortcut(win):
    sc = [s for s in win.findChildren(QShortcut) if s.key().toString() == "Ctrl+Shift+N"]
    assert len(sc) == 1
    win.set_mode("edicao")
    sc[0].activated.emit()
    APP.processEvents()
    assert len(win.model.seq.folders.folders) == 1
