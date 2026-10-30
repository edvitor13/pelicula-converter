"""Várias sequências num projeto e sequência dentro de sequência (#57): `timeline.SequenceSet` e o JSON. Sem GPU."""

from __future__ import annotations

import json

import pytest

from pelicula import project, timeline as tl


def _src(path="C:/v/a.mp4", frames=48, **kw):
    kw.setdefault("has_audio", True)
    return tl.Source(path, 320, 180, 24.0, "24/1", frames, frames / 24.0, pix_fmt="yuv420p", **kw)


def _pair(frames=48):
    """Duas sequências no mesmo projeto: `a` com um arquivo; `b` vazia."""
    a = tl.Sequence(width=320, height=180, micro_fade=True)
    a.insert_media(_src(frames=frames), 0)
    b = a.ensure_set().create(320, 180, "24/1")
    return a, b


def _nested_source(outer, inner):
    return outer.sources[f"sequencia:{inner.id}"]


# ------------------------------------------------------------------ sozinha: tudo como antes
def test_a_lone_sequence_writes_the_same_json_as_before():
    seq = tl.Sequence(width=320, height=180)
    seq.insert_media(_src(), 0)
    d = seq.to_json()
    assert not {"id", "sequencias", "sequencia_pos"} & set(d)
    assert seq.family() == [seq] and seq.siblings is None and seq.block_format() == tl.FORMAT_BASE
    assert tl.Sequence.from_json(d).siblings is None
    seq.ensure_set()  # o conjunto de uma só não muda nada
    assert seq.to_json() == d and not any(s.is_nested for s in seq.sources.values())


def test_a_name_left_empty_shows_as_sequence_1_and_keeps_empty_in_the_json():
    seq = tl.Sequence()
    assert seq.name == "" and seq.display_name == "Sequência 1" and seq.to_json()["nome"] == ""


# ------------------------------------------------------------------ o conjunto
def test_new_sequence_gets_a_free_name_and_shares_the_media():
    a, b = _pair()
    assert b.display_name == "Sequência 2" and a.family() == [a, b] == b.family()
    assert a.sources is b.sources and a.folders is b.folders
    assert b.micro_fade and a.id and b.id and a.id != b.id
    c = a.siblings.create(1920, 1080, "25/1")
    assert c.display_name == "Sequência 3" and (c.width, c.height, c.fps_str) == (1920, 1080, "25/1")


def test_the_source_of_a_sequence_follows_it():
    a, b = _pair()
    src = _nested_source(a, b)
    assert src.is_nested and not src.is_generated and not src.is_file and not src.is_sequence
    assert src.nested_id == b.id and src.name == "Sequência 2" and src.frames == 1 and not src.has_audio
    b.insert_media(_src(frames=96), 0)
    b.name = "Abertura"
    a.siblings.sync()
    assert src is _nested_source(a, b) and (src.frames, src.name) == (96, "Abertura") and src.has_audio
    assert a.nested(src) is b and a.nested(_src()) is None


def test_duplicate_keeps_the_clip_ids_and_goes_right_after():
    a, b = _pair()
    dup = a.siblings.duplicate(a)
    assert a.family() == [a, dup, b] and dup.display_name == "Sequência 1 (cópia)"
    assert {c.id for c in dup.clips} == {c.id for c in a.clips} and dup.id != a.id
    dup.clips[0].start = 10
    assert all(c.start == 0 for c in a.clips)  # cópia de verdade


def test_remove_takes_the_clips_of_it_in_the_others():
    a, b = _pair()
    made = a.insert_media(_nested_source(a, b), 48)
    assert a.siblings.remove(b) == len(made) and a.family() == [a]
    assert all(c.id not in {m.id for m in made} for c in a.clips)
    assert not any(s.is_nested for s in a.sources.values())
    assert a.siblings.remove(a) == -1  # a última fica
    assert "sequencias" not in a.to_json() and "id" not in a.to_json()  # voltou a ser o projeto de sempre


def test_move_changes_the_tab():
    a, b = _pair()
    c = a.siblings.create(320, 180, "24/1")
    a.siblings.move(c, 0)
    assert a.family() == [c, a, b]
    assert [s.id for s in tl.Sequence.from_json(a.to_json()).family()] == [c.id, a.id, b.id]


