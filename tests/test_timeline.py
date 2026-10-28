"""Linha do tempo do modo Edição (timeline.py): montagem, tempo, transições, JSON e desfazer."""

from __future__ import annotations

import json
import math

import pytest

from pelicula import editparams
from pelicula import timeline as tl


def src(path="a.mp4", w=1920, h=1080, fps=24.0, frames=240, audio=True, image=False, fps_str=None):
    return tl.Source(path, w, h, fps, fps_str or f"{int(fps)}/1", frames, frames / fps, is_image=image,
                     has_audio=audio)


def video(seq):
    return sorted((c for c in seq.clips if c.kind == tl.VIDEO), key=lambda c: (c.track, c.start))


def audio(seq):
    return sorted((c for c in seq.clips if c.kind == tl.AUDIO), key=lambda c: (c.track, c.start))


def spans(clips):
    return [(c.start, c.end) for c in clips]


# ------------------------------------------------------------------ origem
def test_source_length_and_json_roundtrip():
    s = src(frames=48, fps=24.0)
    assert s.length == pytest.approx(2.0)
    assert tl.Source("x.png", 10, 10, is_image=True).length == tl.MAX_HOLD_SECONDS
    only = tl.Source("m.mp3", has_video=False, has_audio=True, duration=12.5)
    assert only.length == pytest.approx(12.5)
    again = tl.Source.from_json(json.loads(json.dumps(s.to_json())))
    assert again == s


def test_source_from_bad_json_is_sane():
    s = tl.Source.from_json({"caminho": "x.mp4", "fps": "abc", "quadros": "muitos", "largura": -5})
    assert s.fps == 24.0 and s.frames == 1 and s.width == 0


def test_source_to_info(make_info):
    info = make_info(path="v.mov", fps=25.0, fps_str="25/1", frames=100)
    s = tl.Source.from_info(info)
    back = s.to_info()
    assert (back.path, back.fps, back.frames, back.width, back.has_audio) == ("v.mov", 25.0, 100, 1920, True)


# ------------------------------------------------------------------ montagem
def test_for_source_creates_linked_video_and_audio():
    seq = tl.Sequence.for_source(src())
    v, a = video(seq), audio(seq)
    assert len(v) == len(a) == 1
    assert v[0].link and v[0].link == a[0].link
    assert (seq.width, seq.height, seq.fps_str, seq.duration) == (1920, 1080, "24/1", 240)
    assert seq.is_trivial() == "a.mp4"


def test_image_and_audio_only_sources():
    seq = tl.Sequence()
    seq.insert_media(tl.Source("foto.png", 800, 600, is_image=True, has_audio=False))
    seq.insert_media(tl.Source("musica.mp3", has_video=False, has_audio=True, duration=3.0), at=0)
    v, a = video(seq), audio(seq)
    assert v[0].dur == int(tl.IMAGE_SECONDS * 24) and not v[0].link
    assert a[0].dur == 72 and not a[0].link
    assert seq.src_frame(v[0], 50) == 0


def test_insert_appends_at_end_of_track():
    seq = tl.Sequence.for_source(src(frames=48))
    seq.insert_media(src("b.mp4", frames=24))
    assert spans(video(seq)) == [(0, 48), (48, 72)]
    assert spans(audio(seq)) == [(0, 48), (48, 72)]
    assert seq.is_trivial() is None


def test_is_trivial_rules():
    s = src()
    seq = tl.Sequence.for_source(s)
    assert seq.is_trivial() == s.path
    seq.width = 1280
    assert seq.is_trivial() is None
    seq = tl.Sequence.for_source(s)
    a = audio(seq)[0]
    seq.set_values(a.id, {**a.values, "volume": -3.0})
    assert seq.is_trivial() is None
    seq = tl.Sequence.for_source(s)
    seq.kind_tracks(tl.AUDIO)[0].muted = True
    assert seq.is_trivial() is None
    assert tl.Sequence().is_trivial() is None


# ------------------------------------------------------------------ tempo
def test_src_frame_mapping_with_speed_freeze_and_fps():
    seq = tl.Sequence(fps_str="24/1")
    s30 = src("b.mp4", fps=30.0, frames=300, audio=False)
    (c,) = seq.insert_media(s30)
    assert [seq.src_frame(c, t) for t in (0, 1, 23, 24)] == [0, 1, 28, 30]
    seq.set_speed(c.id, 2.0)
    assert seq.src_frame(c, 24) == 60
    assert c.dur == 120  # 10 s do arquivo a 2× = 5 s
    v = dict(c.values, congelar=True)
    seq.set_values(c.id, v)
    assert {seq.src_frame(c, t) for t in range(0, 100, 7)} == {0}
    # nunca passa do último quadro do arquivo
    seq.set_values(c.id, dict(v, congelar=False))
    assert seq.src_frame(c, 10_000) == 299


