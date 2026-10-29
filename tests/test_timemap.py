"""Tempo dos clipes: rampa de velocidade e reverso (`timemap.py` e o uso em `timeline.Sequence`). Sem ffmpeg."""

from __future__ import annotations

import json
import math

import pytest

from pelicula import timemap
from pelicula import timeline as tl
from pelicula.timemap import TimeMap

RAMP = [(1.0, 1.0), (2.0, 0.25), (3.0, 0.25), (4.0, 2.0)]


def _seq(frames=240, fps=24.0, audio=True):
    src = tl.Source("C:/v/a.mp4", 320, 180, fps, f"{int(fps)}/1", frames, frames / fps, has_audio=audio)
    seq = tl.Sequence.for_source(src)
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    a = next((c for c in seq.clips if c.kind == tl.AUDIO), None)
    return seq, v, a


def _frames(seq, c):
    return [seq.src_frame(c, t) for t in range(c.start, c.end)]


# ------------------------------------------------------------------ o mapa
def test_without_ramp_the_map_is_the_plain_line():
    m = TimeMap(2.0, 1.5)
    for x in (-1.0, 0.0, 0.25, 3.0):
        assert m.src_at(x) == pytest.approx(2.0 + 1.5 * x)
        assert m.out_at(m.src_at(x)) == pytest.approx(x)
    r = TimeMap(5.0, 2.0, reverse=True)
    assert r.src_at(1.0) == pytest.approx(3.0) and r.out_at(3.0) == pytest.approx(1.0)
    assert r.room_after(10.0) == pytest.approx(2.5) and r.room_before(10.0) == pytest.approx(2.5)
    assert m.room_after(10.0) == pytest.approx(8.0 / 1.5) and m.room_before(10.0) == pytest.approx(2.0 / 1.5)


def test_ramp_is_monotonic_continuous_and_exactly_invertible():
    for rev in (False, True):
        m = TimeMap(0.5 if not rev else 4.5, 1.25, RAMP, rev)
        xs = [i * 0.01 for i in range(0, 600)]
        ss = [m.src_at(x) for x in xs]
        steps = [b - a for a, b in zip(ss, ss[1:])]
        assert all(d < 0 for d in steps) if rev else all(d > 0 for d in steps)
        for x, s in zip(xs, ss):
            assert m.out_at(s) == pytest.approx(x, abs=1e-9)
        for x in xs[1:-1:7]:  # a derivada é a velocidade efetiva (V × r)
            h = 1e-5
            num = abs(m.src_at(x + h) - m.src_at(x - h)) / (2 * h)
            assert num == pytest.approx(m.rate_at(x), rel=1e-4)


def test_ramp_closed_form_matches_numeric_integration():
    m = TimeMap(0.0, 1.0, RAMP)
    for s in (1.3, 2.0, 2.7, 3.5, 4.0, 5.0):
        n = 20000
        lo = 1.0
        acc = sum((s - lo) / n / m.r_at(lo + (i + 0.5) * (s - lo) / n) for i in range(n))
        assert m.G(s) == pytest.approx(acc, rel=1e-6)
    # entre duas âncoras a velocidade varia em linha reta no tempo da saída
    x0, x1 = m.out_at(3.0), m.out_at(4.0)
    mid = (x0 + x1) / 2
    assert m.rate_at(mid) == pytest.approx((0.25 + 2.0) / 2, rel=1e-6)


def test_clean_ramp_and_json():
    assert timemap.clean_ramp([[1, 1], [2, 1.0]]) == []                  # tudo a 1×: não é rampa
    assert timemap.clean_ramp([[2, 0.5], [1, 3], ["x", 1], [-1, 2], [3, 0]]) == [(1.0, 3.0), (2.0, 0.5)]
    assert timemap.clean_ramp([[0, 1e-9], [1, 1e9]]) == [(0.0, timemap.R_MIN), (1.0, timemap.R_MAX)]
    assert timemap.clean_ramp("lixo") == [] and timemap.clean_ramp(None) == []
    assert timemap.ramp_json([(1.0, 0.25)]) == [[1.0, 0.25]]


