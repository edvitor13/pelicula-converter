"""Aninhar seleção e desaninhar (#57, ARQUITETURA §41.7): `pelicula/aninhar.py`. A primeira parte é só o modelo (sem GPU nem
Qt): o que vai para onde, o que se recusa e por quê. Depois vêm as provas de que **aninhar não muda a imagem nem o som**
(GPU e ffmpeg de verdade), as legendas presas ao arquivo e o inverso."""

from __future__ import annotations

import copy

import pytest

from pelicula import aninhar, audiomix, subtitles as sb
from pelicula import timeline as tl
from pelicula.aninhar import Refusal
from pelicula.i18n import _

W, H = 320, 180


def fsrc(path="C:/nao/a.mp4", frames=240, **kw):
    kw.setdefault("has_audio", True)
    return tl.Source(path, W, H, 24.0, "24/1", frames, frames / 24.0, pix_fmt="yuv420p", **kw)


def montage(magnetic=False) -> tl.Sequence:
    """V1: a (0-48), b (48-96); V2: sobre (24-72, sem som); A1 de a e b; uma segunda faixa de som com um arquivo só de som."""
    seq = tl.Sequence(width=W, height=H, fps_str="24/1", micro_fade=True, magnetic=magnetic)
    seq.insert_media(fsrc("C:/nao/a.mp4"), 0)
    seq.insert_media(fsrc("C:/nao/b.mp4"), 48)
    for c in seq.clips:
        c.dur = 48
    seq.insert_media(fsrc("C:/nao/c.mp4"), 24, vtrack=1, with_audio=False)
    for c in seq.clips:
        if c.track == 1 and c.kind == tl.VIDEO:
            c.dur = 48
    return seq


def by(seq, src: str, kind=tl.VIDEO) -> tl.Clip:
    return next(c for c in seq.clips if c.src == f"C:/nao/{src}.mp4" and c.kind == kind)


def ids_of(*clips):
    return [c.id for c in clips]


def timeline_of(seq):
    """O que a imagem e o som veem: cada clipe pelo que importa, sem o id da sequência de dentro."""
    return sorted((c.id, c.kind, c.track, c.start, c.dur, round(c.src_in, 6), c.link != "", repr(sorted(c.values.items())))
                  for c in seq.clips)


# ------------------------------------------------------------------ o que vai para onde
def test_nesting_moves_the_clips_with_the_same_ids_and_shifted_times():
    seq = montage()
    b_v, b_a = by(seq, "b"), by(seq, "b", tl.AUDIO)
    v_track_before = [t.name for t in seq.kind_tracks(tl.VIDEO)]
    res = aninhar.nest(seq, [b_v.id])
    inner = res.inner
    assert seq.family() == [seq, inner] and inner.display_name == _("Sequência {n}").format(n=2)
    # os mesmos objetos andaram: id, entrada, ligação e valores intactos; só o tempo e a faixa mudaram
    assert b_v in inner.clips and b_a in inner.clips and b_v.start == 0 and b_a.start == 0
    assert b_v.id and b_v.link == b_a.link and b_v not in seq.clips and b_a not in seq.clips
    assert [t.name for t in seq.kind_tracks(tl.VIDEO)] == v_track_before  # a de fora guarda todas as faixas
    assert (inner.width, inner.height, inner.fps_str) == (W, H, "24/1") and inner.duration == 48
    # fora: um clipe de vídeo e um de som, ligados, na mesma faixa e no mesmo lugar
    outv, outa = res.clips
    assert (outv.kind, outv.track, outv.start, outv.dur, outv.src_in) == (tl.VIDEO, 0, 48, 48, 0.0)
    assert (outa.kind, outa.track, outa.start, outa.dur, outa.src_in) == (tl.AUDIO, 0, 48, 48, 0.0)
    assert outv.link and outv.link == outa.link and outv.src == outa.src == f"sequencia:{inner.id}"
    assert tl.editparams.is_neutral(tl.VIDEO, outv.values) and tl.editparams.is_neutral(tl.AUDIO, outa.values)
    assert not outv.keys and not outv.ramp and outv.name == ""
    assert seq.sources[outv.src].is_nested and seq.nested(outv) is inner
    assert tl.Sequence.from_json(seq.to_json()).to_json() == seq.to_json()  # o resultado salva e reabre igual


def test_the_nested_clip_goes_to_the_lowest_selected_track_and_the_rest_collapse_into_the_inner_one():
    seq = montage()
    a, b, over = by(seq, "a"), by(seq, "b"), by(seq, "c")
    res = aninhar.nest(seq, [a.id, b.id, over.id])
    inner = res.inner
    # a e b (V1) e c (V2): a tela de dentro tem V1 e V2 na mesma ordem; fora, um clipe na V1 cobre de 0 a 96
    assert sorted((c.src[-5:], c.track) for c in inner.clips if c.kind == tl.VIDEO) == [("a.mp4", 0), ("b.mp4", 0),
                                                                                         ("c.mp4", 1)]
    assert (over.start, b.start) == (24, 48)
    outv = res.clips[0]
    assert (outv.track, outv.start, outv.dur) == (0, 0, 96)
    # só a V2 sobre a V1 que fica: o clipe de fora cai na V2, de 24 a 72
    seq2 = montage()
    res2 = aninhar.nest(seq2, [by(seq2, "c").id])
    assert (res2.clips[0].track, res2.clips[0].start, res2.clips[0].dur) == (1, 24, 48)


def test_only_the_used_tracks_go_inside_with_their_properties():
    seq = montage()
    seq.add_track(tl.VIDEO)
    seq.add_track(tl.VIDEO)
    seq.tracks[[t.name for t in seq.tracks].index("V2")].name = "Letreiro"
    seq.track(tl.VIDEO, 1).muted = True   # escondida
    over = by(seq, "c")
    res = aninhar.nest(seq, [over.id])
    inner = res.inner
    names = [(t.kind, t.name, t.muted) for t in inner.tracks]
    assert (tl.VIDEO, "Letreiro", True) in names and sum(1 for t in inner.tracks if t.kind == tl.VIDEO) == 1
    assert over.track == 0 and len(seq.kind_tracks(tl.VIDEO)) == 4
    outv = res.clips[0]
    assert outv.track == 1  # a única faixa da seleção, mesmo escondida
    assert not res.clips[0].link and len(res.clips) == 1  # sem som: só o clipe de vídeo


def test_default_track_names_follow_their_new_position_and_custom_ones_stay():
    seq = montage()
    seq.add_track(tl.VIDEO)
    over = by(seq, "c")
    over.track = 2   # V3
    res = aninhar.nest(seq, [over.id])
    assert [t.name for t in res.inner.kind_tracks(tl.VIDEO)] == ["V1"]
    seq2 = montage()
    seq2.track(tl.VIDEO, 1).name = "Cartela"
    res2 = aninhar.nest(seq2, [by(seq2, "c").id])
    assert [t.name for t in res2.inner.kind_tracks(tl.VIDEO)] == ["Cartela"]