def test_frame_mapping_is_exact_for_integer_frames():
    seq = tl.Sequence(fps_str="30000/1001")
    s = src("ntsc.mp4", fps=30000 / 1001, fps_str="30000/1001", frames=1000, audio=False)
    (c,) = seq.insert_media(s)
    assert [seq.src_frame(c, t) for t in range(0, 1000, 37)] == list(range(0, 1000, 37))


# ------------------------------------------------------------------ edição
def test_split_keeps_sync_and_moves_transitions():
    seq = tl.Sequence.for_source(src())
    v = video(seq)[0]
    seq.set_values(v.id, {**v.values, "entrada_tipo": "preto", "saida_tipo": "branco"})
    made = seq.split(100)
    assert len(made) == 2
    vl, vr = video(seq)
    al, ar = audio(seq)
    assert spans([vl, vr]) == spans([al, ar]) == [(0, 100), (100, 240)]
    assert vr.src_in == pytest.approx(100 / 24) == ar.src_in
    assert vl.link == al.link and vr.link == ar.link and vl.link != vr.link
    assert vl.values["entrada_tipo"] == "preto" and vl.values["saida_tipo"] == "corte"
    assert vr.values["entrada_tipo"] == "corte" and vr.values["saida_tipo"] == "branco"
    assert seq.src_frame(vr, 150) == 150  # o tempo do arquivo não muda com o corte


def test_split_only_selected_and_outside_does_nothing():
    seq = tl.Sequence.for_source(src())
    seq.insert_media(src("b.mp4", audio=False), at=0, vtrack=1)
    top = [c for c in video(seq) if c.track == 1][0]
    assert seq.split(50, [top.id]) and len(seq.clips) == 4
    assert seq.split(0) == [] and seq.split(240) == []


def test_trim_start_and_end_are_limited_by_the_file():
    seq = tl.Sequence.for_source(src(frames=100))
    v = video(seq)[0]
    assert seq.trim_start(v.id, 30) == 30
    assert (v.start, v.dur, v.src_in) == (30, 70, pytest.approx(30 / 24))
    a = audio(seq)[0]
    assert (a.start, a.dur) == (30, 70)  # o som ligado acompanha
    assert seq.trim_start(v.id, 0) == -30  # volta até o começo do arquivo, não além
    assert v.src_in == pytest.approx(0.0)
    assert seq.trim_end(v.id, 500) == 0  # o arquivo acaba no quadro 100
    assert seq.trim_end(v.id, 60) == -40 and v.dur == 60
    assert seq.trim_end(v.id, -10) == -59 and v.dur == 1


def test_image_can_be_stretched():
    seq = tl.Sequence()
    (c,) = seq.insert_media(tl.Source("f.png", 100, 100, is_image=True))
    assert seq.trim_end(c.id, 10_000) > 0 and c.dur == 10_000


def test_move_overwrites_what_is_under_it():
    seq = tl.Sequence()
    a, = seq.insert_media(src("a.mp4", audio=False, frames=100))
    b, = seq.insert_media(src("b.mp4", audio=False, frames=20))
    assert spans(video(seq)) == [(0, 100), (100, 120)]
    seq.move(b.id, 40)  # cai no meio de "a": divide "a" em duas partes
    vs = video(seq)
    assert spans(vs) == [(0, 40), (40, 60), (60, 100)]
    right = vs[2]
    assert right.src == "a.mp4" and right.src_in == pytest.approx(60 / 24)
    seq.move(b.id, -50)  # não vai para antes do zero
    assert b.start == 0


def test_move_linked_group_and_change_track():
    seq = tl.Sequence.for_source(src(frames=48))
    v, a = video(seq)[0], audio(seq)[0]
    seq.move(v.id, 10, new_track=2)
    assert (v.start, v.track) == (10, 2) and (a.start, a.track) == (10, 0)
    assert len(seq.kind_tracks(tl.VIDEO)) == 3


def test_locked_track_is_not_touched():
    seq = tl.Sequence.for_source(src(frames=48))
    seq.kind_tracks(tl.VIDEO)[0].locked = True
    v, a = video(seq)[0], audio(seq)[0]
    assert seq.move(v.id, 20) == 0  # arrastar o clipe travado não mexe em nada
    assert a.start == 0
    seq.move(a.id, 20)
    assert v.start == 0 and a.start == 20  # só o que não está travado anda
    seq.delete([v.id])
    assert v in seq.clips


def test_delete_with_and_without_ripple():
    seq = tl.Sequence()
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        seq.insert_media(src(name, frames=24))
    b = [c for c in video(seq) if c.src == "b.mp4"][0]
    seq.copy().delete([b.id])
    gap = seq.copy()
    gap.delete([[c for c in video(gap) if c.src == "b.mp4"][0].id])
    assert spans(video(gap)) == [(0, 24), (48, 72)] and len(gap.clips) == 4
    seq.delete([b.id], ripple=True)
    assert spans(video(seq)) == [(0, 24), (24, 48)] and spans(audio(seq)) == [(0, 24), (24, 48)]


