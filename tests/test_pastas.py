"""Pastas do painel de mídia (`pastas.py`, `Sequence.folders`, bloco "pastas", `TimelineModel.folder_*`). Sem GPU."""

from __future__ import annotations

import json
import os

import pytest

from pelicula import pastas, project, timeline as tl
from pelicula.pastas import Folders
from pelicula.ui.edit_model import TimelineModel


def _src(path="C:/v/a.mp4", **kw):
    return tl.Source(path, 320, 180, 24.0, "24/1", 48, 2.0, pix_fmt="yuv420p", has_audio=True, **kw)


# ------------------------------------------------------------------ modelo puro
def test_palette_is_the_marker_palette():
    assert pastas.PALETTE == tl.MARKER_COLOR_KEYS


def test_create_rename_color_and_ids_are_deterministic():
    f = Folders()
    a = f.create("Cenas")
    b = f.create("  Takes   boas ", parent=a.id, color="#ABCDEF")
    assert (a.id, b.id) == ("p1", "p2") and b.name == "Takes boas" and b.color == "#abcdef" and b.parent == "p1"
    assert f.create("x", parent="nao_existe").parent == ""
    assert f.create("").name == pastas.DEFAULT_NAME
    assert f.rename("p1", "Externas") and not f.rename("p1", "Externas") and not f.rename("p1", "  ")
    assert f.set_color("p1", "azul") and not f.set_color("p1", "azul")
    assert f.set_color("p1", "xyz") and f.get("p1").color == ""   # cor inválida = padrão
    assert f.path_of("p2") == ["Externas", "Takes boas"]
    assert [c.id for c in f.children("")] == ["p1", "p3", "p4"] and [c.id for c in f.children("p1")] == ["p2"]


def test_move_refuses_cycles():
    f = Folders()
    a, b, c = f.create("a"), f.create("b"), f.create("c")
    assert f.move(b.id, a.id) and f.move(c.id, b.id)
    assert not f.move(a.id, a.id) and not f.move(a.id, c.id) and not f.move(a.id, b.id)
    assert not f.move(c.id, b.id) and not f.move(c.id, "nao_existe") and not f.move("nao_existe", "")
    assert f.descendants(a.id) == [b.id, c.id] and f.ancestors(c.id) == [b.id, a.id]
    assert f.move(c.id, "") and f.get(c.id).parent == ""


def test_assign_and_delete_both_ways():
    f = Folders()
    a, b = f.create("a"), f.create("b")
    f.move(b.id, a.id)
    assert f.assign(["m1", "m2"], b.id) and f.assign(["m3"], a.id)
    assert not f.assign(["m1"], b.id) and not f.assign(["m1"], "nao_existe")
    assert f.items_in(b.id) == ["m1", "m2"] and sorted(f.items_under(a.id)) == ["m1", "m2", "m3"]
    sub = f.copy()
    assert f.delete(b.id) and f.folder_of("m1") == a.id and not f.get(b.id)   # sobe para a mãe
    assert sub.delete(b.id, to_root=True) and sub.folder_of("m1") == ""       # vai para a raiz
    assert sub.items == {"m3": a.id}
    g = Folders()
    p, q = g.create("p"), g.create("q")
    g.move(q.id, p.id)
    g.assign(["x"], p.id)
    assert g.delete(p.id) and g.get(q.id).parent == "" and g.folder_of("x") == ""   # filhas sobem
    assert not g.delete("nao_existe")
    assert g.assign(["x"], q.id) and g.assign(["x"], "") and g.items == {}


def test_json_round_trip_and_counter():
    f = Folders()
    a = f.create("a", color="verde")
    b = f.create("b", parent=a.id)
    f.assign(["m"], b.id)
    g = Folders.from_json(json.loads(json.dumps(f.to_json())))
    assert g == f and g.create("c").id == "p3"


def test_broken_json_is_tolerated():
    assert not Folders.from_json(None) and not Folders.from_json("x") and not Folders.from_json({"lista": 3})
    g = Folders.from_json({
        "lista": [{"id": "a", "nome": "A", "pai": "b", "x": 1}, {"id": "b", "nome": "B", "pai": "a"},
                  {"id": "c", "pai": "sumiu", "cor": "#12"}, {"id": "c"}, {"id": 4}, 7, {"nome": "sem id"},
                  {"id": "d", "pai": "d"}],
        "midia": {"m1": "a", "m2": "sumiu", "": "a", "m3": 5}, "extra": 1})
    assert [f.id for f in g.folders.values()] == ["a", "b", "c", "d"]
    assert not (g.get("a").parent == "b" and g.get("b").parent == "a")   # o ciclo a<->b foi desfeito
    assert g.get("c").parent == "" and g.get("c").color == "" and g.get("c").name == pastas.DEFAULT_NAME
    assert g.get("d").parent == "" and g.items == {"m1": "a"}
    assert set(g.to_json()) == {"lista", "midia"}
    for f in g.folders.values():
        assert f.id not in g.ancestors(f.id)