def test_keys_and_times_inside_are_relative_to_the_clip_and_not_shifted():
    seq = montage()
    b_v = by(seq, "b")
    seq.set_key(b_v.id, "opacidade", 60, 0.5)
    seq.set_key(b_v.id, "opacidade", 90, 1.0)
    before = (copy.deepcopy(b_v.keys), b_v.key_off, seq.values_at(b_v, 70)["opacidade"])
    aninhar.nest(seq, [b_v.id])
    inner = seq.family()[1]
    assert (b_v.keys, b_v.key_off) == (before[0], before[1])
    assert abs(inner.values_at(b_v, 70 - 48)["opacidade"] - before[2]) < 1e-12  # o mesmo valor no mesmo ponto do clipe


def test_a_speed_trim_and_ramp_travel_untouched():
    seq = montage()
    b_v = by(seq, "b")
    seq.set_speed(b_v.id, 2.0)
    seq.trim_start(b_v.id, 60)
    b_a = by(seq, "b", tl.AUDIO)
    snap = (b_v.src_in, b_v.dur, b_v.speed, b_a.src_in, b_a.dur)
    aninhar.nest(seq, [b_v.id])
    assert (b_v.src_in, b_v.dur, b_v.speed, b_a.src_in, b_a.dur) == snap


def test_the_inner_sequence_takes_the_window_size_and_loses_the_window():
    seq = montage()
    seq.window = 2.39
    _x, _y, w, h = seq.window_rect(W, H)
    res = aninhar.nest(seq, [by(seq, "a").id])
    assert (res.inner.width, res.inner.height) == (w, h) and res.inner.window == 0.0
    assert seq.window == 2.39 and seq.width == W   # a de fora fica como estava


def test_the_inner_background_and_micro_fade_follow_the_outer_one():
    seq = montage()
    seq.background = (0.2, 0.3, 0.4)
    seq.micro_fade = False
    res = aninhar.nest(seq, [by(seq, "a").id])
    assert res.inner.background == (0.2, 0.3, 0.4) and res.inner.micro_fade is False


def test_the_inner_name_is_free_and_an_asked_name_is_used():
    seq = montage()
    seq.ensure_set().create(W, H, "24/1")     # "Sequência 2" já existe
    assert aninhar.nest(seq, [by(seq, "a").id]).inner.display_name == _("Sequência {n}").format(n=3)
    assert aninhar.nest(seq, [by(seq, "b").id], name="Abertura").inner.display_name == "Abertura"


# ------------------------------------------------------------------ fundo (a promessa da imagem)
def test_nothing_unselected_below_and_a_normal_outer_gives_an_opaque_inner_with_the_outer_background():
    seq = montage()
    seq.background = (0.1, 0.2, 0.3)
    res = aninhar.nest(seq, [by(seq, "a").id])
    assert not res.inner.transparent and res.inner.background == (0.1, 0.2, 0.3)


def test_something_unselected_below_makes_the_inner_transparent():
    seq = montage()
    res = aninhar.nest(seq, [by(seq, "c").id])    # a V2 sobre a V1 que fica
    assert res.inner.transparent and not res.warnings


def test_a_transparent_outer_keeps_a_transparent_inner():
    seq = montage()
    seq.transparent = True
    assert aninhar.nest(seq, [by(seq, "a").id]).inner.transparent


def test_a_blend_mode_over_something_unselected_nests_and_warns():
    seq = montage()
    over = by(seq, "c")
    seq.set_values(over.id, {"mesclagem": "tela"})
    res = aninhar.nest(seq, [over.id])
    assert res.inner.transparent and len(res.warnings) == 1 and "mesclagem" in res.warnings[0]
    # com nada embaixo, a mesclagem é a de sempre e não há aviso
    seq2 = montage()
    v = by(seq2, "a")
    seq2.set_values(v.id, {"mesclagem": "tela"})
    assert aninhar.nest(seq2, [v.id]).warnings == []


def test_a_look_that_reads_the_cuts_warns_but_nests():
    seq = montage()
    res = aninhar.nest(seq, [by(seq, "a").id], look={"mfilme_on": True})
    assert len(res.warnings) == 1 and "cortes" in res.warnings[0]
    seq2 = montage()
    assert aninhar.nest(seq2, [by(seq2, "a").id], look={"mfilme_on": False}).warnings == []
    seq3 = montage()
    v = by(seq3, "a")
    seq3.set_values(v.id, {"luz_r": 2.0})
    assert len(aninhar.nest(seq3, [v.id], look={"lab_on": True}).warnings) == 1
    seq4 = montage()
    assert aninhar.nest(seq4, [by(seq4, "a").id], look=None).warnings == []


# ------------------------------------------------------------------ faixa principal magnética
def test_a_magnetic_outer_keeps_a_magnetic_inner_only_without_gaps_and_nothing_moves():
    seq = montage(magnetic=True)
    a, b = by(seq, "a"), by(seq, "b")
    res = aninhar.nest(seq, [a.id, b.id])
    assert res.inner.magnetic is True
    solo = montage(magnetic=True)
    over = by(solo, "c")
    r2 = aninhar.nest(solo, [over.id])     # a V1 de dentro começa em 0, mas o clipe começava em 24: com buraco antes
    assert r2.inner.magnetic is True       # só o clipe, sem buraco depois: começa em 0 dentro
    # nada se move: a faixa principal de fora, já assentada, continua igual
    for s in (seq, solo):
        before = timeline_of(s)
        s.settle_main()
        assert timeline_of(s) == before


def test_a_magnetic_outer_does_not_make_a_magnetic_inner_with_a_gap_in_the_v1():
    seq = montage(magnetic=True)
    seq.add_track(tl.VIDEO)
    over = by(seq, "c")
    sel = [over.id]
    # o clipe da V2 começa em 24; dentro ele fica sozinho na V1 de dentro, mas um segundo clipe depois do buraco
    extra = seq.insert_media(fsrc("C:/nao/d.mp4"), 80, vtrack=1, with_audio=False)[0]
    sel.append(extra.id)
    res = aninhar.nest(seq, sel)
    assert res.inner.magnetic is False   # buraco entre os dois dentro: ligar a faixa magnética fecharia o buraco


# ------------------------------------------------------------------ recusas
def refuses(seq, ids, fragment="", **kw):
    before = seq.to_json()
    with pytest.raises(Refusal) as exc:
        aninhar.nest(seq, ids, **kw)
    assert fragment in exc.value.text, exc.value.text
    assert seq.to_json() == before and len(seq.family()) == 1   # nada mudou, nem uma sequência nova
    return exc.value.text


def test_refuses_an_empty_selection():
    refuses(montage(), [], "Selecione")
    refuses(montage(), ["não existe"], "Selecione")