# ------------------------------------------------------------------ tempo do clipe de sequência
def test_a_clip_of_a_sequence_has_the_time_rules_of_a_video():
    a, b = _pair()
    b.insert_media(_src("C:/v/b.mp4", frames=96), 0)
    a.siblings.sync()
    made = a.insert_media(_nested_source(a, b), 48)
    assert [c.kind for c in made] == [tl.VIDEO, tl.AUDIO] and made[0].dur == 96 and made[0].link == made[1].link
    v = made[0]
    assert a.src_frame(v, 48) == 0 and a.src_frame(v, 60) == 12
    a.set_speed(v.id, 2.0)
    assert a.src_frame(v, 49) == 2 and v.dur == 48
    assert a.nested(v) is b


def test_a_different_fps_inside_follows_the_rule_of_video_clips():
    a = tl.Sequence(width=320, height=180, fps_str="24/1")
    b = a.ensure_set().create(320, 180, "48/1")
    b.insert_media(_src(frames=240), 0)  # 10 s de um arquivo de 24 fps: 480 quadros da sequência de 48 fps
    a.siblings.sync()
    src = _nested_source(a, b)
    assert src.fps == 48.0 and src.frames == 480
    v = a.insert_media(src, 0)[0]
    assert v.dur == 240  # os mesmos 10 s nos quadros da sequência de fora
    assert a.src_frame(v, 24) == 48  # 1 s depois: o quadro de 1 s da interna


def test_a_shorter_sequence_holds_its_last_frame_like_a_shorter_file():
    a, b = _pair()
    made = b.insert_media(_src("C:/v/b.mp4", frames=96), 0)
    a.siblings.sync()
    v = a.insert_media(_nested_source(a, b), 48)[0]
    b.trim_end(made[0].id, 24)
    a.siblings.sync()
    assert v.dur == 96 and a.src_frame(v, 48 + 90) == 23


def test_a_sequence_only_with_sound_makes_only_an_audio_clip():
    a, b = _pair()
    b.insert_media(tl.Source("C:/v/m.wav", fps=24.0, frames=48, duration=2.0, has_video=False, has_audio=True), 0)
    a.siblings.sync()
    made = a.insert_media(_nested_source(a, b), 48)
    assert [c.kind for c in made] == [tl.AUDIO]


def test_deep_sources_cross_every_level():
    a, b = _pair()
    c = a.siblings.create(320, 180, "24/1")
    c.insert_media(_src("C:/v/c.mp4"), 0)
    a.siblings.sync()
    b.insert_media(_nested_source(a, c), 0)
    a.siblings.sync()
    a.insert_media(_nested_source(a, b), 48)
    assert a.closure() == [a, b, c]
    assert {s.path for s in a.deep_sources()} == {"C:/v/a.mp4", "C:/v/c.mp4"}


# ------------------------------------------------------------------ sem ciclos
def test_a_sequence_cannot_contain_itself_even_indirectly():
    a, b = _pair()
    c = a.siblings.create(320, 180, "24/1")
    assert not a.can_contain(_nested_source(a, a)) and a.insert_media(_nested_source(a, a), 0) == []
    assert a.insert_media(_nested_source(a, b), 48)  # a → b
    assert b.insert_media(_nested_source(a, c), 0)   # b → c
    before = json.dumps(c.to_json(), sort_keys=True)
    assert not b.can_contain(_nested_source(a, a))   # fecharia a → b → a
    assert c.insert_media(_nested_source(a, a), 0) == []  # fecharia a → b → c → a
    assert json.dumps(c.to_json(), sort_keys=True) == before


def test_nesting_stops_at_the_level_limit():
    a = tl.Sequence(width=320, height=180)
    chain = [a]
    for _i in range(tl.MAX_NEST - 1):
        chain.append(a.ensure_set().create(320, 180, "24/1"))
    for outer, inner in zip(chain, chain[1:]):
        assert outer.insert_media(_nested_source(a, inner), 0)
    extra = a.siblings.create(320, 180, "24/1")
    assert not chain[-1].can_contain(_nested_source(a, extra))
    assert a.siblings.allows(extra, chain[-1])  # a última da cadeia ainda cabe numa sequência solta
    assert not extra.can_contain(_nested_source(a, a))  # a cadeia inteira não


