"""Música na montagem (`musica.py`, 1.8, ARQUITETURA §46): batidas no tempo da sequência (aparar, velocidade, rampa,
reverso), ímã nas batidas, o plano de encaixar a música numa duração e o de abaixá-la sob a voz."""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import batidas, musica
from pelicula import timeline as tl

FPS = 24


def grid_beats(bpm: float = 120.0, secs: float = 60.0, first: float = 0.0, phase: int = 0) -> batidas.Beats:
    """Batidas exatas a `bpm` desde `first`; o compasso começa na batida `phase`."""
    per = 60.0 / bpm
    times = tuple(first + i * per for i in range(int((secs - first) / per) + 1))
    return batidas.Beats(times, bpm, times[phase::4], 1.0, (bpm / 2, bpm * 2), 1.0, secs)


def music_seq(secs: float = 60.0, start: int = 0, src_in: float = 0.0, dur: int | None = None,
              speed: float = 1.0) -> tuple[tl.Sequence, tl.Clip]:
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    seq.add_source(tl.Source("musica.wav", fps=float(FPS), frames=int(secs * FPS), duration=secs, has_video=False,
                             has_audio=True))
    c = tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, start, dur or int((secs - src_in) * FPS), src_in,
                values={"velocidade": speed})
    seq.clips.append(c)
    return seq, c


# ------------------------------------------------------------------ batidas no tempo da sequência
def test_beat_frames_follow_trim_and_speed():
    b = grid_beats(120)
    seq, c = music_seq(start=48, src_in=2.0, dur=120)       # começa no quadro 48 com 2 s do arquivo: 5 s de clipe
    fr = musica.beat_frames(seq, c, b)
    assert [f for f, _d in fr] == pytest.approx([48 + 12 * k for k in range(10)])
    assert [d for _f, d in fr] == [k % 4 == 0 for k in range(10)]   # 2,0 s é começo de compasso (batida 4)
    seq.set_speed(c.id, 2.0)                                   # 2×: uma batida a cada 6 quadros, no mesmo começo
    c = seq.find(c.id)
    fr = musica.beat_frames(seq, c, b)
    assert fr[0][0] == pytest.approx(48) and np.allclose(np.diff([f for f, _d in fr]), 6)
    assert all(48 <= f < c.end for f, _d in fr)
    # rampa e reverso: o mapa exato do clipe (o quadro em que o arquivo passa pela batida)
    seq, c = music_seq(start=0, src_in=10.0, dur=96)
    seq.retime(c.id, reverse=True)
    c = seq.find(c.id)
    rev = musica.beat_frames(seq, c, b)
    assert len(rev) == 8 and rev[0][0] == pytest.approx(0)    # de 10 s para trás: 10; 9,5; … 6,5
    for f, _d in rev:
        s = seq.time_map(c).src_at((f - c.start) / FPS)
        assert abs(s * 2 - round(s * 2)) < 1e-6
    seq, c = music_seq(start=0, src_in=0.0, dur=240)
    seq.retime(c.id, ramp=[[0.0, 1.0], [10.0, 2.0]])
    c = seq.find(c.id)
    m = seq.time_map(c)
    for f, _d in musica.beat_frames(seq, c, b):
        s = m.src_at((f - c.start) / FPS)
        assert abs(s * 2 - round(s * 2)) < 1e-6           # cada marca cai exatamente numa batida do arquivo


def test_snap_frames_skip_the_dragged_clip():
    b = grid_beats(120)
    seq, c = music_seq(start=7, dur=48)
    pts = musica.snap_frames(seq, lambda p: b if p == "musica.wav" else None)
    assert {7, 19, 31, 43} <= pts and 55 not in pts          # só dentro do clipe
    assert musica.snap_frames(seq, lambda p: b, exclude=[c.id]) == set()
    assert musica.snap_frames(seq, lambda p: None) == set()


# ------------------------------------------------------------------ encaixar a música numa duração
def played_downbeats(plan, b, speed=1.0, fps=FPS):
    """Quadros da sequência em que cada começo de compasso toca, pedaço por pedaço."""
    out = []
    for p in plan.pieces:
        u1 = p.src_in + p.dur / fps * speed
        out += [p.start + (d - p.src_in) / speed * fps for d in b.downbeats if p.src_in - 1e-9 <= d < u1 - 1e-9]
    return out


def check_joints(plan, b, speed=1.0, fps=FPS):
    downs = np.array(b.downbeats)
    for prev, p in zip(plan.pieces, plan.pieces[1:]):
        assert p.start == prev.start + prev.dur                       # sem buraco nem sobreposição
        assert np.min(np.abs(downs - p.src_in)) < speed / fps         # entra num começo de compasso
        out = prev.src_in + prev.dur / fps * speed
        assert np.min(np.abs(downs - out)) < speed / fps              # e sai noutro
        assert p.transition == pytest.approx(60.0 / b.bpm / speed, abs=1e-3)   # uma batida de transição


def test_fit_shortens_by_whole_bars_in_the_middle():
    b = grid_beats(120)                                     # compassos de 2 s
    seq, c = music_seq(60.0)
    plan = musica.fit_plan(b, c, 30 * FPS, FPS)
    assert plan.ok and plan.removed == 15 and plan.added == 0
    assert plan.pieces[0].start == 0 and plan.end == 30 * FPS
    assert len(plan.pieces) == 2 and plan.pieces[0].src_in == 0.0
    assert plan.pieces[1].src_in + plan.pieces[1].dur / FPS == pytest.approx(60.0)   # o final natural inteiro
    cut_at = plan.pieces[0].dur / FPS
    assert 10.0 <= cut_at <= 16.0 and 40.0 <= plan.pieces[1].src_in <= 46.0         # o corte é no meio
    check_joints(plan, b)
    assert plan.fade_out == 0.0                             # nada cortado do fim
    # duração que não é um número inteiro de compassos: o resto sai do fim, com a saída suave
    plan = musica.fit_plan(b, c, int(31.3 * FPS), FPS)
    assert plan.ok and plan.end == int(31.3 * FPS) and plan.fade_out == musica.FADE_S
    check_joints(plan, b)