def test_presets_shapes():
    slow, fast = 1 / (1 + 3 * 0.5), 1 + 3 * 0.5
    for pid in timemap.PRESET_IDS:
        an = timemap.preset_anchors(pid, 2.0, 6.0)
        assert an and all(2.0 <= s <= 6.0 for s, _r in an), pid
    rs = lambda pid: [r for _s, r in timemap.preset_anchors(pid, 0.0, 10.0)]  # noqa: E731
    assert rs("acelerar") == [1.0, pytest.approx(fast)] and rs("desacelerar") == [1.0, pytest.approx(slow)]
    assert rs("impacto") == [pytest.approx(fast), pytest.approx(slow), pytest.approx(slow), pytest.approx(fast)]
    assert rs("lento_meio") == [1.0, pytest.approx(slow), pytest.approx(slow), 1.0]
    assert rs("entrada_lenta")[0] == pytest.approx(slow) and rs("entrada_lenta")[-1] == 1.0
    assert rs("saida_lenta")[0] == 1.0 and rs("saida_lenta")[-1] == pytest.approx(slow)
    # a duração de cada transição sai em segundos do arquivo
    an = timemap.preset_anchors("desacelerar", 0.0, 10.0, ramp_s=2.0)
    assert an[1][0] - an[0][0] == pytest.approx(2.0)
    # no reverso a forma é a mesma na ordem em que o clipe toca
    fw = timemap.preset_anchors("saida_lenta", 0.0, 10.0)
    rv = timemap.preset_anchors("saida_lenta", 0.0, 10.0, reverse=True)
    assert [(10.0 - s, r) for s, r in reversed(rv)] == [(pytest.approx(s), r) for s, r in fw]
    with pytest.raises(KeyError):
        timemap.preset_shape("nada")


# ------------------------------------------------------------------ na sequência
def test_ramp_keeps_the_picture_range_and_changes_the_duration():
    seq, v, a = _seq()
    before = _frames(seq, v)
    ramp = timemap.preset_anchors("lento_meio", 0.0, 10.0)
    assert seq.retime(v.id, ramp=ramp)
    m = TimeMap(0.0, 1.0, ramp)
    assert v.dur == round(m.out_at(10.0) * 24) and v.dur > 240
    assert (a.start, a.dur, a.ramp, a.src_in) == (v.start, v.dur, v.ramp, v.src_in), "o som ligado acompanha"
    fr = _frames(seq, v)
    assert fr[0] == before[0] and before[-1] - 1 <= fr[-1] <= before[-1]  # a duração é arredondada ao quadro
    assert all(b >= x for x, b in zip(fr, fr[1:]))
    assert set(before[:-1]) <= set(fr), "câmera lenta mostra todos os quadros do trecho"
    for t in range(v.start, v.end, 13):
        assert seq.src_time(a, t) == seq.src_time(v, t)
    assert not seq.retime(v.id, ramp=ramp)                                # nada mudou
    assert seq.retime(v.id, ramp=[]) and v.dur == 240 and _frames(seq, v) == before and not v.ramp


