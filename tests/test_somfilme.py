"""1.8, som de película (`somfilme.py`, ARQUITETURA §45): o motor puro em numpy.

Desligado = o som de entrada bit a bit; um trecho com o contexto antes = o mesmo pedaço do som inteiro; tudo
determinístico pela semente; a faixa de cada trilha medida; os estalos na amostra exata dos quadros em que a imagem
mostra a emenda (a mesma conta de `look.build_plan` e de `montagem_filme`); o wow segue o tremor do quadro; nada
passa de 0,98 (limite suave). Os sons de teste são gerados com numpy e têm poucos segundos.
"""

from __future__ import annotations

import math
import wave

import numpy as np
import pytest

from pelicula import look, modules, montagem_filme as mf, params, somfilme as S
from pelicula import timeline as tl
from pelicula.frame import Recipe

RATE = S.RATE


def _vals(**kw):
    return params.sanitize({"somf_on": True, **kw})


def _quiet(**kw):
    """Só o que o teste pede: sem trilha, estalos, poeira, wow, projetor e sala."""
    return _vals(**{**dict(somf_trilha_forca=0.0, somf_estalos=0.0, somf_poeira=0.0, somf_wow=0.0,
                           somf_projetor=0.0, somf_sala=0.0), **kw})


def _tones(seconds=3.0, amp=0.3):
    t = np.arange(int(seconds * RATE)) / RATE
    return np.stack([amp * np.sin(2 * np.pi * 440 * t), amp * np.sin(2 * np.pi * 659 * t + 1.0)], 1)


ALL_ON = dict(somf_projetor=0.7, somf_sala=0.6, somf_estalos=1.0, somf_poeira=1.0, somf_wow=1.0,
              desg_on=True, emenda_on=True, emenda=1.0, poeira_on=True, poeira=0.8)


# ------------------------------------------------------------------ esquema e módulo
def test_section_is_last_neutral_and_not_animatable():
    sec = params.SECTIONS[-1]
    assert sec.key == "som_pelicula" and sec.toggle == "somf_on"
    d = params.defaults()
    assert d["somf_on"] is False and d["somf_trilha"] == "auto" and d["somf_projetor"] == 0.0
    assert d["somf_sala"] == 0.0
    assert not any(p.animatable for p in sec.params)
    assert [c[0] for c in params.PARAMS["somf_trilha"].choices] == [
        "auto", "otica_35", "otica_16", "magnetica_s8", "otica_antiga"]
    assert all(p.key.startswith("somf_") for p in sec.params)
    assert params.beyond_1_7(params.FILM, params.known_1_7()["look"], d) is False
    assert params.beyond_1_7(params.FILM, params.known_1_7()["look"], {**d, "somf_on": True}) is True


def test_module_is_beta_off_and_used_by_the_look():
    m = modules.get("som_pelicula")
    assert m.status == modules.BETA and not modules.default_enabled("som_pelicula")
    assert "som_pelicula" in modules.used_by(_vals())
    assert "som_pelicula" not in modules.used_by(params.defaults())


def test_track_follows_the_gauge_in_auto():
    assert S.track_of(_vals(bitola="35mm")) == "otica_35"
    assert S.track_of(_vals(bitola="imax")) == "otica_35"
    assert S.track_of(_vals(bitola="16mm")) == "otica_16"
    assert S.track_of(_vals(bitola="super16")) == "otica_16"
    assert S.track_of(_vals(bitola="super8")) == "magnetica_s8"
    assert S.track_of(_vals(bitola="8mm")) == "magnetica_s8"
    assert S.track_of(_vals(bitola="nenhuma")) == "otica_35"
    assert S.track_of(_vals(bitola="16mm", somf_trilha="otica_antiga")) == "otica_antiga"


# ------------------------------------------------------------------ neutro, trecho e determinismo
def test_off_returns_the_input_bit_for_bit():
    x = _tones(0.5)
    assert S.process(x, RATE, params.defaults(), 24, 0) is x
    assert S.process(x, RATE, None, 24, 0) is x
    assert S.process(x, RATE, {**_vals(**ALL_ON), "somf_on": False}, 24, 1000) is x
    assert S.film_values(_vals(), no_effects=True) is None
    assert S.film_values(params.defaults()) is None
    assert S.sound_key(params.defaults()) == ""


