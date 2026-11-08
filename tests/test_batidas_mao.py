"""Correção à mão das batidas (1.8, ARQUITETURA §46.5): `batidas.corrected` (×2, ÷2, compasso de 3), a correção na
fonte (`Source.beats_fix`, JSON, formato 6 só quando não é neutra) e o encaixe com os compassos corrigidos."""

from __future__ import annotations

import json

import numpy as np
import pytest

from pelicula import batidas, musica, project
from pelicula import timeline as tl

FPS = 24


def beats(bpm: float = 100.0, n: int = 48, accents=None, phase: int = 0) -> batidas.Beats:
    """Batidas exatas; acento 2 a cada 4 batidas (a partir de `phase`), 1 nas outras; compasso de 4 na `phase`."""
    per = 60.0 / bpm
    times = tuple(0.5 + i * per for i in range(n))
    acc = tuple(accents) if accents is not None else tuple(2.0 if i % 4 == phase else 1.0 for i in range(n))
    return batidas.Beats(times, bpm, times[phase::4], 0.9, (bpm / 2, bpm * 2), 0.8, n * per + 1.0, acc)


def test_neutral_correction_is_the_same_object():
    b = beats()
    assert batidas.corrected(b) is b and batidas.corrected(b, 1.0, 4) is b
    assert batidas.corrected(b, 3.0, 5) is b                      # valor estranho vale neutro
    assert batidas.corrected_by(b, None) is b and batidas.corrected_by(b, {}) is b


def test_double_inserts_exact_midpoints():
    b = beats(90.0, n=20)
    d = batidas.corrected(b, 2.0)
    assert len(d.times) == 2 * len(b.times) - 1
    assert d.times[0::2] == b.times                                # as batidas de antes ficam como estavam
    for i in range(len(b.times) - 1):
        assert d.times[2 * i + 1] == (b.times[i] + b.times[i + 1]) / 2.0
    assert d.bpm == 180.0 and d.bar == 4 and d.confidence == b.confidence
    assert d.candidates == (90.0, 360.0)
    assert len(d.accents) == len(d.times) and d.accents[1::2] == (0.0,) * (len(b.times) - 1)
    # o compasso de 4 da batida nova cai nas batidas de antes mais fortes (índice par), a cada 4 batidas novas
    assert np.allclose(np.diff(d.downbeats), 4 * 60.0 / 180.0) and d.downbeats[0] in b.times


def test_half_keeps_the_phase_with_the_detected_downbeats():
    b = beats(180.0, n=40, phase=0)
    h = batidas.corrected(b, 0.5)
    assert h.times == b.times[0::2] and h.bpm == 90.0
    assert set(h.downbeats) <= set(b.downbeats)                    # compassos de 4 batidas novas = de 8 antigas: só
    assert len(h.downbeats) == 5                                   # os do detector (um sim, outro não) abrem compasso
    # compasso detectado na batida de índice 1 (ímpar): é a paridade que fica
    b = beats(180.0, n=40, phase=1)
    h = batidas.corrected(b, 0.5)
    assert h.times == b.times[1::2] and set(h.downbeats) <= set(b.downbeats)
    # sem compassos: fica a paridade de maior acento somado; empate, a par
    acc = [1.0, 3.0] * 20
    h = batidas.corrected(batidas.Beats(b.times, 180.0, (), 0.9, (), 0.0, 20.0, tuple(acc)), 0.5)
    assert h.times == b.times[1::2]
    h = batidas.corrected(batidas.Beats(b.times, 180.0, (), 0.9, (), 0.0, 20.0, ()), 0.5)
    assert h.times == b.times[0::2]


def test_meter_3_puts_a_downbeat_every_3_beats_on_the_strongest_accent():
    n = 48
    acc = tuple(2.0 if i % 3 == 2 else 1.0 for i in range(n))      # música em 3: o acento cai nas batidas 2, 5, 8…
    b = beats(120.0, n=n, accents=acc)
    t = batidas.corrected(b, 1.0, 3)
    assert t.bar == 3 and t.times == b.times and t.bpm == b.bpm
    assert t.downbeats == b.times[2::3] and len(t.downbeats) == 16
    assert t.bar_confidence > 0.5 and t.confidence == b.confidence
    assert np.allclose(np.diff(t.downbeats), 3 * 0.5)
    # voltar a 4 refaz os compassos de 4 por acento
    back = batidas.corrected(t, 1.0, 4)
    assert back.bar == 4 and len(back.downbeats) == 12
    # o ×2 e o compasso de 3 juntos
    both = batidas.corrected(b, 2.0, 3)
    assert both.bar == 3 and len(both.times) == 2 * n - 1 and np.allclose(np.diff(both.downbeats), 3 * 0.25)