def test_refuses_a_clip_on_a_locked_track_even_through_its_partner():
    seq = montage()
    seq.track(tl.AUDIO, 0).locked = True
    refuses(seq, [by(seq, "a").id], "travada")      # o par ligado do vídeo está na A1 travada


def test_refuses_a_clip_left_in_the_middle_of_the_selection():
    seq = montage()
    a, b = by(seq, "a"), by(seq, "b")
    seq.delete([b.id])
    mid = seq.insert_media(fsrc("C:/nao/m.mp4"), 48, with_audio=False)[0]
    mid.dur = 24
    last = seq.insert_media(fsrc("C:/nao/z.mp4"), 72, with_audio=False)[0]
    last.dur = 24
    text = refuses(seq, [a.id, last.id], "no meio")
    assert "V1" in text
    # o vizinho que só encosta no fim da faixa não atrapalha
    aninhar.nest(seq, [a.id, mid.id])


def test_refuses_a_video_track_between_the_selected_ones():
    seq = montage()
    seq.delete([by(seq, "b").id])
    seq.delete([by(seq, "c").id])
    seq.add_track(tl.VIDEO)
    mid = seq.insert_media(fsrc("C:/nao/m.mp4"), 30, vtrack=1, with_audio=False)[0]
    top = seq.insert_media(fsrc("C:/nao/t.mp4"), 30, vtrack=2, with_audio=False)[0]
    mid.dur = top.dur = 20
    base = by(seq, "a")
    refuses(seq, [base.id, top.id], "entre")
    # escondida ou incluída na seleção, não atrapalha a ordem das camadas
    seq.track(tl.VIDEO, 1).muted = True
    aninhar.nest(seq, [base.id, top.id])


def test_refuses_a_transition_that_joins_a_selected_clip_to_an_unselected_one():
    seq = montage()
    a, b = by(seq, "a"), by(seq, "b")
    seq.set_values(b.id, {"entrada_tipo": "dissolver", "entrada_dur": 0.5})
    refuses(seq, [b.id], "transição")        # o dissolver de b mostra a cauda de a
    refuses(seq, [a.id], "transição")        # e a, selecionado, é o que b usa
    aninhar.nest(seq, [a.id, b.id])          # com os dois, tudo fica dentro
    seq2 = montage()
    b2 = by(seq2, "b")
    seq2.set_values(b2.id, {"entrada_tipo": "fusao", "entrada_dur": 0.5})
    refuses(seq2, [b2.id], "transição")
    seq3 = montage()
    seq3.set_values(by(seq3, "b").id, {"entrada_tipo": "surgir", "entrada_dur": 0.5})
    aninhar.nest(seq3, [by(seq3, "b").id])   # surgir não usa o vizinho


def test_refuses_a_sound_crossfade_that_joins_a_selected_clip_to_an_unselected_one():
    seq = montage()
    a_a, b_a = by(seq, "a", tl.AUDIO), by(seq, "b", tl.AUDIO)
    seq.set_values(b_a.id, {"transicao": 0.4})
    assert audiomix.crossfades(seq)[0]
    refuses(seq, [by(seq, "b").id], "som")
    refuses(seq, [by(seq, "a").id], "som")
    aninhar.nest(seq, [by(seq, "a").id, by(seq, "b").id])
    assert a_a in seq.family()[1].clips and b_a in seq.family()[1].clips


def test_refuses_to_pass_the_nesting_limit():
    seq = montage()
    group = seq.ensure_set()
    deep = seq.siblings.create(W, H, "24/1")
    inner = deep
    for _i in range(tl.MAX_NEST - 1):    # uma cadeia de sequências, uma dentro da outra
        nxt = group.create(W, H, "24/1")
        nxt.insert_media(group.sources[f"sequencia:{inner.id}"] if inner is not deep else fsrc("C:/nao/q.mp4"), 0)
        inner = nxt
    top_key = f"sequencia:{inner.id}"
    clip = seq.insert_media(group.sources[top_key], 0, vtrack=1)[0] if group.allows(seq, inner) else None
    assert clip is not None
    refuses_before = seq.to_json()
    with pytest.raises(Refusal) as exc:
        aninhar.nest(seq, [clip.id])
    assert "níveis" in exc.value.text and seq.to_json() == refuses_before


def test_refuses_track_volumes_too_far_apart():
    seq = montage()
    seq.add_track(tl.AUDIO)
    extra = seq.insert_media(fsrc("C:/nao/s.mp4", has_audio=True), 0, vtrack=3, atrack=1, with_audio=True)
    for c in extra:
        c.dur = 48
    seq.clips = [c for c in seq.clips if not (c.kind == tl.VIDEO and c.track == 3)]
    seq.track(tl.AUDIO, 0).volume = -50.0     # a faixa onde o som cai
    seq.track(tl.AUDIO, 1).volume = 12.0      # 12 - (-50) = 62 dB: fora do limite
    sel = [c.id for c in seq.clips if c.kind == tl.AUDIO]
    refuses(seq, sel, "-60 a +12")


# ------------------------------------------------------------------ som
def two_track_sound() -> tuple[tl.Sequence, list[str]]:
    seq = tl.Sequence(width=W, height=H, fps_str="24/1", micro_fade=True)
    a = seq.insert_media(fsrc("C:/nao/a.mp4"), 0)
    for c in a:
        c.dur = 96
    s2 = seq.insert_media(fsrc("C:/nao/s.mp4", has_video=False), 0, atrack=1)
    for c in s2:
        c.dur = 96
    return seq, [c.id for c in seq.clips]


def test_the_inner_volume_is_the_original_minus_the_track_where_the_nested_clip_falls():
    seq, ids = two_track_sound()
    seq.track(tl.AUDIO, 0).volume = -2.0
    seq.track(tl.AUDIO, 1).volume = -5.0
    res = aninhar.nest(seq, ids)
    outa = next(c for c in res.clips if c.kind == tl.AUDIO)
    assert outa.track == 0                                 # a mais baixa
    vols = [t.volume for t in res.inner.kind_tracks(tl.AUDIO)]
    assert vols == [pytest.approx(0.0), pytest.approx(-3.0)]
    # o ganho total de cada clipe é o de antes: dentro + a faixa de fora
    assert [v + seq.track(tl.AUDIO, 0).volume for v in vols] == [pytest.approx(-2.0), pytest.approx(-5.0)]


def test_a_muted_track_is_not_where_the_sound_falls_and_stays_silent_inside():
    seq, ids = two_track_sound()
    seq.track(tl.AUDIO, 0).muted = True
    seq.track(tl.AUDIO, 1).volume = -4.0
    res = aninhar.nest(seq, ids)
    outa = next(c for c in res.clips if c.kind == tl.AUDIO)
    assert outa.track == 1
    assert [t.muted for t in res.inner.kind_tracks(tl.AUDIO)] == [True, False]
    assert [t.volume for t in res.inner.kind_tracks(tl.AUDIO)][1] == pytest.approx(0.0)
    assert [c.src for c in res.inner.audio_clips()] == ["C:/nao/s.mp4"] and res.inner.has_audio