def test_fit_lengthens_by_repeating_bars_and_keeps_the_tempo():
    b = grid_beats(128, secs=40.0, first=0.3)               # compasso de 1,875 s, a 25 qps: emendas fora da grade
    fps = 25
    seq = tl.Sequence(640, 360, f"{fps}/1")
    seq.add_source(tl.Source("musica.wav", fps=25.0, frames=1000, duration=40.0, has_video=False, has_audio=True))
    c = tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, 10, 950, 1.0)
    seq.clips.append(c)
    for target in (1200, 1650, 4000):                       # um bloco, o meio quase todo, o meio repetido várias vezes
        plan = musica.fit_plan(b, c, target, fps)
        assert plan.ok and plan.added > 0 and plan.end == 10 + target, target
        check_joints(plan, b, fps=fps)
        bar = 4 * 60.0 / 128 * fps
        played = np.array(played_downbeats(plan, b, fps=fps))
        phase = (played - played[0]) / bar
        assert np.allclose(phase, np.round(phase), atol=1e-6)   # os compassos continuam na mesma grade
        assert plan.pieces[0].src_in == 1.0 and plan.pieces[-1].src_in < 39.0
    # a velocidade do clipe entra na conta
    seq.set_speed(c.id, 2.0)
    c = seq.find(c.id)
    plan = musica.fit_plan(b, c, c.dur + 100, fps)
    assert plan.ok and plan.end == c.start + c.dur + 100
    check_joints(plan, b, speed=2.0, fps=fps)


def test_fit_refusals_and_the_simple_fade():
    b = grid_beats(120)
    seq, c = music_seq(60.0)
    shaky = batidas.Beats(b.times, b.bpm, b.downbeats, 0.2)
    plan = musica.fit_plan(shaky, c, 30 * FPS, FPS)
    assert not plan.ok and "confiáveis" in plan.reason and plan.can_fade
    plan = musica.fit_plan(b, c, 6 * FPS, FPS)              # introdução (4 s) + final (4 s) não cabem em 6 s
    assert not plan.ok and plan.can_fade
    fade = musica.fade_plan(c, 6 * FPS, FPS)
    assert fade.ok and fade.end == 6 * FPS and fade.fade_out == musica.FADE_S
    assert not musica.fade_plan(c, 70 * FPS, FPS).ok       # a saída simples não alonga
    seq, short = music_seq(8.0)                             # 4 compassos: nada no meio
    assert not musica.fit_plan(b, short, 6 * FPS, FPS).ok
    seq, c = music_seq(60.0)
    seq.retime(c.id, reverse=True)
    assert not musica.fit_plan(b, seq.find(c.id), 30 * FPS, FPS).ok


def test_fit_target_and_blockers():
    seq, c = music_seq(60.0, start=24)
    assert musica.fit_target(seq, c) is None               # sem imagem e sem trecho
    seq.add_source(tl.Source("video.mp4", 640, 360, 24.0, "24/1", 2400, 100.0, has_video=True, has_audio=False))
    v = tl.Clip(tl.new_id(), tl.VIDEO, "video.mp4", 0, 0, 30 * FPS, 0.0)
    seq.clips.append(v)
    assert musica.fit_target(seq, c) == (24, 30 * FPS)
    assert musica.fit_target(seq, c, 48, 959) == (48, 960)
    assert musica.fit_blockers(seq, c, 24, 720) == ""
    other = tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, 1500, 48, 0.0)
    seq.clips.append(other)
    assert musica.fit_blockers(seq, c, 24, 2000) != ""
    c.link = v.link = "x"
    assert "ligado" in musica.fit_blockers(seq, c, 24, 720)


def test_apply_fit_is_one_undo_step():
    from pelicula.ui.edit_model import TimelineModel
    b = grid_beats(120)
    seq, c = music_seq(60.0, start=24)
    c.values = {**c.values, "volume": -6.0, "fade_in": 1.0, "fade_out": 3.0}
    seq.set_key(c.id, "volume", 24 + 240, -3.0)
    m = TimelineModel(seq)
    plan = musica.fit_plan(b, m.seq.find(c.id), 30 * FPS, FPS)
    ids = []
    assert m.apply_edit(lambda s: ids.extend(musica.apply_fit(s, c.id, plan)))
    parts = [m.seq.find(i) for i in ids]
    assert ids[0] == c.id and len(parts) == 2
    assert [(p.start, p.dur) for p in parts] == [(q.start, q.dur) for q in plan.pieces]
    assert parts[0].values["fade_in"] == 1.0 and parts[0].values["fade_out"] == 0.0
    assert parts[1].values["fade_in"] == 0.0 and parts[1].values["fade_out"] == 3.0
    assert parts[1].values["transicao"] == pytest.approx(0.5) and parts[1].values["volume"] == -6.0
    prev, before, after = m.seq.audio_crossfade(parts[1])
    assert prev is parts[0] and before + after == pytest.approx(0.5)   # a emenda tem a transição de som
    assert m.seq.keys_of(parts[0], "volume")[0][0] == 264             # a chave fica presa à música
    m.undo()
    assert len(m.seq.clips) == 1 and m.seq.find(c.id).dur == 60 * FPS and not m.can_undo()
    assert not m.apply_edit(lambda s: None)                 # nada mudou: nenhum passo