def test_set_speed_does_not_invade_next_clip():
    seq = tl.Sequence()
    a, = seq.insert_media(src("a.mp4", audio=False, frames=48))
    seq.insert_media(src("b.mp4", audio=False, frames=48))
    seq.set_speed(a.id, 0.5)  # ficaria com 96 quadros, mas o próximo clipe começa no 48
    assert a.dur == 48 and a.speed == 0.5
    seq.set_speed(a.id, 4.0)  # o trecho do arquivo (1 s) fica igual: 1 s a 4× = 6 quadros
    assert a.dur == 6


def test_link_unlink_and_close_gaps():
    seq = tl.Sequence.for_source(src(frames=24))
    v, a = video(seq)[0], audio(seq)[0]
    seq.unlink(v.id)
    seq.move(v.id, 30)
    assert a.start == 0
    seq.link([v.id, a.id])
    assert v.link == a.link != ""
    seq.unlink(v.id)
    seq.close_gaps(tl.VIDEO, 0)
    assert v.start == 0


def test_tracks_add_remove():
    seq = tl.Sequence.for_source(src(frames=24))
    assert seq.add_track(tl.VIDEO) == 1
    seq.insert_media(src("b.mp4", audio=False), at=0, vtrack=1)
    seq.remove_track(tl.VIDEO, 0)
    assert [c.track for c in video(seq)] == [0] and video(seq)[0].src == "b.mp4"
    assert [t.name for t in seq.kind_tracks(tl.VIDEO)] == ["V1"]
    seq.remove_track(tl.VIDEO, 0)  # sempre sobra uma faixa
    assert len(seq.kind_tracks(tl.VIDEO)) == 1


# ------------------------------------------------------------------ camadas e transições
def test_layers_order_bottom_to_top_and_hidden_track():
    seq = tl.Sequence.for_source(src(frames=48, audio=False))
    seq.insert_media(src("b.mp4", frames=48, audio=False), at=0, vtrack=1)
    assert [l.clip.src for l in seq.layers_at(10)] == ["a.mp4", "b.mp4"]
    seq.kind_tracks(tl.VIDEO)[1].muted = True
    assert [l.clip.src for l in seq.layers_at(10)] == ["a.mp4"]
    assert seq.layers_at(48) == []


def test_fade_from_black_and_to_white():
    seq = tl.Sequence.for_source(src(frames=48, audio=False))
    c = video(seq)[0]
    seq.set_values(c.id, {**c.values, "entrada_tipo": "preto", "entrada_dur": 0.5,
                          "saida_tipo": "branco", "saida_dur": 0.5})
    fades = [seq.layers_at(t)[0].fade for t in range(12)]
    assert all(a > b for a, b in zip(fades, fades[1:])) and 0 < fades[-1] < fades[0] < 1
    assert seq.layers_at(12)[0].fade == 0.0
    last = seq.layers_at(47)[0]
    assert last.fade_color == (1.0, 1.0, 1.0) and 0.9 < last.fade < 1.0


def test_dissolve_shows_previous_clip_underneath():
    seq = tl.Sequence()
    a, = seq.insert_media(src("a.mp4", audio=False, frames=100))
    seq.trim_end(a.id, 48)
    b, = seq.insert_media(src("b.mp4", audio=False, frames=100))
    seq.set_values(b.id, {**b.values, "entrada_tipo": "dissolver", "entrada_dur": 0.5})
    layers = seq.layers_at(50)
    assert [l.clip.src for l in layers] == ["a.mp4", "b.mp4"]
    assert layers[0].extension and layers[0].src_frame == 50  # a cauda continua no arquivo
    alphas = [seq.layers_at(t)[-1].alpha for t in range(48, 60)]
    assert all(x < y for x, y in zip(alphas, alphas[1:])) and alphas[-1] < 1
    assert len(seq.layers_at(60)) == 1


def test_fade_out_transparent_reveals_lower_track():
    seq = tl.Sequence.for_source(src(frames=48, audio=False))
    top, = seq.insert_media(src("b.mp4", frames=48, audio=False), at=0, vtrack=1)
    seq.set_values(top.id, {**top.values, "saida_tipo": "transparente", "saida_dur": 0.25})
    assert seq.layers_at(47)[-1].alpha < 0.3 and seq.layers_at(10)[-1].alpha == 1.0


def test_audio_clips_respect_mute_and_solo():
    seq = tl.Sequence.for_source(src(frames=24))
    seq.insert_media(tl.Source("m.mp3", has_video=False, has_audio=True, duration=1.0), at=0, atrack=1)
    assert len(seq.audio_clips()) == 2 and seq.has_audio
    seq.kind_tracks(tl.AUDIO)[1].solo = True
    assert [c.src for c in seq.audio_clips()] == ["m.mp3"]
    seq.kind_tracks(tl.AUDIO)[1].solo = False
    a = audio(seq)[0]
    seq.set_values(a.id, {**a.values, "mudo": True})
    assert [c.src for c in seq.audio_clips()] == ["m.mp3"]