def test_without_accents_the_first_detected_downbeat_is_kept():
    base = beats(100.0, n=24, phase=2)
    b = batidas.Beats(base.times, 100.0, base.downbeats, 0.9, (), 0.7, 20.0)      # resultado montado à mão
    t = batidas.corrected(b, 1.0, 3)
    assert t.downbeats == b.times[2::3] and t.bar_confidence == 0.7
    d = batidas.corrected(b, 2.0)
    assert b.times[2] in d.downbeats and len(d.times) == 47
    assert len(batidas.corrected(batidas.Beats(b.times[:2], 100.0, (), 0.9), 1.0, 3).downbeats) == 0   # curto demais


def test_beats_json_keeps_accents_and_bar():
    b = batidas.corrected(beats(), 2.0, 3)
    back = batidas.Beats.from_json(json.loads(json.dumps(b.to_json())))
    assert back.bar == 3 and back.accents == pytest.approx(b.accents) and back.times == pytest.approx(b.times)
    raw = beats().to_json()
    assert "batidas_por_compasso" not in raw and len(raw["acentos"]) == 48
    old = {k: v for k, v in raw.items() if k != "acentos"}               # um cache sem acentos continua legível
    assert batidas.Beats.from_json(old).accents == () and batidas.Beats.from_json(old).bar == 4


# ------------------------------------------------------------------ a correção na fonte (projeto)
def seq_with_music(fix=None) -> tuple[tl.Sequence, tl.Source]:
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    src = tl.Source("musica.wav", fps=float(FPS), frames=60 * FPS, duration=60.0, has_video=False, has_audio=True)
    src.beats_fix = dict(fix or {})
    seq.add_source(src)
    seq.clips.append(tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, 0, 60 * FPS, 0.0))
    return seq, src


def test_fix_json_round_trip_and_format_6_only_when_not_neutral():
    seq, src = seq_with_music()
    assert "batidas" not in src.to_json() and "batidas_corrigidas" not in seq.features()
    assert seq.block_format() < tl.FORMAT                                # nada novo: a 1.7 ainda abre
    data = project.Project(media_path="", sequence=seq.to_json(), mode="edicao").to_json()
    assert data["formato"] < 6
    for fix in ({"fator": 2.0}, {"fator": 0.5, "compasso": 3}, {"compasso": 3}):
        seq, src = seq_with_music(fix)
        assert src.to_json()["batidas"] == fix
        back = tl.Sequence.from_json(json.loads(json.dumps(seq.to_json())))
        assert back.sources["musica.wav"].beats_fix == fix
        assert "batidas_corrigidas" in seq.features() and seq.block_format() == tl.FORMAT
        data = project.Project(media_path="", sequence=seq.to_json(), mode="edicao").to_json()
        assert data["formato"] == 6 and "batidas_corrigidas" in data["recursos"]
    src.beats_fix = {}
    assert "batidas_corrigidas" not in seq.features()


def test_fix_from_json_keeps_only_valid_values():
    load = lambda v: tl.Source.from_json({"caminho": "a.wav", "batidas": v}).beats_fix  # noqa: E731
    assert load({"fator": 2, "compasso": 3}) == {"fator": 2.0, "compasso": 3}
    assert load({"fator": 1, "compasso": 4}) == {}                       # neutro não é guardado
    assert load({"fator": 3, "compasso": 5}) == {} and load({"fator": "2"}) == {} and load({"fator": True}) == {}
    assert load("texto") == {} and load(None) == {}
    assert tl.Source.from_json({"caminho": "a.wav"}).beats_fix == {}


def test_fit_plan_uses_the_corrected_bars():
    raw = beats(120.0, n=121, accents=[2.0 if i % 4 == 0 else 1.0 for i in range(121)])
    seq, _src = seq_with_music()
    clip = seq.clips[0]
    meter3 = batidas.corrected_by(raw, {"compasso": 3})
    plan = musica.fit_plan(meter3, clip, 40 * FPS, FPS)
    assert plan.ok
    downs = np.array(meter3.downbeats)
    for p in plan.pieces[1:]:
        assert np.min(np.abs(downs - p.src_in)) < 1.0 / FPS            # corta num começo de compasso de 3
    plan4 = musica.fit_plan(raw, clip, 40 * FPS, FPS)
    assert [p.src_in for p in plan.pieces] != [p.src_in for p in plan4.pieces]
