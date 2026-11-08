"""Efeitos sonoros feitos pelo app (sfx.py, 1.8, ARQUITETURA §47): síntese determinística, nível, tamanho, a mixagem
(o efeito entra como a entrada derivada de um clipe de som, `audiomix.segments` + `somcache`), JSON e formato 6."""

from __future__ import annotations

import json

import numpy as np
import pytest

from pelicula import audiomix, modules, project, sfx
from pelicula import timeline as tl

FPS = "25/1"
RATE = sfx.RATE


def data_of(eid: str, **over) -> dict:
    eff = sfx.EFFECTS[eid]
    return {"efeito": eid, **{f.key: f.default for f in eff.fields}, **over}


def seq_with_effect(eid: str, start: int = 0, dur: int = 25, src_in: float = 0.0, **over):
    seq = tl.Sequence(640, 360, FPS, micro_fade=False)
    src = sfx.new_source(eid, seq, **over)
    seq.add_source(src)
    seq.add_track(tl.AUDIO)
    c = tl.Clip(tl.new_id(), tl.AUDIO, src.path, 0, start, dur, src_in)
    seq.clips.append(c)
    return seq, src, c


def read(path) -> np.ndarray:
    r = audiomix.WavReader(str(path))
    return r.read(0, r.frames).astype(np.float64)


def onsets(x: np.ndarray, thresh: float, gap: int) -> list[int]:
    """Amostras onde o som passa de `thresh` depois de `gap` amostras abaixo dele."""
    a = np.abs(x).max(axis=1)
    out, last = [], -gap - 1
    for i in np.flatnonzero(a > thresh):
        if i - last > gap:
            out.append(int(i))
        last = i
    return out


# ------------------------------------------------------------------ síntese
def test_every_kind_is_deterministic_and_the_seed_changes_it():
    for eid, eff in sfx.EFFECTS.items():
        n = int(min(eff.seconds, 1.5) * RATE)
        a = sfx.render(data_of(eid), n)
        b = sfx.render(data_of(eid), n)
        assert a.dtype == np.float32 and a.shape == (n, 2), eid
        assert np.array_equal(a, b), eid
        other = sfx.render(data_of(eid, semente=2), n)
        assert not np.array_equal(a, other), eid


def test_peak_and_rms_are_sane_at_every_intensity():
    for eid, eff in sfx.EFFECTS.items():
        n = int(eff.seconds * RATE)
        full = sfx.render(data_of(eid, intensidade=1.0), n)
        assert np.isfinite(full).all(), eid
        peak = float(np.abs(full).max())
        assert sfx.PEAK * 0.95 <= peak <= sfx.PEAK + 1e-6, (eid, peak)  # nunca satura
        rms_db = 20 * np.log10(float(np.sqrt(np.mean(full.astype(np.float64) ** 2))))
        assert -45.0 < rms_db < -6.0, (eid, rms_db)
        half = sfx.render(data_of(eid, intensidade=0.5), n)
        assert abs(float(np.abs(half).max()) - 0.5 * sfx.PEAK) < 1e-3, eid
        assert not sfx.render(data_of(eid, intensidade=0.0), n).any(), eid
        assert np.abs(full[-1]).max() < 1e-3, eid  # o fim nunca é um degrau


def test_width_zero_is_mono_and_brightness_moves_the_spectrum():
    x = sfx.render(data_of("whoosh", largura=0.0), RATE).astype(np.float64)
    assert np.abs(x[:, 0] - x[:, 1]).max() < 1e-5

    def centroid(y):
        s = np.abs(np.fft.rfft(y[:, 0].astype(np.float64)))
        f = np.fft.rfftfreq(len(y), 1 / RATE)
        return float((s * f).sum() / s.sum())

    dark = centroid(sfx.render(data_of("whoosh", brilho=0.0), RATE))
    bright = centroid(sfx.render(data_of("whoosh", brilho=1.0), RATE))
    assert bright > dark * 1.5


def test_click_and_shutter_are_short_and_silent_after():
    for eid, limit in (("clique", 0.05), ("obturador", 0.4)):
        x = sfx.render(data_of(eid), RATE)
        tail = np.abs(x[int(limit * RATE):]).max()
        assert tail < 1e-4, (eid, tail)
    x = sfx.render(data_of("obturador", intervalo=150.0), RATE)
    hits = onsets(x, 0.05, int(0.03 * RATE))
    assert len(hits) == 2 and abs(hits[1] - hits[0] - int(0.15 * RATE)) < int(0.003 * RATE)


def test_typewriter_hits_the_given_times_and_fills_the_clip():
    toques = [0.1, 0.25, 0.4, 0.9]
    x = sfx.render(data_of("maquina", toques=toques, sino=False), int(1.2 * RATE))
    hits = onsets(x, 0.02, int(0.05 * RATE))
    assert len(hits) == len(toques)
    for h, t in zip(hits, toques):
        assert abs(h - t * RATE) < 0.002 * RATE
    # sem toques: bate o clipe inteiro no ritmo (o tamanho do clipe é o da máquina)
    long = sfx.render(data_of("maquina", ritmo=10.0, sino=False), 3 * RATE)
    hits = onsets(long, 0.02, int(0.03 * RATE))
    assert 24 <= len(hits) <= 36 and hits[-1] > 2.6 * RATE
    times, rets = sfx.typewriter_times(sfx.values(sfx.EFFECTS["maquina"], data_of("maquina", ritmo=20.0)), 3.0, 1)
    assert rets and all(times[0] <= r <= times[-1] for r in rets)  # o sino no fim de cada linha