# ------------------------------------------------------------------ JSON e desfazer
def test_json_roundtrip_and_sanitize():
    seq = tl.Sequence.for_source(src())
    seq.split(30)
    v = video(seq)[1]
    seq.set_values(v.id, {**v.values, "exposicao": 1.5, "roda_meios": [0.3, -0.2], "mesclagem": "tela"})
    data = json.loads(json.dumps(seq.to_json()))
    again = tl.Sequence.from_json(data)
    assert again.to_json() == seq.to_json()
    assert again.find(v.id).values["roda_meios"] == [0.3, -0.2]
    first_video = next(c for c in data["clipes"] if c["tipo"] == "video")
    first_video["valores"] = {"exposicao": 99, "inventado": 1, "roda_meios": [5, 5]}
    data["clipes"].append({"tipo": "video", "fonte": "nao_existe.mp4"})
    data["clipes"].append({"tipo": "outro"})
    bad = tl.Sequence.from_json(data)
    c0 = bad.find(first_video["id"])
    assert c0.values["exposicao"] == editparams.VIDEO.params["exposicao"].max and "inventado" not in c0.values
    assert math.hypot(*c0.values["roda_meios"]) == pytest.approx(1.0)
    assert len(bad.clips) == len(seq.clips)


@pytest.mark.parametrize("junk", [None, {}, [], {"largura": "x", "fps": None, "faixas": "nada", "fundo": "?"}])
def test_from_json_junk(junk):
    seq = tl.Sequence.from_json(junk)
    assert seq.clips == [] and seq.kind_tracks(tl.VIDEO) and seq.kind_tracks(tl.AUDIO)


def test_relink():
    seq = tl.Sequence.for_source(src("C:/velho/a.mp4"))
    seq.relink("C:/velho/a.mp4", "D:/novo/a.mp4")
    assert set(seq.sources) == {"D:/novo/a.mp4"} and all(c.src == "D:/novo/a.mp4" for c in seq.clips)


def test_history_undo_redo():
    seq = tl.Sequence.for_source(src())
    h = tl.History(seq)
    assert not h.can_undo() and not h.push(seq)
    seq.split(100)
    assert h.push(seq)
    seq.delete([video(seq)[1].id])
    h.push(seq)
    back = h.undo()
    assert len(back.clips) == 4
    back = h.undo()
    assert len(back.clips) == 2 and not h.can_undo()
    fwd = h.redo()
    assert len(fwd.clips) == 4 and h.can_redo()
    fwd.width = 1280
    h.push(fwd)  # depois de desfazer, uma edição nova apaga o "refazer"
    assert not h.can_redo()


def test_history_limit():
    seq = tl.Sequence.for_source(src())
    h = tl.History(seq, limit=5)
    for i in range(10):
        seq.width = 100 + i
        h.push(seq)
    n = 0
    while h.undo() is not None:
        n += 1
    assert n == 4


# ------------------------------------------------------------------ marcadores
def test_markers_add_update_and_navigate():
    seq = tl.Sequence.for_source(src())
    a = seq.add_marker(48, "Abertura", chapter=True)
    assert seq.add_marker(48) is a and len(seq.markers) == 1  # mesmo quadro: não duplica
    b = seq.add_marker(10, color="verde", note="cor estourada")
    c = seq.add_marker(200)
    assert [m.id for m in seq.sorted_markers()] == [b.id, a.id, c.id]
    assert [m.id for m in seq.chapters()] == [a.id]
    assert seq.next_marker(10) is a and seq.next_marker(9) is b and seq.next_marker(200) is None
    assert seq.previous_marker(48) is b and seq.previous_marker(201) is c and seq.previous_marker(10) is None
    assert seq.update_marker(c.id, name="Fim", chapter=True, color="inventada", frame=-5)
    assert (c.name, c.chapter, c.color, c.frame) == ("Fim", True, tl.MARKER_COLOR_KEYS[0], 0)
    assert not seq.update_marker(c.id, name="Fim")  # nada mudou
    assert seq.update_marker(c.id, name="x" * 5000) and len(c.name) == tl.MARKER_TEXT_MAX
    with pytest.raises(KeyError):
        seq.update_marker(c.id, inventado=1)
    assert seq.remove_marker(b.id) and not seq.remove_marker(b.id) and seq.marker(b.id) is None