def test_solo_silences_the_tracks_it_silenced_before_and_the_sound_falls_on_a_solo_track():
    seq, ids = two_track_sound()
    seq.track(tl.AUDIO, 1).solo = True
    res = aninhar.nest(seq, ids)
    outa = next(c for c in res.clips if c.kind == tl.AUDIO)
    assert outa.track == 1                                 # a A1 não soa (outra em solo): o clipe cai na que soa
    assert [t.muted for t in res.inner.kind_tracks(tl.AUDIO)] == [True, False]
    assert [t.solo for t in res.inner.kind_tracks(tl.AUDIO)] == [False, True]
    assert [c.src for c in res.inner.audio_clips()] == ["C:/nao/s.mp4"] and seq.audio_clips() == [outa]


def test_selection_with_only_silent_audio_creates_no_sound_clip():
    seq, ids = two_track_sound()
    for t in seq.kind_tracks(tl.AUDIO):
        t.muted = True
    res = aninhar.nest(seq, ids)
    assert not any(c.kind == tl.AUDIO for c in res.clips)


def gain(seq, clip) -> float:
    """O ganho de um clipe de som como a mixagem o soma (`audiomix.segments`): o do clipe mais o da faixa."""
    return float(clip.values["volume"]) + seq.track(tl.AUDIO, clip.track).volume


def test_the_same_audible_clips_play_before_and_after():
    """Os mesmos clipes tocam, e o ganho de cada um (dentro + a faixa de fora) é o de antes."""
    seq, ids = two_track_sound()
    seq.track(tl.AUDIO, 0).volume = 3.0
    seq.track(tl.AUDIO, 1).volume = -7.0
    before = {c.id: gain(seq, c) for c in seq.audio_clips()}
    res = aninhar.nest(seq, ids)
    inner_gain = {c.id: gain(res.inner, c) for c in res.inner.audio_clips()}
    outer = seq.audio_clips()
    assert len(outer) == 1 and set(before) == set(inner_gain)
    for cid, g in before.items():
        assert inner_gain[cid] + gain(seq, outer[0]) == pytest.approx(g)


def test_nonlinear_effects_with_a_track_volume_warn():
    seq, ids = two_track_sound()
    seq.track(tl.AUDIO, 0).volume = -2.0
    a_a = by(seq, "a", tl.AUDIO)
    seq.set_values(a_a.id, {"voz": True})
    res = aninhar.nest(seq, ids)
    assert any("voz" in w for w in res.warnings)
    seq2, ids2 = two_track_sound()
    seq2.set_values(by(seq2, "a", tl.AUDIO).id, {"voz": True})
    assert aninhar.nest(seq2, ids2).warnings == []         # a 0 dB a ordem do ganho não importa


def test_a_join_without_a_cut_warns_about_the_short_fade_it_gets():
    seq = tl.Sequence(width=W, height=H, fps_str="24/1", micro_fade=True)
    seq.insert_media(fsrc("C:/nao/a.mp4"), 0)
    seq.split(24)
    seq.split(48)
    mid = next(c for c in seq.clips if c.kind == tl.VIDEO and c.start == 24)
    res = aninhar.nest(seq, [mid.id])
    assert any("5 ms" in w for w in res.warnings)
    lone = tl.Sequence(width=W, height=H, fps_str="24/1", micro_fade=True)
    lone.insert_media(fsrc("C:/nao/a.mp4"), 0)
    assert aninhar.nest(lone, [c.id for c in lone.clips]).warnings == []


# ------------------------------------------------------------------ desaninhar
def sig(seq):
    """A montagem do ponto de vista da imagem e do som (sem a faixa onde cada coisa está, só a ordem das faixas)."""
    return sorted((c.kind, c.track, c.start, c.dur, round(c.src_in, 6), c.src, c.id, repr(sorted(c.values.items())),
                   repr(c.keys), c.key_off) for c in seq.clips)


@pytest.mark.parametrize("pick", [["b"], ["a", "b"], ["c"], ["a", "b", "c"]])
def test_nesting_then_unnesting_gives_the_same_clips(pick):
    seq = montage()
    seq.set_key(by(seq, "c").id, "opacidade", 40, 0.5)
    ids = [by(seq, p).id for p in pick]
    ids += [x.id for x in seq.expand(ids)]
    base = sig(seq)
    tracks_before = [(t.kind, t.name, t.muted, t.volume) for t in seq.tracks]
    res = aninhar.nest(seq, ids)
    assert sig(seq) != base
    nested = next(c for c in res.clips if c.kind == tl.VIDEO)
    back = aninhar.unnest(seq, nested.id)
    assert sig(seq) == base
    assert [c.id for c in back.clips] and not any(c.src.startswith("sequencia:") for c in seq.clips)
    assert [(t.kind, t.name, t.muted, t.volume) for t in seq.tracks] == tracks_before
    assert len(seq.family()) == 2                       # a sequência de dentro fica no projeto


def test_unnest_keeps_the_links_and_the_ids():
    seq = montage()
    b_v, b_a = by(seq, "b"), by(seq, "b", tl.AUDIO)
    link = b_v.link
    res = aninhar.nest(seq, [b_v.id])
    aninhar.unnest(seq, res.clips[0].id)
    got_v = seq.find(b_v.id)
    assert got_v is not None and seq.find(b_a.id) is not None and got_v.link == link == seq.find(b_a.id).link


def test_unnest_cuts_to_the_range_the_clip_showed_and_shifts_it_to_the_outer_time():
    seq = montage()
    a, b = by(seq, "a"), by(seq, "b")
    res = aninhar.nest(seq, [a.id, b.id])            # dentro: a (0-48) e b (48-96)
    outv = next(c for c in res.clips if c.kind == tl.VIDEO)
    outa = next(c for c in res.clips if c.kind == tl.AUDIO)
    seq.trim_start(outv.id, 24)                       # mostra 24..96 de dentro (a metade de a e b inteiro)
    seq.trim_end(outv.id, 84)                         # ... até 84 (b cortado)
    seq.move(outv.id, 100)                            # e vai para o quadro 100 (o som ligado vai junto)
    assert (outv.src_in, outv.dur, outv.start) == (1.0, 60, 100) and (outa.src_in, outa.start) == (1.0, 100)
    aninhar.unnest(seq, outv.id)
    got = sorted((c.src, c.start, c.dur, round(c.src_in, 6)) for c in seq.clips
                 if c.kind == tl.VIDEO and not c.src.endswith("c.mp4"))
    assert got == [("C:/nao/a.mp4", 100, 24, 1.0), ("C:/nao/b.mp4", 124, 36, 0.0)]
    audio = sorted((c.src, c.start, c.dur, round(c.src_in, 6)) for c in seq.clips if c.kind == tl.AUDIO)
    assert audio == [("C:/nao/a.mp4", 100, 24, 1.0), ("C:/nao/b.mp4", 124, 36, 0.0)]
    cut_left = next(c for c in seq.clips if c.src == "C:/nao/a.mp4" and c.kind == tl.VIDEO)
    assert cut_left.id == a.id            # o pedaço que sobra de a leva o id de a