def test_keep_and_rename_items():
    f = Folders()
    p = f.create("p")
    f.assign(["a", "b"], p.id)
    f.rename_item("a", "z")
    f.keep_items(["z"])
    assert f.items == {"z": p.id}


# ------------------------------------------------------------------ sequência
def _seq_with_unused(*paths):
    seq = tl.Sequence.for_source(_src("C:/v/a.mp4"))
    for p in paths:
        seq.sources[p] = _src(p)
    return seq


def test_no_folder_same_json_as_before():
    seq = _seq_with_unused("C:/v/solto.mp4")
    d = seq.to_json()
    assert "pastas" not in d and d["formato"] == tl.FORMAT_BASE and not seq.features()
    assert [s["caminho"] for s in d["fontes"]] == ["C:/v/a.mp4"]   # a fonte solta não volta (como sempre)


def test_folders_write_format_5_only_when_used():
    seq = tl.Sequence.for_source(_src())
    assert seq.block_format() == tl.FORMAT_BASE
    seq.folders.create("A")
    assert seq.features() == {"pastas"} and seq.block_format() == tl.FORMAT
    p = project.Project(media_path="C:/v/a.mp4", sequence=seq.to_json(), mode="edicao")
    d = p.to_json()
    assert d["formato"] == project.FORMAT == 5 and d["recursos"] == ["pastas"]


def test_older_reader_refuses_a_project_with_folders(tmp_path, monkeypatch):
    seq = tl.Sequence.for_source(_src())
    seq.folders.create("A")
    p = project.Project(media_path="C:/v/a.mp4", sequence=seq.to_json(), mode="edicao")
    project.save(p, str(tmp_path / "novo.plc"))
    monkeypatch.setattr(project, "FORMAT", 4)
    with pytest.raises(project.ProjectError):
        project.load(str(tmp_path / "novo.plc"))


def test_folders_do_not_touch_triviality_or_layers():
    seq = tl.Sequence.for_source(_src())
    layers = [seq.layers_at(t) for t in (0, 10)]
    triv = seq.is_trivial()
    assert triv
    f = seq.folders.create("A")
    seq.folders.assign(["C:/v/a.mp4"], f.id)
    assert seq.is_trivial() == triv and [seq.layers_at(t) for t in (0, 10)] == layers
    assert tl.Sequence.from_json(seq.to_json()).is_trivial() == triv


def test_unused_source_in_folder_comes_back():
    seq = _seq_with_unused("C:/v/solto.mp4", "C:/v/outro.mp4")
    f = seq.folders.create("Sobras")
    seq.folders.assign(["C:/v/solto.mp4", "C:/v/a.mp4"], f.id)
    d = seq.to_json()
    assert [s["caminho"] for s in d["fontes"]] == ["C:/v/a.mp4"]
    assert [s["caminho"] for s in d["pastas"]["fontes"]] == ["C:/v/solto.mp4"]
    back = tl.Sequence.from_json(json.loads(json.dumps(d)))
    assert "C:/v/solto.mp4" in back.sources and "C:/v/outro.mp4" not in back.sources
    assert back.folders.folder_of("C:/v/solto.mp4") == f.id and back.folders.folder_of("C:/v/a.mp4") == f.id
    assert {c.src for c in back.clips} == {"C:/v/a.mp4"}   # a fonte solta não vira clipe
    assert back.used_sources()[0].path == "C:/v/a.mp4" and back.to_json() == d


def test_item_without_a_source_is_dropped():
    seq = tl.Sequence.for_source(_src())
    f = seq.folders.create("A")
    seq.folders.items["C:/v/fantasma.mp4"] = f.id
    d = seq.to_json()
    assert d["pastas"]["midia"] == {}
    d["pastas"]["midia"]["C:/v/fantasma.mp4"] = f.id
    assert tl.Sequence.from_json(d).folders.items == {}


