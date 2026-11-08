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