def test_unnest_asks_about_what_would_be_lost_and_refuses_what_cannot_be_carried():
    seq = montage()
    res = aninhar.nest(seq, [by(seq, "a").id])
    outv = next(c for c in res.clips if c.kind == tl.VIDEO)
    assert seq.nested(outv) is res.inner
    assert aninhar.unnest_loss(seq, outv.id) == []     # o que o aninhar fez é neutro
    seq.set_values(outv.id, {"opacidade": 0.5, "saturacao": 0.3, "escala": 1.2})
    loss = aninhar.unnest_loss(seq, outv.id)
    assert "opacidade" in loss and "enquadramento" in loss and "cor e detalhe" in loss
    seq.set_values(outv.id, {"velocidade": 2.0})
    with pytest.raises(Refusal) as exc:
        aninhar.unnest(seq, outv.id)
    assert "velocidade" in exc.value.text
    seq.set_values(outv.id, {"velocidade": 1.0})
    seq.retime(outv.id, reverse=True)
    with pytest.raises(Refusal):
        aninhar.unnest_loss(seq, outv.id)
    with pytest.raises(Refusal):
        aninhar.unnest(seq, by(seq, "b").id)           # não é um clipe de sequência


def test_unnest_refuses_a_locked_track_and_another_frame_rate():
    seq = montage()
    res = aninhar.nest(seq, [by(seq, "a").id])
    outv = next(c for c in res.clips if c.kind == tl.VIDEO)
    seq.track(tl.VIDEO, 0).locked = True
    with pytest.raises(Refusal) as exc:
        aninhar.unnest(seq, outv.id)
    assert "travada" in exc.value.text
    seq.track(tl.VIDEO, 0).locked = False
    res.inner.fps_str = "30/1"
    with pytest.raises(Refusal) as exc:
        aninhar.unnest(seq, outv.id)
    assert "quadros por segundo" in exc.value.text


def test_unnest_keeps_the_layer_order_of_what_is_around():
    """Dois clipes de dentro em V1 e V2; fora, um clipe da V2 (sem relação) tem que continuar acima dos dois."""
    seq = montage()
    seq.delete([by(seq, "b").id])
    seq.add_track(tl.VIDEO)
    seq.add_track(tl.VIDEO)
    a = by(seq, "a")
    over = by(seq, "c")          # V2, 24-72
    res = aninhar.nest(seq, [a.id, over.id])      # dentro: a (V1), c (V2); fora: um clipe só, na V1
    outv = next(c for c in res.clips if c.kind == tl.VIDEO)
    other = seq.insert_media(fsrc("C:/nao/o.mp4"), 10, vtrack=1, with_audio=False)[0]    # V2, por cima, de fora
    other.dur = 30
    aninhar.unnest(seq, outv.id)
    order = {c.src: c.track for c in seq.clips if c.kind == tl.VIDEO}
    assert order["C:/nao/a.mp4"] < order["C:/nao/c.mp4"] < order["C:/nao/o.mp4"]
    assert len(seq.kind_tracks(tl.VIDEO)) >= 4


def test_unnest_restores_the_sound_volumes_and_flags():
    seq, ids = two_track_sound()
    seq.track(tl.AUDIO, 0).volume = -2.0
    seq.track(tl.AUDIO, 1).volume = -5.0
    seq.track(tl.AUDIO, 1).name = "Música"
    res = aninhar.nest(seq, ids)
    outa = next(c for c in res.clips if c.kind == tl.AUDIO)
    aninhar.unnest(seq, outa.id)
    got = {c.src: seq.track(tl.AUDIO, c.track) for c in seq.clips if c.kind == tl.AUDIO}
    assert got["C:/nao/a.mp4"].volume == pytest.approx(-2.0) and got["C:/nao/s.mp4"].volume == pytest.approx(-5.0)
    assert got["C:/nao/s.mp4"].name == "Música"


def test_unnest_of_a_video_only_clip_brings_back_only_the_picture():
    seq = montage()
    res = aninhar.nest(seq, [by(seq, "a").id])
    outv = next(c for c in res.clips if c.kind == tl.VIDEO)
    seq.unlink(outv.id)
    seq.delete([next(c.id for c in res.clips if c.kind == tl.AUDIO)])   # só o vídeo de fora
    aninhar.unnest(seq, outv.id)
    assert by(seq, "a").link == ""         # sem o par, a ligação não ficaria pendurada
    assert not [c for c in seq.clips if c.src == "C:/nao/a.mp4" and c.kind == tl.AUDIO]


def test_two_levels_nest_a_selection_that_already_has_a_nested_clip():
    seq = montage()
    first = aninhar.nest(seq, [by(seq, "a").id])
    outv = next(c for c in first.clips if c.kind == tl.VIDEO)
    second = aninhar.nest(seq, [outv.id, by(seq, "b").id])     # o clipe de sequência entra numa segunda sequência
    assert any(c.src == f"sequencia:{first.inner.id}" for c in second.inner.clips)
    assert seq.nested(second.clips[0]) is second.inner
    assert [s.display_name for s in seq.family()] == [_("Sequência 1")] + [_("Sequência {n}").format(n=n) for n in (2, 3)]
    assert second.inner.can_contain(seq.sources[f"sequencia:{first.inner.id}"])
    aninhar.unnest(seq, next(c.id for c in second.clips if c.kind == tl.VIDEO))
    assert any(c.src == f"sequencia:{first.inner.id}" for c in seq.clips)


# ------------------------------------------------------------------ legendas presas ao arquivo
def cue(a, b, text):
    return sb.Cue(a, b, text)


def subs_for(seq, path="C:/nao/b.mp4"):
    seq.subtitles = sb.Subtitles(sources={path: [cue(0.2, 1.0, "primeira"), cue(1.2, 1.9, "segunda")]})
    return [(c.start, c.end, c.text) for c in seq.subtitles.timeline_cues(seq)]


def test_subtitles_tied_to_a_file_follow_the_clip_into_a_nested_sequence_and_back():
    seq = montage()
    before = subs_for(seq)
    assert before                                    # a legenda aparece (b está em 48..96)
    res = aninhar.nest(seq, [by(seq, "b").id])
    assert [(c.start, c.end, c.text) for c in seq.subtitles.timeline_cues(seq)] == before
    aninhar.unnest(seq, res.clips[0].id)
    assert [(c.start, c.end, c.text) for c in seq.subtitles.timeline_cues(seq)] == before


def test_subtitles_follow_a_moved_nested_clip_like_a_file_clip():
    seq = montage()
    subs_for(seq)
    res = aninhar.nest(seq, [by(seq, "b").id])
    outv = next(c for c in res.clips if c.kind == tl.VIDEO)
    seq.move(outv.id, outv.start + 24)      # o clipe de sequência anda 1 s para a frente
    got = [(round(c.start, 6), round(c.end, 6), c.text) for c in seq.subtitles.timeline_cues(seq)]
    assert got == [(3.2, 4.0, "primeira"), (4.2, 4.9, "segunda")]