def test_unknown_kind_is_silence_and_bad_values_fall_back():
    assert not sfx.render({"efeito": "nao_existe"}, 1000).any()
    assert sfx.render({"efeito": "whoosh"}, 0).shape == (0, 2)
    v = sfx.values(sfx.EFFECTS["whoosh"], {"intensidade": "x", "brilho": 9, "toques": [0.2, "a", -1, 0.1]})
    assert v["intensidade"] == 0.7 and v["brilho"] == 1.0
    assert sfx.values(sfx.EFFECTS["maquina"], {"toques": [0.2, "a", -1, 0.1]})["toques"] == [0.1, 0.2]


# ------------------------------------------------------------------ a fonte e o clipe
def test_new_source_is_sound_only_unbounded_and_has_the_kind_length():
    seq = tl.Sequence(640, 360, FPS)
    for eid, eff in sfx.EFFECTS.items():
        src = sfx.new_source(eid, seq)
        assert src.kind == sfx.KIND and not src.has_video and src.has_audio and src.unbounded
        assert src.is_generated and not src.is_file
        assert seq.default_dur(src) == seq.frames_for(eff.seconds)
    made = seq.insert_media(sfx.new_source("riser", seq), at=10)
    assert [c.kind for c in made] == [tl.AUDIO] and made[0].dur == 75 and made[0].start == 10


def test_json_round_trip_and_format_6():
    seq, src, _c = seq_with_effect("maquina", toques=[0.1, 0.2], auto="sfx_auto:x")
    back = tl.Sequence.from_json(json.loads(json.dumps(seq.to_json())))
    s2 = back.sources[src.path]
    assert s2.kind == sfx.KIND and not s2.has_video and s2.has_audio and s2.data == src.data
    assert "efeito_sonoro" in seq.features() and seq.block_format() == tl.FORMAT_18
    p = project.Project(media_path="", sequence=seq.to_json(), mode="edicao")
    data = p.to_json()
    assert data["formato"] == project.FORMAT_18 == 6 and "efeito_sonoro" in data["recursos"]
    plain = tl.Sequence(640, 360, FPS)
    assert "efeito_sonoro" not in plain.features()
    assert "efeitos_sonoros" in modules.used_by({}, seq)
    assert "titulos_geradores" not in modules.used_by({}, seq)


def test_mix_key_follows_the_effect_fields():
    seq, src, _c = seq_with_effect("whoosh")
    k0 = audiomix.mix_key(seq)
    src.data = dict(src.data, brilho=0.9)
    assert audiomix.mix_key(seq) != k0
    src.data = dict(src.data, nome="Outro nome", brilho=0.5, auto="x")
    assert audiomix.mix_key(seq) == k0  # o nome e a marca do "Pôr efeitos sonoros…" não mudam o som
    assert audiomix.has_audio(seq)


def test_segment_points_at_the_effect_wav_over_the_clip_span():
    seq, src, c = seq_with_effect("whoosh", start=5, dur=25, src_in=0.4)
    (seg,) = audiomix.segments(seq)
    job = seg["sfx"]
    assert seg["path"].startswith(str(sfx.effect_dir())) and seg["path"].endswith(".wav")
    assert job["body"] == RATE  # 25 quadros a 25 qps: o efeito ocupa o clipe
    # o começo do clipe cai no começo do corpo do efeito
    assert abs(seg["src_in"] * RATE - job["before"]) < 1
    other_seq, _s, _c = seq_with_effect("whoosh", start=5, dur=50)
    assert audiomix.segments(other_seq)[0]["path"] != seg["path"]  # o trecho muda o WAV


# ------------------------------------------------------------------ a mixagem
def test_the_mix_plays_the_effect_like_a_file(ffmpeg_ok, tmp_path):
    """O efeito sai da mixagem (cache por clipe + soma) igual à síntese, no lugar certo, com o volume do clipe."""
    seq, src, c = seq_with_effect("whoosh", start=10, dur=25, src_in=0.4)
    out = tmp_path / "mix.wav"
    assert audiomix.render_mix(seq, str(out))
    got = read(out)
    want = sfx.render(src.data, RATE).astype(np.float64)
    at = int(10 / 25 * RATE)
    assert np.abs(got[:at]).max() < 1e-6
    seg = got[at: at + RATE]
    assert len(seg) == RATE
    assert np.abs(seg - want).max() < 1e-4  # 24 bits
    c.values = {**c.values, "volume": -6.0}
    out2 = tmp_path / "mix2.wav"
    assert audiomix.render_mix(seq, str(out2))
    quieter = read(out2)[at: at + RATE]
    assert np.abs(quieter - want * 10 ** (-6 / 20)).max() < 1e-3


def test_the_old_single_graph_also_renders_the_effect(ffmpeg_ok, tmp_path):
    seq, src, c = seq_with_effect("impacto", start=0, dur=25)
    new, old = tmp_path / "novo.wav", tmp_path / "antigo.wav"
    assert audiomix.render_mix(seq, str(new))
    assert audiomix.render_mix_graph(seq, str(old))
    a, b = read(new), read(old)
    assert len(a) == len(b) and np.abs(a - b).max() < 3 / 8388608.0


@pytest.mark.parametrize("eid", ["maquina"])
def test_the_typewriter_clip_length_is_the_clip(ffmpeg_ok, tmp_path, eid):
    seq, src, c = seq_with_effect(eid, start=0, dur=75, sino=False)
    out = tmp_path / "m.wav"
    assert audiomix.render_mix(seq, str(out))
    x = read(out)
    assert len(x) >= 3 * RATE - 2
    assert np.abs(x[int(2.5 * RATE): 3 * RATE]).max() > 0.01  # ainda batendo perto do fim do clipe