def test_ramp_follows_split_trim_and_speed():
    seq, v, _a = _seq()
    seq.retime(v.id, ramp=timemap.preset_anchors("impacto", 0.0, 10.0, amount=0.8))
    before = {t: seq.src_frame(v, t) for t in range(v.start, v.end)}
    ramp = list(v.ramp)
    seq.split(150)
    left, right = sorted((c for c in seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    assert right.ramp == ramp and left.ramp == ramp
    for t in range(0, before.__len__()):
        c = left if t < right.start else right
        assert seq.src_frame(c, t) == before[t], t
    assert seq.continues(left, right), "o corte não mexido continua o arquivo (sem estalo)"
    seq.trim_start(right.id, right.start + 30)                       # a rampa fica presa à imagem
    for t in range(right.start, right.end):
        assert seq.src_frame(right, t) == before[t]
    seq.trim_end(left.id, left.end - 20)
    for t in range(left.start, left.end):
        assert seq.src_frame(left, t) == before[t]
    d0 = left.dur
    seq.set_speed(left.id, 2.0)
    assert left.dur == round(d0 / 2) and left.ramp == ramp
    assert seq.src_frame(left, left.start) == before[0]


def test_ramp_does_not_invade_the_next_clip():
    seq, v, a = _seq()
    nxt, = seq.insert_media(seq.sources[v.src], at=240, with_audio=False)
    seq.retime(v.id, ramp=timemap.preset_anchors("desacelerar", 0.0, 10.0))
    assert v.end == nxt.start == 240 and a.dur == v.dur
    assert seq.src_frame(v, 0) == 0


def test_json_round_trip_and_untouched_projects():
    seq, v, _a = _seq()
    plain = seq.to_json()
    assert not any("rampa" in c or "reverso" in c for c in plain["clipes"]) and "rampa" not in seq.features()
    seq.retime(v.id, ramp=RAMP)
    d = seq.to_json()
    assert "rampa" in seq.features() and d["formato"] == tl.FORMAT_15
    vj = next(c for c in d["clipes"] if c["tipo"] == tl.VIDEO)
    assert vj["rampa"] == timemap.ramp_json(RAMP)
    back = tl.Sequence.from_json(json.loads(json.dumps(d)))
    vb = next(c for c in back.clips if c.kind == tl.VIDEO)
    assert vb.ramp == v.ramp and _frames(back, vb) == _frames(seq, v)
    assert back.to_json() == d
    assert tl.Sequence.for_source(seq.sources[v.src]).is_trivial() and seq.is_trivial() is None


def test_magnetic_main_track_pushes_after_a_slower_ramp():
    from pelicula.ui.edit_model import TimelineModel
    seq, v, _a = _seq()
    seq.insert_media(seq.sources[v.src], at=240)
    m = TimelineModel(seq)
    m.seq.magnetic = True
    v = next(c for c in m.seq.clips if c.kind == tl.VIDEO and c.start == 0)
    second = next(c for c in m.seq.clips if c.kind == tl.VIDEO and c.start == 240)
    assert m.apply_ramp_preset(v.id, "lento_meio", 0.6, 1.0)
    v = m.seq.find(v.id)
    assert v.dur > 240 and m.seq.find(second.id).start == v.end, "a V1 magnética empurra o resto"
    m.undo()
    assert m.seq.find(v.id).dur == 240 and not m.seq.find(v.id).ramp and m.seq.find(second.id).start == 240
    assert not m.apply_ramp_preset("nada-disso", "impacto")


def test_images_and_frozen_clips_have_no_ramp():
    seq, v, _a = _seq()
    vals = dict(v.values, congelar=True)
    seq.set_values(v.id, vals)
    assert not seq.retime(v.id, ramp=RAMP)
    img = tl.Source("C:/v/foto.png", 320, 180, 24.0, "24/1", 1, 0.0, is_image=True)
    clip, = seq.insert_media(img, at=500)
    assert not seq.retime(clip.id, ramp=RAMP)


def test_audio_graph_with_a_ramp_has_constant_speed_pieces(tmp_path, monkeypatch):
    from pelicula import audiomix, media
    path = tmp_path / "a.mp4"
    path.write_bytes(b"x")
    src = tl.Source(str(path), 320, 180, 24.0, "24/1", 240, 10.0, has_audio=True)
    seq = tl.Sequence.for_source(src)
    monkeypatch.setattr(media, "ffmpeg", lambda: "ffmpeg")
    plain = audiomix.build_graph(seq)
    assert "asplit" not in plain[1] and "q0_" not in plain[1]
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    seq.retime(v.id, ramp=timemap.preset_anchors("desacelerar", 0.0, 10.0, ramp_s=1.0))
    seg, = audiomix.segments(seq)
    pcs = seg["pieces"]
    assert pcs[0][0] == 0.0 and pcs[-1][1] == pytest.approx(seg["clip_len"])
    assert all(math.isclose(a[1], b[0]) for a, b in zip(pcs, pcs[1:])), "pedaços colados, sem buraco"
    assert 5 < len(pcs) < 60
    ins, graph = audiomix.build_graph(seq)
    assert graph.count("atempo=") >= len(pcs) - 2 and "amix" in graph and graph.endswith("[out]")
    assert ins.count("-i") == 2  # o silêncio + um bloco do arquivo (10 s cabem num bloco)


def test_ramp_round_trip_at_the_file_end_keeps_every_frame():
    seq, v, a = _seq()
    before = _frames(seq, v)
    for pid in timemap.PRESET_IDS:
        lo, hi = seq.source_range(v)
        assert (lo, hi) == (0.0, 10.0)
        seq.retime(v.id, ramp=timemap.preset_anchors(pid, lo, hi, amount=1.0, ramp_s=1.0))
        assert seq.source_range(v) == (0.0, 10.0), pid
        seq.retime(v.id, ramp=[])
        assert v.dur == a.dur == 240 and _frames(seq, v) == before, pid


# ------------------------------------------------------------------ reverso
def test_reverse_is_the_exact_mirror_and_toggles_back():
    seq, v, a = _seq()
    seq.trim_start(v.id, 30)
    seq.trim_end(v.id, 200)
    before = _frames(seq, v)
    plain = seq.to_json()
    assert seq.retime(v.id, reverse=True)
    assert v.reverse and a.reverse and (v.start, v.dur) == (30, 170) and (a.start, a.dur) == (30, 170)
    assert _frames(seq, v) == before[::-1]
    assert seq.src_time(v, v.start) == pytest.approx(200 / 24) and seq.src_time(v, v.end) == pytest.approx(30 / 24)
    assert "reverso" in seq.features() and seq.is_trivial() is None
    d = seq.to_json()
    assert next(c for c in d["clipes"] if c["tipo"] == tl.VIDEO)["reverso"] is True
    back = tl.Sequence.from_json(json.loads(json.dumps(d)))
    vb = next(c for c in back.clips if c.kind == tl.VIDEO)
    assert vb.reverse and _frames(back, vb) == before[::-1]
    assert seq.retime(v.id, reverse=False) and _frames(seq, v) == before and seq.to_json() == plain


def test_reverse_with_speed_split_and_trim():
    seq, v, _a = _seq()
    seq.set_speed(v.id, 2.0)
    fwd = _frames(seq, v)
    seq.retime(v.id, reverse=True)
    assert v.dur == 120 and _frames(seq, v) == fwd[::-1]
    whole = {t: seq.src_frame(v, t) for t in range(v.start, v.end)}
    seq.split(50)
    left, right = sorted((c for c in seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    assert left.reverse and right.reverse and seq.continues(left, right)
    assert {t: seq.src_frame(left if t < 50 else right, t) for t in range(0, 120)} == whole
    seq.trim_start(right.id, 70)                       # aparar continua mostrando o mesmo quadro no mesmo lugar
    assert all(seq.src_frame(right, t) == whole[t] for t in range(right.start, right.end))
    seq.trim_end(left.id, 40)
    assert all(seq.src_frame(left, t) == whole[t] for t in range(left.start, left.end))
    head, tail = seq.source_room(left)
    assert head == pytest.approx((10.0 - seq.src_time(left, left.start)) / 2.0)  # o que sobra "antes" é o fim
    assert tail == pytest.approx(seq.src_time(left, left.end) / 2.0)
    assert seq.max_dur(left) == pytest.approx(round(seq.src_time(left, left.start) * 24 / 2), abs=1)


def test_reverse_and_ramp_combine_and_the_ramp_stays_on_the_picture():
    seq, v, _a = _seq()
    ramp = timemap.preset_anchors("entrada_lenta", 0.0, 10.0, amount=0.8)
    seq.retime(v.id, ramp=ramp)
    fwd = _frames(seq, v)
    seq.retime(v.id, reverse=True)
    rev = _frames(seq, v)
    assert v.ramp == timemap.clean_ramp(ramp) and abs(len(rev) - len(fwd)) <= 1
    assert sorted(set(rev)) == sorted(set(fwd)) or set(rev) ^ set(fwd) <= {fwd[-1], 239}
    m = seq.time_map(v)
    assert m.rate_at(0.05) == pytest.approx(1.0) and m.rate_at(v.dur / 24 - 0.05) < 0.5  # lento agora no fim
    seq.retime(v.id, reverse=False)
    assert _frames(seq, v) == fwd


def test_reverse_l_cut_audio_moves_before_the_picture_without_eating_the_neighbour():
    seq, v, a = _seq()
    seq.trim_start(v.id, 48)
    seq.trim_end_only(v.id, 200)       # o som continua 40 quadros depois da imagem (corte L)
    assert (v.start, v.end, a.start, a.end) == (48, 200, 48, 240)
    seq.retime(v.id, reverse=True)     # no espelho, o som do fim do trecho vem antes da imagem
    assert (v.start, v.end) == (48, 200) and a.end == 200 and a.start == 8
    for t in range(v.start, v.end):
        assert seq.src_time(a, t) == pytest.approx(seq.src_time(v, t))
    seq.retime(v.id, reverse=False)
    assert (v.start, v.end, a.start, a.end) == (48, 200, 48, 240)
    # com um clipe de som antes, o som que viria antes da imagem é aparado (não come o vizinho)
    seq.retime(v.id, reverse=False)
    music = tl.Source("C:/v/musica.wav", 0, 0, 24.0, "24/1", 20, 20 / 24, has_audio=True, has_video=False)
    nb, = seq.insert_media(music, at=0)
    assert nb.kind == tl.AUDIO and nb.track == a.track and (nb.start, nb.end) == (0, 20)
    seq.retime(v.id, reverse=True)
    assert (nb.start, nb.end) == (0, 20) and a.start == 20 and a.end == 200
    for t in range(a.start, a.end):
        assert seq.src_time(a, t) == pytest.approx(seq.src_time(v, t))


def test_audio_graph_reverse_splits_long_clips_into_bounded_blocks(tmp_path, monkeypatch):
    from pelicula import audiomix, media
    path = tmp_path / "longo.mp4"
    path.write_bytes(b"x")
    src = tl.Source(str(path), 320, 180, 24.0, "24/1", 24 * 25, 25.0, has_audio=True)
    seq = tl.Sequence.for_source(src)
    monkeypatch.setattr(media, "ffmpeg", lambda: "ffmpeg")
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    seq.retime(v.id, reverse=True)
    ins, graph = audiomix.build_graph(seq)
    assert graph.count("areverse") == ins.count("-i") - 1 >= 3, "um bloco de até 10 s por entrada"
    spans = [float(ins[i + 1]) for i, x in enumerate(ins) if x == "-t"][1:]
    assert max(spans) <= audiomix.GROUP_S + 0.2 and sum(spans) >= 25.0
    assert "atempo" not in graph


def test_freezing_a_reversed_clip_holds_its_first_shown_frame():
    seq, v, _a = _seq()
    seq.trim_end(v.id, 100)
    seq.retime(v.id, reverse=True)
    first = seq.src_frame(v, v.start)
    assert first == 99
    seq.set_values(v.id, dict(v.values, congelar=True))
    assert {seq.src_frame(v, t) for t in range(v.start, v.end)} == {first}