def test_subtitles_in_two_levels_and_with_a_sped_up_nested_clip():
    seq = montage()
    flat = subs_for(seq)
    first = aninhar.nest(seq, [by(seq, "b").id])
    second = aninhar.nest(seq, [next(c.id for c in first.clips if c.kind == tl.VIDEO)])
    assert [(c.start, c.end, c.text) for c in seq.subtitles.timeline_cues(seq)] == flat
    outv = next(c for c in second.clips if c.kind == tl.VIDEO)
    seq.set_speed(outv.id, 2.0)
    fast = [(c.start, c.end, c.text) for c in seq.subtitles.timeline_cues(seq)]
    assert [c[2] for c in fast] == ["primeira", "segunda"] and fast[0][0] == pytest.approx(48 / 24 + 0.2 / 2)


def test_subtitles_of_the_sequence_do_not_move_when_nesting():
    seq = montage()
    seq.subtitles = sb.Subtitles(cues=[cue(1.0, 2.0, "fixa")])
    before = [(c.start, c.end, c.text) for c in seq.subtitles.timeline_cues(seq)]
    aninhar.nest(seq, [by(seq, "b").id])
    assert [(c.start, c.end, c.text) for c in seq.subtitles.timeline_cues(seq)] == before
    assert seq.subtitles.cues[0].text == "fixa" and seq.family()[1].subtitles is None


def test_editing_a_mapped_subtitle_through_a_nested_clip():
    from pelicula import subedit
    seq = montage()
    subs_for(seq)
    aninhar.nest(seq, [by(seq, "b").id])
    items = subedit.items(seq, seq.subtitles)
    first = next(it for it in items if it.cue.text == "primeira")
    assert first.mapping is not None and not first.fixed
    # mudar o texto e mover a legenda: a guardada (tempo do arquivo) acompanha
    subedit.set_text(seq.subtitles, first.ref, "mudou")
    assert [it.cue.text for it in subedit.items(seq, seq.subtitles)][0] == "mudou"
    subedit.move(seq.subtitles, subedit.items(seq, seq.subtitles)[0], 0.5)
    stored = seq.subtitles.sources["C:/nao/b.mp4"][0]
    assert stored.start == pytest.approx(0.7) and stored.text == "mudou"
    shown = subedit.items(seq, seq.subtitles)[0].cue
    assert shown.start == pytest.approx(48 / 24 + 0.7)


def test_a_project_without_nested_clips_maps_subtitles_as_before():
    seq = montage()
    assert subs_for(seq) == [(2.2, 3.0, "primeira"), (3.2, 3.9, "segunda")]
    assert sb.carriers(seq, "C:/nao/b.mp4") == sb.clips_for(seq, "C:/nao/b.mp4")


# ================================================================== na GPU e no ffmpeg: a promessa de "nada muda"
# Uma montagem de verdade (cortes, transições, opacidade, geometria, chaves, PNG transparente, título com mesclagem, duas
# faixas de som em volumes diferentes, transição de som e legenda presa ao arquivo) é exportada; a seleção é aninhada e
# exportada de novo; desaninhada e exportada outra vez. Imagem e som pelo caminho de sempre (`Recipe`, `render_mix`) e, uma
# vez, pelo terminal, num projeto salvo.
import numpy as np  # noqa: E402

from pelicula import cli, export, media, project, sequence  # noqa: E402
from test_aninhada import LOOK, _first_diff, _look, _samples, clips_media, mix_dir  # noqa: E402,F401


def golden(clips_media, qapp, subtitles=True) -> tl.Sequence:
    """A montagem do teste: tudo que o brief pede, com os clipes de V1 a V4 e o som em duas faixas."""
    from test_aninhada import flat_montage
    seq = flat_montage(clips_media, qapp, background=(0.1, 0.2, 0.3))
    longo = media.probe_source(clips_media[0])
    over = next(c for c in seq.clips if c.kind == tl.VIDEO and c.track == 1)
    seq.set_key(over.id, "opacidade", over.start + 4, 0.9)
    seq.set_key(over.id, "pos_x", over.start + 2, 0.3)
    seq.set_key(over.id, "pos_x", over.start + 14, -0.2)
    # a transição de som entre o primeiro e o segundo clipe da V1
    b_a = next(c for c in seq.clips if c.kind == tl.AUDIO and c.start == 18)
    seq.set_values(b_a.id, {"transicao": 0.4})
    extra = next(c for c in seq.insert_media(longo, at=5, vtrack=4, atrack=1) if c.kind == tl.AUDIO)
    seq.set_values(extra.id, {"fade_in": 0.2, "volume": -6.0})
    seq.clips = [c for c in seq.clips if not (c.kind == tl.VIDEO and c.track == 4)]
    seq.track(tl.AUDIO, 0).volume = -2.0
    seq.track(tl.AUDIO, 1).volume = -4.0
    if subtitles:
        seq.subtitles = sb.Subtitles(sources={clips_media[0]: [cue(0.1, 0.6, "Olá"), cue(1.0, 1.7, "mundo afora"),
                                                                 cue(2.4, 3.0, "no fim")]}, burn="digital")
    return seq


def frames_of(engine, seq, values, depth, scale=1.0):
    """Os quadros pelo caminho da exportação, com as legendas gravadas do projeto."""
    burn = sb.Burn.for_project(seq.subtitles, seq)
    info = sequence.media_info(seq)
    s = export.ExportSettings()
    rec = export.frame_pipeline(info, values, s, seq, scale, depth, burn=burn)
    reader, skip = export.open_reader(info, rec, 0, seq.duration, None, media.Perf(), seq)
    assert skip == 0
    out = []
    try:
        for i in range(seq.duration):
            out.append(rec.render(engine, reader.read(), i))
        assert reader.error == ""
    finally:
        reader.close()
    return out


def worst(a_frames, b_frames) -> tuple[int, int, float]:
    """(maior diferença em passos, valores diferentes, fração deles) entre duas listas de quadros."""
    assert len(a_frames) == len(b_frames)
    mx, n, total = 0, 0, 0
    for a, b in zip(a_frames, b_frames):
        assert a.shape == b.shape and a.dtype == b.dtype
        d = np.abs(a.astype(np.int64) - b.astype(np.int64))
        mx = max(mx, int(d.max()))
        n += int((d > 0).sum())
        total += d.size
    return mx, n, n / total


def assert_identical(a_frames, b_frames, what="") -> None:
    assert len(a_frames) == len(b_frames)
    for t, (a, b) in enumerate(zip(a_frames, b_frames)):
        assert np.array_equal(a, b), f"{what} quadro {t}: {_first_diff(a, b)}"