def test_opening_a_file_with_a_cycle_takes_the_clip_out_and_warns():
    a, b = _pair()
    assert a.insert_media(_nested_source(a, b), 48)
    d = a.to_json()
    # O arquivo mexido à mão: b → a, fechando o ciclo.
    other = d["sequencias"][0]
    other["fontes"].append(_nested_source(a, a).to_json())
    other["clipes"].append(tl.Clip("x", tl.VIDEO, f"sequencia:{a.id}", 0, 0, 10).to_json())
    opened = tl.Sequence.from_json(d)
    inner = opened.family()[1]
    assert not any(c.id == "x" for c in inner.clips)
    assert any(opened.nested(c) is inner for c in opened.clips)  # o clipe que não fecha nada fica
    assert len(opened.siblings.problems) == 1 and "Sequência 2" in opened.siblings.problems[0]


def test_opening_a_file_with_a_sequence_that_is_gone_takes_the_clip_out():
    a, b = _pair()
    a.insert_media(_nested_source(a, b), 48)
    d = a.to_json()
    d["sequencias"] = [{**d["sequencias"][0], "id": "outro"}]
    opened = tl.Sequence.from_json(d)
    assert not any(c.src.startswith("sequencia:") for c in opened.clips) and opened.siblings.problems


# ------------------------------------------------------------------ JSON e formato
def test_json_round_trip_keeps_order_active_media_and_folders():
    a, b = _pair()
    a.insert_media(_nested_source(a, b), 48)
    b.markers.append(tl.Marker("m1", 3))
    pid = a.folders.create("Cenas").id
    a.folders.assign([f"sequencia:{b.id}"], pid)
    d = json.loads(json.dumps(b.to_json()))
    assert d["id"] == b.id and d["sequencia_pos"] == 1 and [x["id"] for x in d["sequencias"]] == [a.id]
    assert "pastas" in d and "pastas" not in d["sequencias"][0]
    opened = tl.Sequence.from_json(d)
    assert opened.id == b.id and [s.id for s in opened.family()] == [a.id, b.id]
    x, y = opened.family()
    assert x.sources is y.sources and x.folders is y.folders and y is opened
    assert opened.folders.folder_of(f"sequencia:{b.id}") == pid and [m.id for m in y.markers] == ["m1"]
    assert x.nested(next(c for c in x.clips if c.src.startswith("sequencia:"))) is y
    assert json.dumps(opened.to_json(), sort_keys=True) == json.dumps(d, sort_keys=True)


def test_copy_keeps_the_sisters_and_is_independent():
    a, b = _pair()
    a.insert_media(_nested_source(a, b), 48)
    dup = a.copy()
    assert [s.id for s in dup.family()] == [a.id, b.id] and dup.id == a.id
    inner = dup.family()[1]
    assert inner is not b and inner.sources is dup.sources and inner.sources is not a.sources
    inner.name = "mudou"
    assert b.name != "mudou"


def test_several_sequences_go_to_the_1_7_format():
    a, b = _pair()
    d = a.to_json()
    assert d["formato"] == tl.FORMAT and "varias_sequencias" in a.features()
    assert "sequencia_aninhada" not in a.features()
    a.insert_media(_nested_source(a, b), 48)
    assert "sequencia_aninhada" in a.features() and "gerador" not in a.features()
    p = project.Project(sequence=a.to_json())
    assert p.to_json()["formato"] == project.FORMAT and {"varias_sequencias", "sequencia_aninhada"} <= set(p.features())


def test_a_feature_of_a_sister_also_sets_the_format():
    a, b = _pair()
    a.siblings.remove(b)
    assert a.block_format() == tl.FORMAT_BASE
    b = a.siblings.create(320, 180, "24/1")
    b.window = 2.39
    assert "janela_util" in a.features()


def test_a_newer_block_in_a_sister_is_refused():
    a, b = _pair()
    d = a.to_json()
    d["sequencias"][0]["formato"] = tl.FORMAT + 1
    with pytest.raises(tl.FormatError):
        tl.Sequence.from_json(d)


def test_broken_blocks_are_tolerated():
    a, b = _pair()
    d = a.to_json()
    d["sequencias"] = ["x", 3, {**d["sequencias"][0], "fontes": None, "clipes": "y"}]
    d["sequencia_pos"] = "z"
    opened = tl.Sequence.from_json(d)
    assert len(opened.family()) == 2 and opened.family()[0] is opened
    d["sequencias"] = "quebrado"
    assert tl.Sequence.from_json(d).siblings is None