@pytest.mark.parametrize("cfg", [dict(), ALL_ON, dict(somf_trilha="otica_antiga", **ALL_ON),
                                 dict(bitola="super8", **ALL_ON)])
def test_range_is_the_slice_of_the_whole(cfg):
    v = _vals(**cfg)
    x = _tones(3.0)
    ev = S.events_for(v, 24.0, 72)
    whole = S.process(x, RATE, v, 24.0, 0, ev)
    for a, b in ((0, 30000), (17, 9000), (RATE + 123, 2 * RATE + 7), (int(2.5 * RATE), len(x))):
        part = S.process(x[a:b], RATE, v, 24.0, a, ev, before=x[:a])
        assert np.abs(part - whole[a:b]).max() < 1e-6, (a, b)


def test_deterministic_and_seeded():
    v = _vals(**ALL_ON)
    x = _tones(1.0)
    ev = [6, 20]
    one = S.process(x, RATE, v, 24.0, 5000, ev)
    two = S.process(x.copy(), RATE, dict(v), 24.0, 5000, ev)
    assert np.array_equal(one, two)
    other = S.process(x, RATE, {**v, "somf_semente": v["somf_semente"] + 1}, 24.0, 5000, ev)
    assert np.abs(other - one).max() > 1e-3


def test_hash_and_value_noise_match_the_look():
    for i in (-7, 0, 1, 4242, 10 ** 9):
        assert S.hash_array(np.array([i]), 33)[0] == look._hash(i, 33)
    for x in (-2.75, 0.0, 0.3, 1234.5678):
        assert abs(S.vnoise_array(np.array([x]), 103)[0] - look._vnoise(x, 103)) < 1e-12