def nest_all(seq, **kw):
    """Aninha tudo (Ctrl+A) e devolve o resultado."""
    return aninhar.nest(seq, [c.id for c in seq.clips], **kw)


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
@pytest.mark.parametrize("look", [None, LOOK])
def test_nesting_everything_then_unnesting_gives_the_same_frames(gl_engine, clips_media, qapp, depth, look):
    values = _look(look)
    seq = golden(clips_media, qapp)
    flat = frames_of(gl_engine, seq, values, depth)
    assert any(f.max() > 0 for f in flat)
    res = nest_all(seq, look=values)
    assert not res.warnings and not res.inner.transparent and len(seq.clips) == 2
    nested = frames_of(gl_engine, seq, values, depth)
    assert_identical(flat, nested, "aninhada")
    outv = next(c for c in res.clips if c.kind == tl.VIDEO)
    aninhar.unnest(seq, outv.id)
    assert not any(c.src.startswith("sequencia:") for c in seq.clips)
    assert_identical(flat, frames_of(gl_engine, seq, values, depth), "desaninhada")


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_nesting_everything_keeps_the_subtitles_burnt_in_the_same_place(gl_engine, clips_media, qapp):
    seq = golden(clips_media, qapp)
    plain = golden(clips_media, qapp, subtitles=False)
    values = _look(LOOK)
    with_text = frames_of(gl_engine, seq, values, 8)
    without = frames_of(gl_engine, plain, values, 8)
    assert worst(with_text, without)[0] > 0                   # a legenda está mesmo desenhada
    before = [(c.start, c.end, c.text) for c in seq.subtitles.timeline_cues(seq)]
    assert {c[2] for c in before} == {"Olá", "mundo afora", "no fim"} and len(before) > 3   # o arquivo aparece em vários clipes
    res = nest_all(seq)
    assert [(c.start, c.end, c.text) for c in seq.subtitles.timeline_cues(seq)] == before
    assert_identical(with_text, frames_of(gl_engine, seq, values, 8), "legendas, aninhada")
    aninhar.unnest(seq, next(c.id for c in res.clips if c.kind == tl.VIDEO))
    assert [(c.start, c.end, c.text) for c in seq.subtitles.timeline_cues(seq)] == before
    assert_identical(with_text, frames_of(gl_engine, seq, values, 8), "legendas, desaninhada")


SOUND_LIMIT_STEPS = 1.0   # medido: 1 passo de 24 bits, quando a faixa de fora tem volume (ver o handoff)


def mix_of(seq, path) -> np.ndarray:
    assert audiomix.render_mix(seq, str(path)) is True
    return _samples(path)


def _sound_diff(a, b) -> tuple[float, int]:
    """(maior diferença em passos de 24 bits, amostras diferentes)."""
    assert abs(len(a) - len(b)) <= 2, (len(a), len(b))
    n = min(len(a), len(b))
    d = np.abs(a[:n] - b[:n]) * 8388608.0
    return float(d.max()), int((d > 0).sum())


@pytest.mark.ffmpeg
def test_the_sound_after_nesting_and_unnesting_sample_by_sample(clips_media, qapp, tmp_path, mix_dir):
    seq = golden(clips_media, qapp)
    flat = mix_of(seq, tmp_path / "plano.wav")
    assert np.abs(flat).max() > 0.01
    res = nest_all(seq)
    nested = mix_of(seq, tmp_path / "aninhada.wav")
    d1 = _sound_diff(flat, nested)
    aninhar.unnest(seq, next(c.id for c in res.clips if c.kind == tl.AUDIO))
    back = mix_of(seq, tmp_path / "desaninhada.wav")
    d2 = _sound_diff(flat, back)
    print(f"\nsom: aninhada {d1[0]:.0f} passos de 24 bits em {d1[1]} amostras; desaninhada {d2[0]:.0f} em {d2[1]}")


def _stage_png_and_decode(seq, name, tmp_path, ffmpeg_ok, values):
    """Salva o projeto e exporta pelo terminal (FFV1 + PCM); devolve (quadros em 16 bits, amostras)."""
    from test_aninhada import _decoded
    plc = tmp_path / f"{name}.plc"
    project.save(project.Project(values=values, preset_id=LOOK, sequence=seq.to_json()), str(plc))
    out = tmp_path / f"{name}.mkv"
    assert cli.main(["exportar", str(plc), "-o", str(out), "--qualidade", "ffv1", "-q"]) == 0
    return _decoded(out, ffmpeg_ok, tmp_path)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_cli_on_a_saved_project_gives_the_same_frames_and_sound_before_after_nesting_and_after_unnesting(
        gl_engine, clips_media, qapp, ffmpeg_ok, tmp_path, mix_dir, capsys):
    values = _look(LOOK)
    seq = golden(clips_media, qapp)
    flat_f, flat_s = _stage_png_and_decode(seq, "plano", tmp_path, ffmpeg_ok, values)
    res = nest_all(seq)
    nest_f, nest_s = _stage_png_and_decode(seq, "aninhada", tmp_path, ffmpeg_ok, values)
    saved = project.load(str(tmp_path / "aninhada.plc"))
    assert "sequencia_aninhada" in tl.Sequence.from_json(saved.sequence).features()
    aninhar.unnest(seq, next(c.id for c in res.clips if c.kind == tl.VIDEO))
    back_f, back_s = _stage_png_and_decode(seq, "desaninhada", tmp_path, ffmpeg_ok, values)
    assert len(flat_f) == len(nest_f) == len(back_f) == seq.duration
    for t in range(len(flat_f)):
        assert np.array_equal(flat_f[t], nest_f[t]), f"aninhada, quadro {t}: {_first_diff(flat_f[t], nest_f[t])}"
        assert np.array_equal(flat_f[t], back_f[t]), f"desaninhada, quadro {t}: {_first_diff(flat_f[t], back_f[t])}"
    d1, d2 = _sound_diff(flat_s, nest_s), _sound_diff(flat_s, back_s)
    print(f"\nterminal, som: aninhada {d1}; desaninhada {d2}")
    assert d1[0] <= SOUND_LIMIT_STEPS and d2 == (0.0, 0)


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
@pytest.mark.parametrize("look", [None, LOOK])
def test_a_window_on_the_outer_sequence_is_kept_when_nesting_everything(gl_engine, clips_media, qapp, depth, look):
    """Sem clipe gerado, no máximo 1 passo (arredondamento da tela de dentro, que tem o tamanho da janela). O título, que
    se encaixa na janela de fora mas na tela inteira de dentro, muda um pouco: o aviso existe por isso."""
    values = _look(look)
    for with_title in (False, True):
        seq = golden(clips_media, qapp, subtitles=False)
        if not with_title:
            seq.clips = [c for c in seq.clips if not (c.kind == tl.VIDEO and c.track == 3)]
        seq.window = 2.39
        flat = frames_of(gl_engine, seq, values, depth)
        res = nest_all(seq)
        assert res.inner.window == 0.0 and res.inner.height < seq.height and seq.window == 2.39
        assert bool(res.warnings) == with_title
        got = worst(flat, frames_of(gl_engine, seq, values, depth))
        print(f"\njanela, {depth} bits, look {look}, título {with_title}: máximo {got[0]} passos, {got[1]} valores "
              f"({got[2] * 100:.4f}%)")
        assert got[0] <= WINDOW_LIMIT[(depth, look is None, with_title)], got
        aninhar.unnest(seq, next(c.id for c in res.clips if c.kind == tl.VIDEO))
        assert_identical(flat, frames_of(gl_engine, seq, values, depth), "janela, desaninhada")