def test_project_save_load_with_relative_path(tmp_path):
    """O arquivo importado, numa pasta e sem clipe, volta ao reabrir, até com a pasta do projeto movida."""
    a = tmp_path / "um"
    (a / "midia").mkdir(parents=True)
    used, loose = str(a / "midia" / "usado.mp4"), str(a / "midia" / "solto.mp4")
    for p in (used, loose):
        open(p, "wb").close()
    seq = tl.Sequence.for_source(_src(used))
    seq.sources[loose] = _src(loose)
    f = seq.folders.create("Entrada")
    seq.folders.assign([loose], f.id)
    pr = project.Project(media_path=used, sequence=seq.to_json(), mode="edicao")
    project.save(pr, str(a / "p.plc"))
    raw = json.loads((a / "p.plc").read_text(encoding="utf-8"))
    assert raw["edicao"]["pastas"]["fontes"][0]["relativo"] == os.path.join("midia", "solto.mp4")
    same = tl.Sequence.from_json(project.load(str(a / "p.plc")).sequence)
    assert loose in same.sources and same.folders.folder_of(loose) == f.id
    b = tmp_path / "dois"
    os.rename(a, b)
    moved = tl.Sequence.from_json(project.load(str(b / "p.plc")).sequence)
    new = os.path.normpath(str(b / "midia" / "solto.mp4"))
    assert new in moved.sources and moved.folders.folder_of(new) == f.id and loose not in moved.sources


def test_relink_moves_the_folder_item():
    seq = _seq_with_unused("C:/v/solto.mp4")
    f = seq.folders.create("A")
    seq.folders.assign(["C:/v/solto.mp4"], f.id)
    seq.relink("C:/v/solto.mp4", "D:/novo/solto.mp4")
    assert seq.folders.items == {"D:/novo/solto.mp4": f.id}


# ------------------------------------------------------------------ modelo da interface (desfazer)
def test_model_operations_are_undoable():
    seq = tl.Sequence.for_source(_src())
    m = TimelineModel(seq)
    kinds = []
    m.changed.connect(kinds.append)
    loose = _src("C:/v/solto.mp4")
    a = m.folder_create("A")
    b = m.folder_create("B", parent=a)
    assert m.folder_rename(b, "B2") and m.folder_color(b, "rosa") and m.folder_move(b, "")
    assert not m.folder_move(a, a)
    assert m.media_to_folder(["C:/v/solto.mp4", "C:/v/a.mp4"], a, {"C:/v/solto.mp4": loose})
    assert kinds == ["pastas"] * 6
    assert m.seq.folders.folder_of("C:/v/solto.mp4") == a
    m.undo()
    assert m.seq.folders.folder_of("C:/v/a.mp4") == "" and kinds[-1] == "pastas"
    m.redo()
    assert m.seq.folders.folder_of("C:/v/solto.mp4") == a and "C:/v/solto.mp4" in m.seq.sources
    assert m.folder_delete(a) and m.seq.folders.items == {}
    m.undo()
    assert m.seq.folders.folder_of("C:/v/solto.mp4") == a
    for _ in range(10):
        m.undo()
    assert not m.seq.folders.has_folders() and kinds[-1] == "pastas"
    m.redo()
    m.redo()
    assert [f.name for f in m.seq.folders.folders.values()] == ["A", "B"]


def test_forget_media_and_delete_to_root_in_model():
    m = TimelineModel(tl.Sequence.for_source(_src()))
    a = m.folder_create("A")
    m.media_to_folder(["C:/v/a.mp4"], a)
    m.media_forget("C:/v/nada.mp4")
    n = len(m.history._states)
    m.media_forget("C:/v/a.mp4")
    assert len(m.history._states) == n + 1 and m.seq.folders.items == {}
    b = m.folder_create("B", parent=a)
    m.media_to_folder(["C:/v/a.mp4"], b)
    assert m.folder_delete(a, to_root=True) and m.seq.folders.get(b).parent == ""


def test_folder_with_media_is_one_step():
    m = TimelineModel(tl.Sequence.for_source(_src()))
    n = len(m.history._states)
    s1, s2 = _src("C:/v/1.mp4"), _src("C:/v/2.mp4")
    fid = m.folder_with_media("Takes", "", ["C:/v/1.mp4", "C:/v/2.mp4"], {s1.path: s1, s2.path: s2})
    assert len(m.history._states) == n + 1 and m.seq.folders.items_in(fid) == ["C:/v/1.mp4", "C:/v/2.mp4"]
    m.undo()
    assert not m.seq.folders.has_folders()
