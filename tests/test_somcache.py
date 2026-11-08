"""Cache do som de cada clipe e a soma da mixagem (somcache.py, 1.8, ARQUITETURA §43).

A prova: a mixagem nova (`audiomix.render_mix` → `somcache.mix`) dá as mesmas amostras de 24 bits que o grafo único de
antes (`audiomix.render_mix_graph`), com no máximo 2 passos de diferença, em montagens com cortes, buracos, duas faixas
sobrepostas, transição, fades curtos, velocidade, rampa, reverso, tons, sequência aninhada, mudo/solo, volume da faixa
(com e sem um filtro não linear), chaves de volume e trechos do meio. As posições caem em milissegundos inteiros (25
quadros/s): o grafo antigo arredondava o `adelay` para o milissegundo; a soma põe cada clipe na amostra exata.
"""

from __future__ import annotations

import threading
import time
import wave

import numpy as np
import pytest

from pelicula import audiomix, generators, somcache
from pelicula import timeline as tl

LSB = 1.0 / 8388608.0
FPS = "25/1"


def write_wav(path, freq, secs=3.0, amp=0.4, rate=48000, seed=0) -> str:
    """Estéreo diferente nos dois canais (o balanço aparece): seno + ruído fixo."""
    t = np.arange(int(secs * rate)) / rate
    noise = np.random.default_rng(seed).standard_normal(len(t)) * 0.05
    left = amp * np.sin(2 * np.pi * freq * t) + noise
    right = amp * 0.7 * np.sin(2 * np.pi * freq * 1.5 * t + 0.3) - noise
    x = np.round(np.stack([left, right], axis=1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(x.tobytes())
    return str(path)


@pytest.fixture(scope="module")
def wavs(ffmpeg_ok, tmp_path_factory):
    d = tmp_path_factory.mktemp("somcache")
    return [write_wav(d / f"s{k}.wav", f, seed=k) for k, f in enumerate((220.0, 330.0, 523.0, 97.0))]


def seq_of(paths, micro=True, fps=FPS) -> tl.Sequence:
    seq = tl.Sequence(640, 360, fps, micro_fade=micro)
    for p in paths:
        seq.add_source(tl.Source(p, fps=25.0, frames=1, duration=3.0, has_video=False, has_audio=True))
    seq.add_track(tl.AUDIO)
    seq.add_track(tl.AUDIO)
    return seq


def place(seq, path, start, dur, src_in, track=0, **vals) -> tl.Clip:
    c = tl.Clip(tl.new_id(), tl.AUDIO, path, track, start, dur, src_in, values=vals)
    seq.clips.append(c)
    return c


def read(path) -> np.ndarray:
    r = audiomix.WavReader(str(path))
    return r.read(0, r.frames).astype(np.float64)


def both(seq, tmp_path, start=0, end=-1) -> tuple[np.ndarray, np.ndarray]:
    new, old = tmp_path / "novo.wav", tmp_path / "antigo.wav"
    assert audiomix.render_mix(seq, str(new), start, end)
    assert audiomix.render_mix_graph(seq, str(old), start, end)
    return read(new), read(old)


def assert_same(new, old, lsb=2) -> float:
    assert len(new) == len(old), (len(new), len(old))
    worst = float(np.abs(new - old).max()) / LSB
    assert worst <= lsb, f"diferença máxima de {worst:.1f} passos de 24 bits"
    return worst


# ------------------------------------------------------------------ montagens
def cuts(w) -> tl.Sequence:
    """Cortes, buraco e duas faixas sobrepostas, com ajustes lineares e o balanço do clipe."""
    seq = seq_of(w)
    place(seq, w[0], 0, 25, 0.2)
    place(seq, w[1], 25, 25, 1.0, volume=-3.0)
    place(seq, w[0], 60, 15, 2.0, fade_out=0.2)
    place(seq, w[1], 10, 35, 0.5, track=1, volume=-4.0, balanco=0.3, graves=3.0, agudos=-2.0, medios=1.5,
          fade_in=0.2, fade_out=0.3)
    place(seq, w[2], 30, 40, 0.0, track=2, balanco=-0.6)
    return seq


def montage(name, w) -> tl.Sequence:
    if name == "cortes":
        return cuts(w)
    seq = seq_of(w)
    if name == "transicao":
        place(seq, w[0], 0, 40, 0.5, fade_out=0.3)
        place(seq, w[1], 40, 35, 1.5, transicao=0.8)
        place(seq, w[2], 5, 20, 0.0, track=1)
    elif name == "velocidade":
        place(seq, w[0], 0, 20, 0.0, velocidade=1.5)
        place(seq, w[1], 20, 50, 0.0, velocidade=0.5)
    elif name == "rampa":
        c = place(seq, w[0], 0, 50, 0.0)
        assert seq.retime(c.id, ramp=[[0.0, 1.0], [0.8, 2.0]])
        place(seq, w[1], 0, 25, 0.5, track=1)
    elif name == "reverso":
        c = place(seq, w[2], 5, 40, 0.4)
        assert seq.retime(c.id, reverse=True)
    elif name == "chaves":
        c = place(seq, w[1], 0, 60, 0.0, volume=-2.0)
        seq.set_key(c.id, "volume", 0, -2.0)
        seq.set_key(c.id, "volume", 30, -20.0, "suavizar")
        seq.track(tl.AUDIO, 0).volume = -4.0
    elif name == "mudo_solo":
        place(seq, w[0], 0, 30, 0.0)
        place(seq, w[1], 0, 30, 0.0, track=1)
        place(seq, w[2], 0, 30, 0.0, track=2)
        place(seq, w[3], 10, 10, 0.0, mudo=True)
        seq.track(tl.AUDIO, 1).muted = True
        seq.track(tl.AUDIO, 0).solo = True
        seq.track(tl.AUDIO, 2).solo = True
    elif name == "volume_faixa":
        place(seq, w[0], 0, 40, 0.0, volume=-2.0)                    # linear: o ganho da faixa vai para a soma
        place(seq, w[1], 0, 40, 0.0, track=1, normalizar=True)        # não linear: fica na cadeia
        place(seq, w[2], 0, 40, 0.0, track=2, voz=True, reducao_ruido=0.4)
        seq.track(tl.AUDIO, 0).volume = 4.5
        seq.track(tl.AUDIO, 1).volume = -7.0
        seq.track(tl.AUDIO, 2).volume = 2.0
    return seq


NAMES = ["cortes", "transicao", "velocidade", "rampa", "reverso", "chaves", "mudo_solo", "volume_faixa"]


@pytest.mark.ffmpeg
@pytest.mark.parametrize("name", NAMES)
def test_cached_mix_is_the_old_graph(wavs, tmp_path, name):
    seq = montage(name, wavs)
    new, old = both(seq, tmp_path)
    assert np.abs(old).max() > 0.01
    assert_same(new, old)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("rng", [(20, 60), (13, 47), (0, 30), (45, 75)])
def test_a_middle_range_is_the_old_graph(wavs, tmp_path, rng):
    seq = cuts(wavs)
    new, old = both(seq, tmp_path, *rng)
    assert_same(new, old)
    # e é o recorte exato da mixagem inteira (o grafo antigo arredondava cada `adelay` pelo começo do trecho)
    whole, _old = both(seq, tmp_path)
    a = rng[0] * 1920
    assert np.array_equal(new, whole[a:a + len(new)])


@pytest.mark.ffmpeg
def test_tones_and_a_file(wavs, tmp_path):
    seq = seq_of(wavs[:1])
    src = generators.new_source("contagem", seq)
    seq.insert_media(src, at=0)
    place(seq, wavs[0], 100, 60, 0.0, volume=-12.0)
    new, old = both(seq, tmp_path)
    assert np.abs(new).max() > 0.05  # o bipe
    assert_same(new, old)
    new, old = both(seq, tmp_path, 140, 200)
    assert_same(new, old)


@pytest.mark.ffmpeg
def test_nested_sequence(wavs, tmp_path, monkeypatch):
    monkeypatch.setattr(audiomix, "nested_dir", lambda: tmp_path / "aninhadas")
    outer = tl.Sequence(640, 360, FPS, micro_fade=True)
    inner = outer.ensure_set().create(640, 360, FPS)
    inner.micro_fade = True
    for p in wavs:
        inner.add_source(tl.Source(p, fps=25.0, frames=1, duration=3.0, has_video=False, has_audio=True))
    inner.add_track(tl.AUDIO)
    place(inner, wavs[0], 0, 30, 0.3, volume=-3.0)
    place(inner, wavs[1], 20, 30, 0.0, track=1, balanco=0.5)
    outer.siblings.sync()
    clip = outer.insert_media(outer.sources[f"sequencia:{inner.id}"], at=10)
    aud = next(c for c in clip if c.kind == tl.AUDIO)
    outer.set_values(aud.id, {"volume": -2.0, "fade_in": 0.2})
    for p in wavs[2:3]:
        outer.add_source(tl.Source(p, fps=25.0, frames=1, duration=3.0, has_video=False, has_audio=True))
    outer.add_track(tl.AUDIO)
    place(outer, wavs[2], 0, 40, 0.0, track=1)
    new, old = both(outer, tmp_path)
    assert_same(new, old)


@pytest.mark.ffmpeg
def test_samples_are_placed_exactly_where_the_old_graph_rounded(wavs, tmp_path):
    """A 24 quadros/s um clipe no quadro 1 começa na amostra 2000 (41,67 ms); o grafo antigo usava 42 ms (2016)."""
    seq = seq_of(wavs[:1], fps="24/1")
    place(seq, wavs[0], 1, 30, 0.0)
    new, old = both(seq, tmp_path)
    assert len(new) == len(old)
    first_new = int(np.nonzero(np.abs(new[:, 0]) > 0)[0][0])
    first_old = int(np.nonzero(np.abs(old[:, 0]) > 0)[0][0])
    assert (first_new, first_old) == (2000, 2016)
    assert_same(new[2000:-16], old[2016:])


# ------------------------------------------------------------------ o cache
def _cached() -> set[str]:
    d = somcache.cache_dir()
    return {p.name for p in d.glob("*.wav")} if d.exists() else set()


@pytest.fixture
def own_cache(tmp_path, monkeypatch):
    monkeypatch.setenv(somcache.CACHE_ENV, str(tmp_path / "cache"))
    return tmp_path / "cache" / somcache.CLIP_DIR


@pytest.mark.ffmpeg
def test_moving_trimming_the_range_and_track_gain_render_nothing_new(wavs, tmp_path, own_cache, monkeypatch):
    seq = cuts(wavs)
    out = tmp_path / "o.wav"
    assert audiomix.render_mix(seq, str(out))
    first = _cached()
    assert len(first) == 5
    calls = []
    real = somcache._Job

    def job(batch, perf):
        calls.extend(p.key for p in batch)
        return real(batch, perf)

    monkeypatch.setattr(somcache, "_Job", job)
    seq.track(tl.AUDIO, 0).volume = -6.0           # cadeias lineares: o fader vai para a soma
    assert audiomix.render_mix(seq, str(out), 20, 60)  # outro trecho
    c = next(c for c in seq.clips if c.track == 2)
    c.start += 5                                   # mover o clipe sozinho (sem vizinhos): a cadeia é a mesma
    assert audiomix.render_mix(seq, str(out))
    assert calls == [] and _cached() == first
    # o volume de um clipe muda a cadeia dele, e só a dele
    seq.set_values(c.id, {"volume": -9.0})
    assert audiomix.render_mix(seq, str(out))
    assert len(calls) == 1 and len(_cached() - first) == 1


@pytest.mark.ffmpeg
def test_nonlinear_clip_keeps_the_track_gain_in_its_chain(wavs, tmp_path, own_cache, monkeypatch):
    seq = seq_of(wavs[:1])
    c = place(seq, wavs[0], 0, 40, 0.0, normalizar=True)
    assert not somcache.chain_is_linear(c.values) and somcache.chain_is_linear({**c.values, "normalizar": False})
    part, = somcache.parts(seq)
    assert not part.track_gain
    seq.track(tl.AUDIO, 0).volume = 3.0
    part2, = somcache.parts(seq)
    assert part2.key != part.key and "volume=3dB" in part2.graph[1]
    # ajuste desconhecido fora do padrão (de outra frente) conta como não linear, a não ser que se declare linear
    assert not somcache.chain_is_linear({**c.values, "normalizar": False, "novo_filtro": 0.5})
    monkeypatch.setattr(somcache, "LINEAR_KEYS", somcache.LINEAR_KEYS | {"novo_filtro"})
    assert somcache.chain_is_linear({**c.values, "normalizar": False, "novo_filtro": 0.5})


def test_part_key_follows_values_keys_and_file(tmp_path):
    a = tmp_path / "a.wav"
    a.write_bytes(b"x")
    seq = seq_of([str(a)])
    c = place(seq, str(a), 0, 25, 0.0)
    k0 = somcache.parts(seq)[0].key
    c.values["valor_de_outra_frente"] = 1  # um ajuste que o grafo ainda não usa: o hash dos valores pega
    k1 = somcache.parts(seq)[0].key
    del c.values["valor_de_outra_frente"]
    assert k1 != k0 and somcache.parts(seq)[0].key == k0
    seq.set_key(c.id, "volume", 0, -3.0)
    assert somcache.parts(seq)[0].key != k0
    c.keys = {}
    import os
    os.utime(a, (1_000_000, 1_000_000))  # o arquivo mudou no disco
    assert somcache.parts(seq)[0].key != k0


def test_wav_writer_matches_ffmpeg_rounding():
    x = np.array([[0.0, -0.0], [1.0, -1.0], [2.0, -2.0], [0.5, -0.5], [1 / 8388608, -1 / 8388608],
                  [0.4 / 8388608, -0.4 / 8388608], [0.6 / 8388608, -0.6 / 8388608]])
    v = somcache.to_s24(x)
    assert v[:, 0].tolist() == [0, 8388607, 8388607, 4194304, 1, 0, 0]
    assert v[:, 1].tolist() == [0, -8388608, -8388608, -4194304, -1, -1, -1]


@pytest.mark.ffmpeg
def test_cancel_and_error_leave_nothing(wavs, tmp_path, own_cache):
    seq = cuts(wavs)
    ev = threading.Event()
    ev.set()
    out = tmp_path / "c.wav"
    assert audiomix.render_mix(seq, str(out), cancel=ev) is False and not out.exists()
    assert _cached() == set()
    late = threading.Event()
    real = audiomix.subprocess.Popen
    seen = []

    def popen(cmd, **kw):
        seen.append(cmd)
        late.set()
        return real(cmd, **kw)

    audiomix.subprocess.Popen, keep = popen, audiomix.subprocess.Popen
    try:
        assert audiomix.render_mix(seq, str(out), cancel=late) is False
    finally:
        audiomix.subprocess.Popen = keep
    assert len(seen) == 1 and not out.exists() and not list(own_cache.glob("*.*.wav"))
    with pytest.raises(RuntimeError, match="Falha ao mixar"):
        audiomix.render_mix(seq, str(tmp_path / "pasta_que_nao_existe" / "x.wav"))


@pytest.mark.ffmpeg
def test_track_peaks_and_stems(wavs, tmp_path):
    seq = cuts(wavs)
    for k, db in enumerate((-8.0, -12.0, -9.0)):  # a soma não passa de 1 (sem corte na mixagem)
        seq.track(tl.AUDIO, k).volume = db
    stems = {}
    res = somcache.mix(seq, str(tmp_path / "m.wav"), with_peaks=True,
                       stems=lambda kind, idx: stems.setdefault((kind, idx), str(tmp_path / f"{kind}{idx}.wav")))
    assert res is not None and res.peak_tracks == [0, 1, 2] and res.peaks.shape == (-(-res.samples // 480), 3)
    master = read(res.path)
    parts = [read(p) for p in stems.values()]
    assert all(len(p) == len(master) for p in parts)
    assert np.abs(sum(parts) - master).max() <= 3 * LSB
    # o pico de cada faixa é o do stem dela (blocos de 10 ms)
    for col, (key, path) in enumerate(stems.items()):
        x = np.abs(read(path)).max(axis=1)
        x = np.concatenate([x, np.zeros(-len(x) % 480)]).reshape(-1, 480).max(axis=1)
        assert np.abs(res.peaks[:, col] - x).max() < 2e-6
    m = np.abs(master).max(axis=1)
    m = np.concatenate([m, np.zeros(-len(m) % 480)]).reshape(-1, 480).max(axis=1)
    assert np.abs(res.master_peaks - m).max() < 2e-6
    assert somcache.save_peaks(res).endswith(".faixas.npz")
    tracks, peaks, master_peaks = somcache.load_peaks(res.path)
    assert tracks == [0, 1, 2] and np.array_equal(peaks, res.peaks) and np.array_equal(master_peaks, res.master_peaks)
    assert somcache.load_peaks(str(tmp_path / "nada.wav")) is None


@pytest.mark.ffmpeg
def test_speed_of_a_ten_clip_montage(wavs, tmp_path, own_cache):
    """Não é um limite (máquinas variam): mede o antes e o depois de uma montagem de 10 clipes (os números vão para o
    relatório da 1.8) e confere que mexer no volume de um clipe renderiza só ele."""
    seq = seq_of(wavs)
    for k in range(10):
        place(seq, wavs[k % 4], k * 12, 12, 0.1 * k, track=k % 3, volume=-1.0 * k, graves=float(k % 3))
    t0 = time.perf_counter()
    assert audiomix.render_mix_graph(seq, str(tmp_path / "g.wav"))
    t_graph = time.perf_counter() - t0
    t0 = time.perf_counter()
    assert audiomix.render_mix(seq, str(tmp_path / "1.wav"))
    t_first = time.perf_counter() - t0
    c = seq.clips[4]
    seq.set_values(c.id, {"volume": -20.0})
    t0 = time.perf_counter()
    assert audiomix.render_mix(seq, str(tmp_path / "2.wav"))
    t_one = time.perf_counter() - t0
    seq.track(tl.AUDIO, 1).volume = -3.0
    t0 = time.perf_counter()
    assert audiomix.render_mix(seq, str(tmp_path / "3.wav"))
    t_fader = time.perf_counter() - t0
    print(f"\ngrafo único {t_graph:.3f} s; cache: primeira {t_first:.3f} s, um clipe {t_one:.3f} s, "
          f"fader {t_fader:.3f} s")
    assert t_fader < t_graph


# ------------------------------------------------------------------ balanço da faixa (1.8)
@pytest.mark.ffmpeg
@pytest.mark.parametrize("pan", [0.4, -0.75, 1.0])
def test_track_pan_follows_the_clip_balance_law(wavs, tmp_path, pan):
    clip = seq_of(wavs[:1])
    place(clip, wavs[0], 0, 40, 0.2, balanco=pan)
    track = seq_of(wavs[:1])
    place(track, wavs[0], 0, 40, 0.2)
    track.track(tl.AUDIO, 0).pan = pan
    a, b = tmp_path / "clipe.wav", tmp_path / "faixa.wav"
    assert audiomix.render_mix(clip, str(a)) and audiomix.render_mix(track, str(b))
    assert_same(read(b), read(a))
    assert somcache.track_gains(track, tl.AUDIO, 0)[1:] == (min(1.0, 1 - pan), min(1.0, 1 + pan))


def test_track_pan_json_format_trivial_and_key(tmp_path):
    a = tmp_path / "a.mp4"
    a.write_bytes(b"x")
    seq = tl.Sequence.for_source(tl.Source(str(a), 320, 180, 25.0, "25/1", 50, 2.0, has_audio=True))
    before = seq.to_json()
    assert seq.is_trivial() == str(a) and "balanco" not in before["faixas"][1]
    assert "balanco_faixa" not in seq.features()
    key = audiomix.mix_key(seq)
    seq.track(tl.AUDIO, 0).pan = -0.5
    d = seq.to_json()
    assert d["faixas"][1]["balanco"] == -0.5 and "balanco_faixa" in seq.features()
    assert seq.is_trivial() is None
    assert audiomix.mix_key(seq) != key and audiomix.mix_key(seq.copy()) == audiomix.mix_key(seq)
    again = tl.Sequence.from_json(d)
    assert again.track(tl.AUDIO, 0).pan == -0.5
    for raw, want in ((3, 1.0), (-9, -1.0), ("x", 0.0), (None, 0.0), (float("nan"), 0.0), (0.123, 0.12)):
        assert tl.Track.from_json({"tipo": "audio", "balanco": raw}).pan == want
    seq.track(tl.AUDIO, 0).pan = 0.0
    assert seq.to_json() == before and seq.is_trivial() == str(a)


def _two_tracks(w, pans):
    seq = seq_of(w[:2])
    for k, p in enumerate(pans):
        place(seq, w[k], 0, 40, 0.1 * k, track=k, volume=-3.0 * k)
        seq.track(tl.AUDIO, k).pan = p
    return seq


@pytest.mark.ffmpeg
@pytest.mark.parametrize("pans", [(0.5, 0.0), (-0.4, -0.4), (0.6, -0.3)])
def test_nesting_and_unnesting_keep_the_track_pan(wavs, tmp_path, monkeypatch, pans):
    from pelicula import aninhar
    monkeypatch.setattr(audiomix, "nested_dir", lambda: tmp_path / "aninhadas")
    seq = _two_tracks(wavs, pans)
    flat = tmp_path / "plano.wav"
    assert audiomix.render_mix(seq, str(flat))
    res = aninhar.nest(seq, [c.id for c in seq.clips])
    out = next(c for c in res.clips if c.kind == tl.AUDIO)
    land = seq.track(tl.AUDIO, out.track)
    inner = [t.pan for t in res.inner.kind_tracks(tl.AUDIO)]
    if pans == (0.6, -0.3):  # nenhuma faixa desconta o balanço da outra: o som cai numa faixa nova, no centro
        assert land.pan == 0.0 and inner == list(pans)
    nested = tmp_path / "aninhada.wav"
    assert audiomix.render_mix(seq, str(nested))
    assert_same(read(nested), read(flat))
    aninhar.unnest(seq, out.id)
    back = tmp_path / "desaninhada.wav"
    assert audiomix.render_mix(seq, str(back))
    assert_same(read(back), read(flat))
    got = sorted(seq.track(tl.AUDIO, c.track).pan for c in seq.clips if c.kind == tl.AUDIO)
    assert got == sorted(pans)


def test_unnest_refuses_two_pans_that_do_not_combine(tmp_path):
    from pelicula import aninhar
    a = tmp_path / "a.wav"
    a.write_bytes(b"x")
    seq = _two_tracks([str(a), str(a)], (0.5, 0.0))
    res = aninhar.nest(seq, [c.id for c in seq.clips])
    out = next(c for c in res.clips if c.kind == tl.AUDIO)
    seq.track(tl.AUDIO, out.track).pan = -0.2   # a faixa de fora ganhou balanço; a de dentro tem 0,5
    with pytest.raises(aninhar.Refusal, match="balanço"):
        aninhar.unnest(seq, out.id)