# medido (ver o handoff); o primeiro item é a profundidade, o segundo "sem look", o terceiro "com o título"
WINDOW_LIMIT = {(8, True, False): 1, (8, False, False): 1, (16, True, False): 256, (16, False, False): 256,
                (8, True, True): 4, (8, False, True): 9, (16, True, True): 1000, (16, False, True): 2240}


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
@pytest.mark.parametrize("look", [None, LOOK])
def test_nesting_upper_tracks_over_an_unselected_v1_is_within_one_step(gl_engine, clips_media, qapp, depth, look):
    values = _look(look)
    seq = golden(clips_media, qapp, subtitles=False)
    over = next(c for c in seq.clips if c.kind == tl.VIDEO and c.track == 1)
    png = next(c for c in seq.clips if c.kind == tl.VIDEO and c.track == 2)
    flat = frames_of(gl_engine, seq, values, depth)
    res = aninhar.nest(seq, [over.id, png.id], look=values)
    assert res.inner.transparent and not res.warnings
    outv = res.clips[0]
    assert (outv.track, outv.start, outv.end) == (1, 6, 44)
    got = worst(flat, frames_of(gl_engine, seq, values, depth))
    print(f"\nfaixas de cima, {depth} bits, look {look}: máximo {got[0]} passos, {got[1]} valores ({got[2] * 100:.4f}%)")
    assert got[0] <= (16 if (depth == 16 and look) else 1), got   # o look amplifica o passo de 16 bits: < 1 passo de 8 bits
    aninhar.unnest(seq, outv.id)
    assert_identical(flat, frames_of(gl_engine, seq, values, depth), "faixas de cima, desaninhada")


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_a_blend_mode_over_unselected_clips_changes_the_picture_and_that_is_why_it_warns(gl_engine, clips_media, qapp):
    seq = golden(clips_media, qapp, subtitles=False)
    title = next(c for c in seq.clips if c.kind == tl.VIDEO and c.track == 3)   # mesclagem "tela"
    flat = frames_of(gl_engine, seq, None, 8)
    res = aninhar.nest(seq, [title.id])
    assert res.inner.transparent and len(res.warnings) == 1
    got = worst(flat, frames_of(gl_engine, seq, None, 8))
    print(f"\nmesclagem sobre o que ficou fora: máximo {got[0]} passos em {got[2] * 100:.3f}% dos valores")
    assert got[0] > 1   # o aviso existe porque a imagem muda de verdade


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
def test_nesting_a_selection_that_already_has_a_nested_clip(gl_engine, clips_media, qapp, depth):
    values = _look(LOOK)
    seq = golden(clips_media, qapp, subtitles=False)
    png_src = media.probe_source(clips_media[2])
    ref = golden(clips_media, qapp, subtitles=False)
    for s in (seq, ref):  # o mesmo clipe extra, por cima de tudo, nas duas
        extra = s.insert_media(png_src, at=20, vtrack=5, with_audio=False)[0]
        extra.dur = 12
        extra.id = "extra0001"
    flat = frames_of(gl_engine, ref, values, depth)
    first = aninhar.nest(seq, [c.id for c in seq.clips if c.id != "extra0001"])
    assert_identical(flat, frames_of(gl_engine, seq, values, depth), "uma vez")
    second = aninhar.nest(seq, [c.id for c in seq.clips])
    assert second.inner.name != first.inner.name and seq.nested(second.clips[0]) is second.inner
    assert any(seq.sources[c.src].is_nested for c in second.inner.clips)
    assert_identical(flat, frames_of(gl_engine, seq, values, depth), "duas vezes")
    aninhar.unnest(seq, next(c.id for c in second.clips if c.kind == tl.VIDEO))
    assert_identical(flat, frames_of(gl_engine, seq, values, depth), "desaninhada uma")
    aninhar.unnest(seq, next(c.id for c in seq.clips if c.kind == tl.VIDEO and c.src.startswith("sequencia:")))
    assert_identical(flat, frames_of(gl_engine, seq, values, depth), "desaninhada duas")
    assert first.inner is not second.inner


@pytest.mark.ffmpeg
def test_nesting_a_selection_in_the_middle_changes_the_sound_only_at_the_edges(clips_media, qapp, tmp_path, mix_dir):
    """A emenda sem estalo (o clipe continua o anterior) ganha os fades curtos nas duas pontas do clipe de sequência."""
    longo = media.probe_source(clips_media[0])
    seq = tl.Sequence(width=W, height=H, fps_str="24/1", micro_fade=True)
    seq.insert_media(longo, at=0)
    seq.split(24)
    seq.split(48)
    mid = next(c for c in seq.clips if c.kind == tl.VIDEO and c.start == 24)
    flat = mix_of(seq, tmp_path / "plano.wav")
    res = aninhar.nest(seq, [mid.id])
    nested = mix_of(seq, tmp_path / "aninhada.wav")
    n = min(len(flat), len(nested))
    diff = np.abs(flat[:n] - nested[:n]) * 8388608.0
    where = np.nonzero(diff.max(axis=1) > 0)[0] if diff.ndim > 1 else np.nonzero(diff > 0)[0]
    micro = int(round(tl.MICRO_FADE * audiomix.RATE))
    edges = [24 / 24 * audiomix.RATE, 48 / 24 * audiomix.RATE]
    assert len(where)
    assert all(min(abs(w - e) for e in edges) <= micro + 1 for w in where), (where.min(), where.max())
    print(f"\nemendas: {len(where)} amostras diferentes, todas a até {micro} amostras de uma ponta; máximo {diff.max():.0f} passos")
    aninhar.unnest(seq, res.clips[0].id)
    assert _sound_diff(flat, mix_of(seq, tmp_path / "volta.wav")) == (0.0, 0)


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("scale", [0.5, 0.37])
def test_nesting_everything_on_a_reduced_preview_canvas(gl_engine, clips_media, qapp, scale):
    """A prévia reduzida (lados pares arredondados) também fica igual: o mesmo caminho da exportação, em tamanho menor."""
    values = _look(LOOK)
    seq = golden(clips_media, qapp)
    flat = frames_of(gl_engine, seq, values, 8, scale=scale)
    nest_all(seq)
    assert_identical(flat, frames_of(gl_engine, seq, values, 8, scale=scale), f"prévia {scale}")