def test_markers_json_is_optional_and_roundtrips():
    seq = tl.Sequence.for_source(src())
    plain = seq.to_json()
    assert "marcadores" not in plain  # montagem sem marcadores: o JSON é o de sempre
    assert tl.Sequence.from_json(plain).markers == []
    seq.add_marker(30, "Abertura", "azul", "nota", chapter=True)
    seq.add_marker(5)
    data = json.loads(json.dumps(seq.to_json()))
    assert [m["quadro"] for m in data["marcadores"]] == [5, 30]
    assert data["marcadores"][1] == {"id": seq.markers[0].id, "quadro": 30, "cor": "azul", "nome": "Abertura",
                                     "nota": "nota", "capitulo": True}
    again = tl.Sequence.from_json(data)
    assert again.to_json() == data and again.copy().to_json() == data
    # Lixo: entradas inválidas somem, ids repetidos ficam uma vez, campos estranhos viram o padrão.
    data["marcadores"] += [{"quadro": "x"}, "lixo", {"id": seq.markers[0].id, "quadro": 99},
                           {"quadro": 7.9, "cor": 3, "nome": None, "capitulo": "sim"}]
    bad = tl.Sequence.from_json(data)
    assert len(bad.markers) == 3
    odd = [m for m in bad.markers if m.frame == 7][0]
    assert (odd.color, odd.name, odd.chapter) == (tl.MARKER_COLOR_KEYS[0], "", False)
    for junk in ("nada", 5, {"a": 1}):
        assert tl.Sequence.from_json({**data, "marcadores": junk}).markers == []


def test_markers_stay_put_when_clips_change():
    seq = tl.Sequence.for_source(src())
    mk = seq.add_marker(100)
    v = video(seq)[0]
    seq.split(50)
    seq.move(video(seq)[1].id, 60)
    seq.trim_end(v.id, 40)
    seq.delete([video(seq)[0].id])
    assert mk.frame == 100


def test_ripple_delete_pulls_markers_after_the_cut():
    seq = tl.Sequence()
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        seq.insert_media(src(name, frames=24))  # 0–24, 24–48, 48–72
    before, inside, at_cut, after = (seq.add_marker(f) for f in (10, 30, 24, 60))
    b = [c for c in video(seq) if c.src == "b.mp4"][0]
    seq.delete([b.id], ripple=True)
    assert (before.frame, inside.frame, at_cut.frame, after.frame) == (10, 24, 24, 36)


def test_ripple_on_one_track_only_keeps_markers():
    seq = tl.Sequence()
    seq.insert_media(src("a.mp4", frames=24, audio=False))
    seq.insert_media(src("b.mp4", frames=24, audio=False))
    music = tl.Source("m.mp3", fps=24.0, duration=3.0, has_video=False, has_audio=True)
    seq.insert_media(music, at=0)  # som por baixo de tudo
    mk = seq.add_marker(40)
    seq.delete([video(seq)[0].id], ripple=True)
    assert spans(video(seq)) == [(0, 24)] and mk.frame == 40  # o som segura o tempo: só a faixa andou


def test_history_undoes_markers():
    seq = tl.Sequence.for_source(src())
    h = tl.History(seq)
    mk = seq.add_marker(12, "A")
    assert h.push(seq)
    seq.update_marker(mk.id, name="B")
    h.push(seq)
    assert h.undo().marker(mk.id).name == "A"
    assert h.undo().markers == []
    assert h.redo().marker(mk.id).name == "A"


# ------------------------------------------------------------------ ferramentas de corte (1.5)
def named(seq, name, kind=tl.VIDEO):
    return sorted((c for c in seq.clips if c.name == name and c.kind == kind), key=lambda c: c.start)


def layout(seq):
    """(faixa, nome, início, fim) de cada clipe, em ordem: o retrato da montagem para comparar."""
    return sorted((f"{c.kind[0]}{c.track + 1}", c.name, c.start, c.end) for c in seq.clips)


def no_overlaps(seq):
    for kind in (tl.VIDEO, tl.AUDIO):
        for i in range(len(seq.kind_tracks(kind))):
            cs = seq.clips_on(kind, i)
            for a, b in zip(cs, cs[1:]):
                assert a.end <= b.start, (kind, i, a.name, b.name)


def main_packed(seq):
    v1 = seq.clips_on(tl.VIDEO, 0)
    pos = 0
    for c in v1:
        assert c.start == pos, [(x.name, x.start, x.end) for x in v1]
        pos = c.end


def three(title=True, music=True):
    """A, B, C (100 quadros cada, com som ligado) na V1/A1; um título de 120 quadros na V2 a partir de 150 (em
    cima de B), uma música na A2 de 0 a 300 e um marcador em 250 (em cima de C)."""
    seq = tl.Sequence(1920, 1080, "24/1")
    for n in "ABC":
        seq.insert_media(src(n, frames=100))
    if title:
        seq.insert_media(tl.Source("T.png", 100, 100, is_image=True), at=150, vtrack=1)
    if music:
        seq.insert_media(tl.Source("M.mp3", has_video=False, has_audio=True, duration=300 / 24), at=0, atrack=1)
    seq.add_marker(250)
    return seq