def test_relink_reaches_every_sequence():
    a, b = _pair()
    made = b.insert_media(a.sources["C:/v/a.mp4"], 0)
    a.relink("C:/v/a.mp4", "D:/novo/a.mp4")
    assert a.clips[0].src == "D:/novo/a.mp4" == made[0].src and "C:/v/a.mp4" not in b.sources
    assert b.sources["D:/novo/a.mp4"].path == "D:/novo/a.mp4"


def test_project_saves_relative_paths_of_every_sequence_and_finds_them_again(tmp_path):
    (tmp_path / "midia").mkdir()
    (tmp_path / "midia" / "a.mp4").write_bytes(b"x")
    (tmp_path / "midia" / "c.mp4").write_bytes(b"x")
    a = tl.Sequence(width=320, height=180)
    a.insert_media(_src(str(tmp_path / "midia" / "a.mp4")), 0)
    b = a.ensure_set().create(320, 180, "24/1")
    b.insert_media(_src(str(tmp_path / "midia" / "c.mp4")), 0)
    path = tmp_path / "p.plc"
    project.save(project.Project(sequence=a.to_json(), mode="edicao"), str(path))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["edicao"]["sequencias"][0]["fontes"][0]["relativo"].replace("\\", "/") == "midia/c.mp4"
    # Pasta do projeto movida: os dois arquivos são achados pelo caminho relativo.
    moved = tmp_path / "outro"
    (tmp_path / "midia").rename(tmp_path / "guardado")
    moved.mkdir()
    (tmp_path / "guardado").rename(moved / "midia")
    (moved / "p.plc").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    opened = tl.Sequence.from_json(project.load(str(moved / "p.plc")).sequence)
    first, second = opened.family()
    assert first.clips[0].src == str(moved / "midia" / "a.mp4") and second.clips[0].src == str(moved / "midia" / "c.mp4")


def test_a_trivial_sequence_with_a_sister_is_still_trivial():
    a, _b = _pair()
    a.clips = [c for c in a.clips if c.kind == tl.VIDEO]
    a.sources["C:/v/a.mp4"].has_audio = False
    assert a.is_trivial() == "C:/v/a.mp4" and a.direct_file() == "C:/v/a.mp4"


def test_a_nested_clip_is_not_trivial_and_not_a_generator():
    a, b = _pair()
    a.clips.clear()
    a.insert_media(_nested_source(a, b), 0)
    assert a.is_trivial() is None
    from pelicula import modules
    assert "titulos_geradores" not in modules.used_by({}, a)


# ------------------------------------------------------------------ desfazer
def test_switching_tabs_is_not_a_step():
    a, b = _pair()
    h = tl.History(a)
    assert not h.push(b) and not h.can_undo()


def test_undo_goes_back_to_the_sequence_where_the_change_was():
    a, b = _pair()
    h = tl.History(a)
    b.insert_media(_src("C:/v/b.mp4"), 0)
    assert h.push(b) and h.can_undo()
    back = h.undo()  # estando em qualquer aba, desfaz na `b`
    assert back.id == b.id and not back.clips and len(back.family()) == 2
    ahead = h.redo()
    assert ahead.id == b.id and ahead.clips


def test_undo_of_a_new_sequence_falls_back_to_the_one_that_was_open():
    a = tl.Sequence(width=320, height=180)
    a.insert_media(_src(), 0)
    b = a.ensure_set().create(320, 180, "24/1")
    h = tl.History(a)
    c = a.siblings.create(320, 180, "24/1")
    assert h.push(c)
    back = h.undo()
    assert back.id == a.id and [s.id for s in back.family()] == [a.id, b.id]


def test_undo_covers_a_change_in_two_sequences_in_one_step():
    a, b = _pair()
    h = tl.History(a)
    b.insert_media(a.sources["C:/v/a.mp4"], 0)
    a.clips.clear()
    a.insert_media(_nested_source(a, b), 0)
    assert h.push(a)
    back = h.undo()
    assert back.id == a.id and not back.nested_children() and not back.family()[1].clips
    assert not h.can_undo()


def test_history_of_a_lone_sequence_is_as_before():
    seq = tl.Sequence(width=320, height=180)
    h = tl.History(seq)
    seq.insert_media(_src(), 0)
    assert h.push(seq)
    back = h.undo()
    assert not back.clips and back.siblings is None and not h.can_undo()