# ------------------------------------------------------------------ trilha
def _gain_db(v, freqs):
    """Ganho medido (dB) da trilha pela correlação cruzada com um ruído de entrada (o chiado somado não conta)."""
    rng = np.random.default_rng(5)
    n = 2 * RATE
    x = rng.normal(0.0, 0.03, (n, 2))
    y = S.process(x, RATE, v, 24.0, 0)
    seg = 8192
    sxy = np.zeros(seg // 2 + 1, complex)
    sxx = np.zeros(seg // 2 + 1)
    win = np.hanning(seg)
    xm = x.mean(axis=1)
    ym = y.mean(axis=1)
    for a in range(seg, n - seg, seg // 2):
        X = np.fft.rfft(xm[a:a + seg] * win)
        Y = np.fft.rfft(ym[a:a + seg] * win)
        sxy += Y * np.conj(X)
        sxx += np.abs(X) ** 2
    h = np.abs(sxy) / sxx
    f = np.fft.rfftfreq(seg, 1 / RATE)
    return [20 * math.log10(np.interp(q, f, h)) for q in freqs]


def test_band_limit_of_each_track():
    q = _quiet
    g = _gain_db(q(somf_trilha="otica_antiga", somf_trilha_forca=1.0), (1000, 5000, 8000, 12000))
    assert abs(g[0]) < 1.0 and abs(g[1] + 10) < 2.0 and abs(g[2] + 18) < 2.0 and g[3] < -35
    g = _gain_db(q(somf_trilha="otica_16", somf_trilha_forca=1.0), (1000, 6500, 10000))
    assert abs(g[0]) < 1.0 and abs(g[1] + 3) < 2.0 and g[2] < -25
    g = _gain_db(q(somf_trilha="magnetica_s8", somf_trilha_forca=1.0), (1000, 10000, 15000))
    assert abs(g[0]) < 1.0 and abs(g[1] + 3) < 2.0 and g[2] < -25
    g = _gain_db(q(somf_trilha="otica_35", somf_trilha_forca=1.0), (1000, 12000, 17000))
    assert abs(g[0]) < 1.0 and abs(g[1] + 3) < 2.0 and g[2] < -30
    g = _gain_db(q(somf_trilha="otica_antiga", somf_trilha_forca=0.5), (8000,))
    assert abs(g[0] + 9) < 2.0, "a força escala a curva em dB"


def test_mono_tracks_are_mono_and_hiss_is_there():
    x = _tones(1.0)
    y = S.process(x, RATE, _quiet(somf_trilha="otica_16", somf_trilha_forca=1.0), 24.0, 0)
    assert np.abs(y[:, 0] - y[:, 1]).max() < 1e-12
    y = S.process(np.zeros((RATE, 2)), RATE, _quiet(somf_trilha="otica_16", somf_trilha_forca=1.0), 24.0, 0)
    rms = 20 * math.log10(float(np.sqrt((y ** 2).mean())))
    assert -52 < rms < -36, rms
    y = S.process(x, RATE, _quiet(somf_trilha="otica_35", somf_trilha_forca=1.0), 24.0, 0)
    assert np.abs(y[:, 0] - y[:, 1]).max() > 0.1, "a ótica de 35 mm continua estéreo"


def test_levels_stay_below_full_scale():
    t = np.arange(2 * RATE) / RATE
    s = 10 ** (-1 / 20) * np.sin(2 * np.pi * 1000 * t)
    x = np.stack([s, s], 1)
    for cfg in (dict(), ALL_ON, dict(somf_trilha="magnetica_s8", **ALL_ON)):
        y = S.process(x, RATE, _vals(**cfg), 24.0, 0, [10, 30])
        assert np.abs(y).max() <= S.LIMIT_CEIL
        assert np.abs(y).max() > 0.5


# ------------------------------------------------------------------ eventos iguais aos da imagem
def test_emenda_frames_are_the_frames_where_the_image_shows_the_splice():
    for fps in (24.0, 25.0, 29.97):
        v = params.sanitize({"desg_on": True, "emenda_on": True, "emenda": 1.0, "poeira_on": False,
                             "riscos_on": False, "vazamento_on": False})
        n = int(40 * fps)
        image = [f for f in range(n) if look.build_plan(v, 64, 36, f, fps).uniforms["u_splice"][0] > 0]
        assert image, fps
        assert look.emenda_frames(v, fps, 0, n) == image
        assert look.emenda_frames(v, fps, image[1], n) == image[1:]
        assert look.emenda_frames({**v, "emenda_on": False}, fps, 0, n) == []


def _seq(fps="24/1"):
    seq = tl.Sequence(width=64, height=36, fps_str=fps)
    for i, at in enumerate((0, 37, 61, 110)):
        seq.insert_media(tl.Source(path=f"C:/v/c{i}.mp4", width=64, height=36, fps=24.0, frames=60,
                                   duration=2.5, has_audio=False), at=at)
    return seq


def test_montage_splice_frames_are_the_frames_of_the_tape():
    seq = _seq()
    for fps in (24.0, 25.0, 48.0):
        for vis in (1.0, 0.5):
            v = params.sanitize({"mfilme_on": True, "mfilme_emenda": vis})
            n = int(seq.duration * fps) + 2
            image = [f for f in range(n)
                     if Recipe.for_source(v, fps, 8, legal=True, seq=seq).plan(64, 36, f).uniforms["u_splice"][0] > 0]
            assert mf.splice_frames(seq, v, fps, 0, n) == image, (fps, vis)
    v = params.sanitize({"mfilme_on": True, "mfilme_emenda": 1.0})
    assert mf.splice_frames(seq, v, 24.0, 0, 200) == [37, 61, 110]
    assert mf.splice_frames(None, v, 24.0, 0, 200) == []


def test_pops_start_at_the_exact_sample_of_the_frame():
    v = _quiet(somf_estalos=1.0)
    for fps in (24.0, 29.97):
        ev = [7, 31, 50]
        y = S.process(np.zeros((3 * RATE, 2)), RATE, v, fps, 0, ev)
        nz = np.flatnonzero(np.abs(y[:, 0]) > 0)
        onsets = [int(nz[0])] + [int(nz[i]) for i in range(1, len(nz)) if nz[i] - nz[i - 1] > RATE // 10]
        assert onsets == [round(f / fps * RATE) for f in ev], fps
        assert np.abs(y[onsets[0]]).max() > 0.2
    # num trecho, o estalo continua na mesma amostra absoluta
    part = S.process(np.zeros((RATE, 2)), RATE, v, 24.0, 10000, [7])
    assert int(np.flatnonzero(np.abs(part[:, 0]) > 0)[0]) == round(7 / 24 * RATE) - 10000


def test_events_for_joins_both_sources():
    seq = _seq()
    v = params.sanitize({"somf_on": True, "mfilme_on": True, "mfilme_emenda": 1.0, "desg_on": True,
                         "emenda_on": True, "emenda": 1.0})
    ev = S.events_for(v, 24.0, 200, seq)
    assert set([37, 61, 110]) <= set(ev)
    assert set(look.emenda_frames(v, 24.0, 0, 200)) <= set(ev)
    assert ev == sorted(set(ev))


# ------------------------------------------------------------------ wow
def _delay_of(y, f0):
    """Atraso (s) de um tom de f0 Hz pela fase do sinal analítico."""
    n = len(y)
    Y = np.fft.fft(y)
    Y[n // 2 + 1:] = 0
    Y[1:n // 2] *= 2
    a = np.fft.ifft(Y)
    t = np.arange(n) / RATE
    ph = np.unwrap(np.angle(a)) - 2 * np.pi * f0 * t
    return -(ph - ph[RATE // 2:-RATE // 2].mean()) / (2 * np.pi * f0)


def test_wow_follows_the_frame_weave():
    fps = 24.0
    v = _quiet(somf_wow=1.0, bitola="super8", proj_on=True, tremor_y=4.0, tremor_vel=1.3)
    t = np.arange(6 * RATE) / RATE
    x = np.stack([0.4 * np.sin(2 * np.pi * 1000 * t)] * 2, 1)
    d = _delay_of(S.process(x, RATE, v, fps, 0)[:, 0], 1000.0)
    frames = np.arange(int(1 * fps), int(5 * fps))
    image = np.array([look.build_plan(v, 64, 36, int(f), fps).uniforms["u_shift"][1] for f in frames])
    sound = d[np.round(frames / fps * RATE).astype(int)]
    r = np.corrcoef(image, sound)[0, 1]
    assert r > 0.9, r
    # a profundidade é a da bitola: o Super 8 balança mais que o 35 mm
    d35 = _delay_of(S.process(x, RATE, {**v, "bitola": "35mm"}, fps, 0)[:, 0], 1000.0)
    assert d[RATE:-RATE].std() > 1.8 * d35[RATE:-RATE].std()


def test_wow_off_has_no_delay():
    x = _tones(0.5)
    y = S.process(x, RATE, _quiet(), 24.0, 0)
    assert np.abs(y - x).max() < 1e-12


# ------------------------------------------------------------------ em blocos, de WAV para WAV
def _write(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(3)
        w.setframerate(RATE)
        S._write_pcm24(w, x)


def test_process_wav_in_chunks_equals_process(tmp_path, monkeypatch):
    from pelicula.audiomix import WavReader
    monkeypatch.setattr(S, "CHUNK_S", 0.7)
    v = _vals(**ALL_ON)
    x = _tones(2.5)
    src = tmp_path / "a.wav"
    _write(src, x)
    xr = WavReader(str(src)).read(0, len(x)).astype(np.float64)
    ev = [9, 40]
    ref = S.process(xr, RATE, v, 24.0, 3000, ev)
    dst = tmp_path / "b.wav"
    assert S.process_wav(str(src), str(dst), v, 24.0, 3000, ev)
    got = WavReader(str(dst)).read(0, len(x)).astype(np.float64)
    assert got.shape == ref.shape
    assert np.abs(got - ref).max() < 2e-7
    # contexto antes e amostras de contexto puladas
    dst2 = tmp_path / "c.wav"
    assert S.process_wav(str(src), str(dst2), v, 24.0, 3000, ev, skip=20000)
    got2 = WavReader(str(dst2)).read(0, len(x)).astype(np.float64)
    assert np.abs(got2 - ref[20000:]).max() < 2e-7