def handles():
    """A, B, C usando o meio de arquivos de 200 quadros (sobra de 50 antes e depois de cada clipe)."""
    seq = tl.Sequence(1920, 1080, "24/1")
    for n in "ABC":
        seq.insert_media(src(n, frames=200))
    for n in "ABC":
        v = named(seq, n)[0]
        seq.trim_start(v.id, v.start + 50)
        seq.trim_end(v.id, v.start + 100)
    seq.close_gaps(tl.VIDEO, 0)
    seq.close_gaps(tl.AUDIO, 0)
    return seq


def sync(c):
    """Quadro da sequência onde estaria o começo do arquivo: igual na imagem e no som = em sincronia."""
    return round(c.start - c.src_in * 24 / c.speed, 6)


def test_insert_pushes_everything_after_the_point_and_splits_the_target_tracks():
    seq = three()
    made = seq.insert_media(src("X", frames=50), at=150, insert=True)
    assert spans(made) == [(150, 200), (150, 200)]
    assert spans(named(seq, "B")) == [(100, 150), (200, 250)]
    assert spans(named(seq, "B", tl.AUDIO)) == [(100, 150), (200, 250)]
    assert named(seq, "B")[1].src_in == pytest.approx(50 / 24)  # a parte da direita continua do mesmo ponto
    assert spans(named(seq, "C")) == spans(named(seq, "C", tl.AUDIO)) == [(250, 350)]
    assert spans(named(seq, "T.png")) == [(200, 320)]          # começava no ponto: anda junto
    assert spans(named(seq, "M.mp3", tl.AUDIO)) == [(0, 300)]  # atravessa o ponto em outra faixa: fica inteira
    assert [m.frame for m in seq.markers] == [300]
    right_b = named(seq, "B")[1]
    assert right_b.link and right_b.link == named(seq, "B", tl.AUDIO)[1].link != named(seq, "B")[0].link
    no_overlaps(seq)


def test_overwrite_stays_the_default():
    seq = three()
    seq.insert_media(src("X", frames=50), at=150)
    assert spans(named(seq, "B")) == [(100, 150)]
    assert spans(named(seq, "C")) == [(200, 300)]
    assert spans(named(seq, "T.png")) == [(150, 270)] and [m.frame for m in seq.markers] == [250]


def test_insert_at_a_cut_does_not_split_and_respects_locked_tracks():
    seq = three()
    seq.track(tl.VIDEO, 1).locked = True
    seq.insert_media(src("X", frames=50), at=100, insert=True)
    assert spans(named(seq, "A")) == [(0, 100)] and spans(named(seq, "B")) == [(150, 250)]
    assert spans(named(seq, "C")) == [(250, 350)]
    assert spans(named(seq, "T.png")) == [(150, 270)]   # faixa travada não anda...
    assert [m.frame for m in seq.markers] == [250]      # ...e os marcadores ficam com ela


def test_move_insert_opens_space_at_the_destination():
    seq = three(title=False, music=False)
    c = named(seq, "C")[0]
    seq.move_insert(c.id, 50)
    assert layout(seq) == [("a1", "A", 0, 50), ("a1", "A", 150, 200), ("a1", "B", 200, 300), ("a1", "C", 50, 150),
                           ("v1", "A", 0, 50), ("v1", "A", 150, 200), ("v1", "B", 200, 300), ("v1", "C", 50, 150)]
    seq = three(title=False, music=False)
    a = named(seq, "A")[0]
    seq.move_insert(a.id, 150)  # para a direita, no meio de B: B se divide e o lugar de A fica vazio
    assert spans(named(seq, "B")) == [(100, 150), (250, 300)] and spans(named(seq, "A")) == [(150, 250)]
    assert spans(named(seq, "C")) == [(300, 400)]
    no_overlaps(seq)


def test_ripple_trim_start_and_end_close_the_gap():
    seq = three(music=False)
    b = named(seq, "B")[0]
    assert seq.ripple_trim_start(b.id, 130) == 30
    assert spans(named(seq, "B")) == spans(named(seq, "B", tl.AUDIO)) == [(100, 170)]
    assert named(seq, "B")[0].src_in == pytest.approx(30 / 24)
    assert spans(named(seq, "C")) == [(170, 270)]
    assert spans(named(seq, "T.png")) == [(120, 240)] and [m.frame for m in seq.markers] == [220]
    seq = three(music=False)
    b = named(seq, "B")[0]
    assert seq.ripple_trim_end(b.id, 130) == 70
    assert spans(named(seq, "B")) == [(100, 130)] and spans(named(seq, "C", tl.AUDIO)) == [(130, 230)]
    # O título atravessa o trecho tirado: só as faixas do clipe andam e o marcador fica (como em "Excluir e
    # fechar o espaço").
    assert spans(named(seq, "T.png")) == [(150, 270)] and [m.frame for m in seq.markers] == [250]
    assert seq.ripple_trim_end(b.id, 100) == 0 and seq.ripple_trim_end(b.id, 300) == 0  # cursor fora do clipe


def test_ripple_trim_keeps_other_tracks_when_something_is_under_the_cut():
    seq = three()  # a música atravessa o trecho tirado: só as faixas do clipe andam
    b = named(seq, "B")[0]
    seq.ripple_trim_start(b.id, 130)
    assert spans(named(seq, "C")) == [(170, 270)] and spans(named(seq, "T.png")) == [(150, 270)]
    assert spans(named(seq, "M.mp3", tl.AUDIO)) == [(0, 300)] and [m.frame for m in seq.markers] == [250]


def test_trim_target_prefers_the_selected_track_then_the_top_unlocked_one():
    seq = three()
    assert seq.trim_target(160).name == "T.png"
    assert seq.trim_target(160, (tl.AUDIO, 1)).name == "M.mp3"
    seq.track(tl.VIDEO, 1).locked = True
    assert seq.trim_target(160).name == "B"
    assert seq.trim_target(100).name == "M.mp3"  # num corte da V1 não há o que aparar: vale a faixa de baixo
    assert seq.trim_target(5000) is None


def test_j_and_l_cuts_roll_only_the_sound():
    seq = handles()
    b = named(seq, "B")[0]
    assert seq.split_edit(b.id, True, -24) == -24       # corte J: o som de B entra 1 s antes da imagem
    assert spans(named(seq, "A")) == [(0, 100)] and spans(named(seq, "A", tl.AUDIO)) == [(0, 76)]
    assert spans(named(seq, "B")) == [(100, 200)] and spans(named(seq, "B", tl.AUDIO)) == [(76, 200)]
    assert sync(named(seq, "B")[0]) == sync(named(seq, "B", tl.AUDIO)[0])
    assert seq.split_edit(b.id, False, 12) == 12        # corte L: o som de B continua depois do corte
    assert spans(named(seq, "B", tl.AUDIO)) == [(76, 212)] and spans(named(seq, "C", tl.AUDIO)) == [(212, 300)]
    assert sync(named(seq, "C")[0]) == sync(named(seq, "C", tl.AUDIO)[0])
    assert seq.split_edit(b.id, True, 0) == 0           # alinha de novo
    assert spans(named(seq, "B", tl.AUDIO)) == [(100, 212)] and spans(named(seq, "A", tl.AUDIO)) == [(0, 100)]
    assert seq.split_edit(b.id, True, -500) == -50      # só cabe o que sobra do arquivo antes da entrada
    unlinked = named(seq, "A")[0]
    seq.unlink(unlinked.id)
    assert seq.split_edit(b.id, True, -10) is None      # sem par ligado do outro lado do corte


def test_alt_trim_moves_only_one_side_of_the_pair():
    seq = handles()
    b = named(seq, "B")[0]
    seq.trim_end_only(b.id, 180)
    assert spans(named(seq, "B")) == [(100, 180)] and spans(named(seq, "B", tl.AUDIO)) == [(100, 200)]
    a_audio = named(seq, "A", tl.AUDIO)[0]
    seq.trim_start_only(named(seq, "B", tl.AUDIO)[0].id, 90)  # cobre o fim do som de A, a imagem fica
    assert spans(named(seq, "B", tl.AUDIO)) == [(90, 200)] and a_audio.end == 90
    assert named(seq, "B")[0].link == named(seq, "B", tl.AUDIO)[0].link


def test_offset_pairs_survive_move_split_delete_speed_and_undo():
    seq = handles()
    b = named(seq, "B")[0]
    seq.split_edit(b.id, True, -24)
    snap = json.dumps(seq.to_json())
    lead = named(seq, "B", tl.AUDIO)[0].start - b.start
    seq.move(b.id, b.start + 5)
    assert named(seq, "B", tl.AUDIO)[0].start - named(seq, "B")[0].start == lead == -24
    assert sync(named(seq, "B")[0]) == sync(named(seq, "B", tl.AUDIO)[0])
    seq.move(b.id, b.start - 5)
    # dividir dentro do som que entra antes: a imagem de B vai com a parte da direita do som
    seq.split(85)
    ba = named(seq, "B", tl.AUDIO)
    assert spans(ba) == [(76, 85), (85, 200)]
    assert named(seq, "B")[0].link == ba[1].link and ba[0].link != ba[1].link
    seq = tl.Sequence.from_json(json.loads(snap))  # o corte J sobrevive ao projeto salvo
    assert named(seq, "B", tl.AUDIO)[0].start - named(seq, "B")[0].start == -24
    h = tl.History(seq)
    b = named(seq, "B")[0]
    seq.set_speed(b.id, 2.0)
    vb, ab = named(seq, "B")[0], named(seq, "B", tl.AUDIO)[0]
    assert (vb.start, ab.start, vb.speed, ab.speed) == (100, 88, 2.0, 2.0)
    assert sync(vb) == sync(ab)
    seq.set_speed(b.id, 1.0)
    assert spans(named(seq, "B")) == [(100, 200)] and spans(named(seq, "B", tl.AUDIO)) == [(76, 200)]
    seq.delete([named(seq, "B")[0].id])
    assert named(seq, "B", tl.AUDIO) == [] and named(seq, "B") == []
    h.push(seq)
    restored = h.undo()
    assert spans(named(restored, "B", tl.AUDIO)) == [(76, 200)]


def test_magnetic_key_is_optional_and_off_by_default():
    seq = three()
    data = seq.to_json()
    assert "faixa_magnetica" not in data and not seq.magnetic
    assert not tl.Sequence().magnetic and not tl.Sequence.for_source(src()).magnetic
    assert tl.Sequence.from_json(data).to_json() == data  # projeto antigo sai igual
    seq.magnetic = True
    data = seq.to_json()
    assert data["faixa_magnetica"] is True and tl.Sequence.from_json(data).magnetic
    for junk in ("sim", 1, None, [True]):
        assert not tl.Sequence.from_json({**data, "faixa_magnetica": junk}).magnetic


def magnetic(seq):
    seq.magnetic = True
    seq.settle_main()
    return seq


def test_magnetic_delete_closes_v1_and_the_rest_follows_the_picture():
    seq = magnetic(three())
    with seq.keep_main():
        seq.delete([named(seq, "B")[0].id])
    main_packed(seq)
    assert spans(named(seq, "C")) == spans(named(seq, "C", tl.AUDIO)) == [(100, 200)]
    assert spans(named(seq, "T.png")) == [(100, 220)]  # a imagem de baixo sumiu: vai para o ponto do corte
    assert spans(named(seq, "M.mp3", tl.AUDIO)) == [(0, 300)]  # começava em A, que não mudou
    assert [m.frame for m in seq.markers] == [150]  # estava em C (quadro 50 dele): continua lá
    no_overlaps(seq)


def test_magnetic_move_keeps_connected_clips_on_their_picture():
    seq = magnetic(three())
    with seq.keep_main():
        seq.move(named(seq, "B")[0].id, 300)
    main_packed(seq)
    assert [c.name for c in seq.clips_on(tl.VIDEO, 0)] == ["A", "C", "B"]
    assert spans(named(seq, "B")) == [(200, 300)]
    assert spans(named(seq, "T.png")) == [(250, 370)]  # estava no quadro 50 de B: foi junto
    assert [m.frame for m in seq.markers] == [150]
    with seq.keep_main():  # mexer no próprio título: fica onde a pessoa deixou
        seq.move(named(seq, "T.png")[0].id, 10)
    assert spans(named(seq, "T.png")) == [(10, 130)]
    no_overlaps(seq)


def test_magnetic_insert_and_growth_push_instead_of_covering():
    seq = magnetic(handles())
    with seq.keep_main():
        seq.insert_media(src("X", frames=50), at=150, insert=seq.magnet_active)
    main_packed(seq)
    assert [c.name for c in seq.clips_on(tl.VIDEO, 0)] == ["A", "B", "X", "B", "C"]
    seq = magnetic(handles())
    b = named(seq, "B")[0]
    with seq.keep_main():
        seq.trim_start(b.id, seq.room_for_start(b.id, 90))  # alongar o começo mostra mais do arquivo
    assert spans(named(seq, "A")) == [(0, 100)] and spans(named(seq, "B")) == [(100, 210)]
    assert spans(named(seq, "C")) == spans(named(seq, "C", tl.AUDIO)) == [(210, 310)]
    with seq.keep_main():
        seq.room_for_speed(b.id, 0.5)
        seq.set_speed(b.id, 0.5)
    assert spans(named(seq, "B")) == [(100, 320)] and spans(named(seq, "C")) == [(320, 420)]
    with seq.keep_main():
        seq.trim_end(b.id, 200)  # encurtar puxa o resto
    main_packed(seq)
    assert spans(named(seq, "C")) == [(200, 300)]
    no_overlaps(seq)


def test_magnetic_turning_on_closes_gaps_and_locked_v1_waits():
    seq = three(title=False, music=False)
    seq.delete([named(seq, "B")[0].id])
    assert spans(video(seq)) == [(0, 100), (200, 300)]
    seq.magnetic = True
    seq.track(tl.VIDEO, 0).locked = True
    assert not seq.magnet_active
    seq.settle_main()
    assert spans(video(seq)) == [(0, 100), (200, 300)]  # V1 travada: nada muda
    seq.track(tl.VIDEO, 0).locked = False
    seq.settle_main()
    assert spans(video(seq)) == spans(audio(seq)) == [(0, 100), (100, 200)]
    with seq.keep_main():
        seq.ripple_trim_start(named(seq, "C")[0].id, 150)
    main_packed(seq)
    assert spans(named(seq, "C")) == [(100, 150)]


def test_magnetic_off_changes_nothing():
    seq = three()
    before = seq.to_json()
    with seq.keep_main():
        pass
    seq.settle_main()
    assert seq.to_json() == before
