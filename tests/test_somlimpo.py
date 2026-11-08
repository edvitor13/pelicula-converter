"""Limpeza do som do clipe (`somlimpo.py`, 1.8, ARQUITETURA §44): ruído aprendido (numpy e na mixagem de verdade),
zumbido da rede, cortes de graves/agudos, predefinições do "eq" e nivelar a voz."""

from __future__ import annotations

import math
import os
import wave

import numpy as np
import pytest

from pelicula import audiomix, editparams, somlimpo
from pelicula import timeline as tl

R = 48000


def tone_and_noise(kind="white", secs=3.0, noise_db=-40.0, tone_db=-20.0, onset=1.0, seed=1):
    """Ruído estéreo o tempo todo e um tom de 1 kHz (RMS `tone_db`) a partir de `onset`."""
    rng = np.random.default_rng(seed)
    n = int(secs * R)
    t = np.arange(n) / R
    if kind == "white":
        noise = rng.standard_normal((n, 2))
    else:  # rosa, de 20 Hz para cima
        spec = np.fft.rfft(rng.standard_normal((n, 2)), axis=0)
        f = np.fft.rfftfreq(n, 1 / R)
        spec *= np.where(f >= 20, 1 / np.sqrt(np.maximum(f, 1)), 0)[:, None]
        noise = np.fft.irfft(spec, n, axis=0)
        noise /= noise.std(axis=0)
    tone = np.where(t >= onset, 10 ** (tone_db / 20) * math.sqrt(2) * np.sin(2 * np.pi * 1000 * t), 0.0)
    return noise * 10 ** (noise_db / 20) + tone[:, None]


def rms_db(x) -> float:
    return 20 * math.log10(math.sqrt(float(np.mean(np.square(x)))))


def tone_at(x, a, b, freq=1000.0) -> complex:
    """Amplitude complexa do seno de `freq` em [a, b) s (lock-in)."""
    i0, i1 = int(a * R), int(b * R)
    t = np.arange(i0, i1) / R
    return 2 * complex(np.mean(np.asarray(x[i0:i1], np.float64) * np.exp(-2j * np.pi * freq * t)))


# ------------------------------------------------------------------ redução em numpy
@pytest.mark.parametrize("kind", ["white", "pink"])
def test_learned_noise_drops_and_tone_keeps_its_level(kind):
    x = tone_and_noise(kind)
    prof = somlimpo.learn_profile(x[int(0.1 * R):int(0.9 * R)])
    y = somlimpo.denoise(x, prof, 1.0)
    assert y.shape == x.shape
    drop = rms_db(y[int(0.2 * R):int(0.8 * R)]) - rms_db(x[int(0.2 * R):int(0.8 * R)])
    assert drop <= -15.0, drop
    for ch in (0, 1):
        level = 20 * math.log10(abs(tone_at(y[:, ch], 1.5, 2.5)) / abs(tone_at(x[:, ch], 1.5, 2.5)))
        assert abs(level) < 0.5, level
    half = somlimpo.denoise(x, prof, 0.5)  # a força é em dB: metade tira cerca da metade
    mid = rms_db(half[int(0.2 * R):int(0.8 * R)]) - rms_db(x[int(0.2 * R):int(0.8 * R)])
    assert drop < mid < -5.0


def test_processing_in_blocks_equals_processing_at_once():
    x = tone_and_noise(secs=2.0, onset=0.7)
    prof = somlimpo.learn_profile(x[:int(0.5 * R)])
    whole = somlimpo.denoise(x, prof, 0.8, block=len(x) + somlimpo.HOP)
    for block in (somlimpo.HOP, 7 * somlimpo.HOP, 1 << 15):
        assert np.abs(somlimpo.denoise(x, prof, 0.8, block=block) - whole).max() < 1e-9, block
    mono = somlimpo.denoise(x[:, 0], prof, 0.8, block=5 * somlimpo.HOP)
    assert mono.shape == (len(x),)


def test_zero_strength_is_the_input():
    x = tone_and_noise(secs=1.0, onset=0.5)
    prof = somlimpo.learn_profile(x[:int(0.4 * R)])
    assert np.abs(somlimpo.denoise(x, prof, 0.0) - x).max() < 1e-9  # reconstrução exata
    assert somlimpo.floor_for(0.0) == 1.0 and somlimpo.floor_for(1.0) == pytest.approx(10 ** (-30 / 20))


def test_profile_refused_when_silent_or_short():
    with pytest.raises(somlimpo.CleanError, match="não tem som"):
        somlimpo.learn_profile(np.zeros((R, 2)))
    with pytest.raises(somlimpo.CleanError, match="curto"):
        somlimpo.learn_profile(tone_and_noise(secs=0.2, onset=9))
    quiet = tone_and_noise(secs=1.0, noise_db=-75.0, onset=9)
    with pytest.raises(somlimpo.CleanError):
        somlimpo.learn_profile(quiet)


# ------------------------------------------------------------------ esquema, JSON e o grafo
def test_new_keys_are_neutral_and_sparse():
    base = editparams.AUDIO.defaults()
    new = ("ruido_perfil", "ruido_ini", "ruido_fim", "zumbido", "zumbido_harmonicos", "passa_alta", "passa_baixa",
           "nivelar_voz")
    assert {k: base[k] for k in new} == {"ruido_perfil": 0.0, "ruido_ini": 0.0, "ruido_fim": 0.0, "zumbido": "nao",
                                         "zumbido_harmonicos": 6, "passa_alta": 0.0, "passa_baixa": 0.0,
                                         "nivelar_voz": 0.0}
    assert set(new) <= editparams.SPARSE_KEYS
    stored = editparams.stored_values("audio", base)
    assert not set(new) & set(stored)
    stored = editparams.stored_values("audio", {**base, "zumbido": "60", "ruido_perfil": 0.5})
    assert stored["zumbido"] == "60" and stored["ruido_perfil"] == 0.5 and "ruido_ini" not in stored
    assert [s.key for s in editparams.AUDIO_SECTIONS] == ["som", "eq", "tempo", "limpar"]  # só no fim
    eq = next(s for s in editparams.AUDIO_SECTIONS if s.key == "eq")
    assert [p.key for p in eq.params][:6] == ["graves", "medios", "agudos", "voz", "reducao_ruido", "normalizar"]
    from pelicula.ui import edit_panels
    order = [s.key for s in edit_panels.display_order(editparams.AUDIO_SECTIONS)]
    assert order == ["som", "eq", "limpar", "tempo"]


def fake(tmp_path, *names):
    out = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b"x")
        out.append(str(p))
    return out


def audio_seq(paths, secs=3.0) -> tl.Sequence:
    seq = tl.Sequence(640, 360, "24/1")
    for p in paths:
        seq.add_source(tl.Source(p, fps=24.0, frames=1, duration=secs, has_video=False, has_audio=True))
    return seq


def place(seq, path, start, dur, src_in, track=0, **vals) -> tl.Clip:
    c = tl.Clip(tl.new_id(), tl.AUDIO, path, track, start, dur, src_in, values=vals)
    seq.clips.append(c)
    return c


def test_defaults_and_zero_strength_keep_the_graph(tmp_path):
    (a,) = fake(tmp_path, "a.wav")
    seq = audio_seq([a])
    c = place(seq, a, 0, 48, 0.5)
    before = audiomix.build_graph(seq)
    for vals in ({"ruido_ini": 0.1, "ruido_fim": 0.9}, {"ruido_perfil": 0.7}, {"zumbido_harmonicos": 3},
                 {"ruido_perfil": 0.0, "ruido_ini": 0.1, "ruido_fim": 0.9}):
        seq.set_values(c.id, {**editparams.AUDIO.defaults(), **vals})
        assert audiomix.build_graph(seq) == before, vals
    seq.set_values(c.id, editparams.AUDIO.defaults())
    text = str(seq.to_json())
    assert "ruido_" not in text and "zumbido" not in text and "passa_" not in text and "nivelar" not in text


def test_clean_input_substitutes_the_path_and_offsets(tmp_path):
    (a,) = fake(tmp_path, "a.wav")
    seq = audio_seq([a], secs=30.0)
    c = place(seq, a, 24, 48, 7.3, ruido_perfil=0.6, ruido_ini=0.2, ruido_fim=1.0)
    (seg,) = audiomix.segments(seq)
    job = seg["clean"]
    assert job["source"] == a and job["lo"] == 6.0 and job["hi"] == 10.5   # 7,3 − 1 → 6; 9,3 + 1 → 10,5
    assert seg["path"].startswith(str(somlimpo.clean_dir())) and seg["src_in"] == pytest.approx(1.3)
    inputs, _graph = audiomix.build_graph(seq)
    assert inputs[inputs.index(seg["path"]) - 4] == "1.3"
    # o nome muda com a força, o trecho do ruído e o arquivo; o mesmo pedido dá o mesmo nome
    assert audiomix.segments(seq)[0]["path"] == seg["path"]
    seq.set_values(c.id, {**c.values, "ruido_perfil": 0.7})
    assert audiomix.segments(seq)[0]["path"] != seg["path"]
    # rampa/reverso: os pedaços vêm para o tempo do WAV limpo
    seq.set_values(c.id, {**c.values, "ruido_perfil": 0.6})
    c.reverse = True
    (rs,) = audiomix.segments(seq)
    lo = rs["clean"]["lo"]
    assert rs["length"] == pytest.approx(rs["clean"]["hi"] - lo)
    assert min(min(p[2], p[3]) for p in rs["pieces"]) >= 0.0


# ------------------------------------------------------------------ mixagem de verdade
def write_wav16(path, x) -> str:
    x = np.asarray(x)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(R)
        w.writeframes(np.round(np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return str(path)


def mixed(seq, path) -> np.ndarray:
    assert audiomix.render_mix(seq, str(path))
    r = audiomix.WavReader(str(path))
    return r.read(0, r.frames).astype(np.float64)


@pytest.mark.ffmpeg
def test_mix_cleans_the_clip_input(ffmpeg_ok, tmp_path, monkeypatch):
    monkeypatch.setattr(somlimpo, "clean_dir", lambda: tmp_path / "limpos")
    src = write_wav16(tmp_path / "fala.wav", tone_and_noise(secs=3.0, onset=1.0))
    seq = audio_seq([src], secs=3.0)
    c = place(seq, src, 0, 60, 0.25)   # 0,25–2,75 s do arquivo
    plain = mixed(seq, tmp_path / "antes.wav")
    seq.set_values(c.id, {**c.values, "ruido_perfil": 1.0, "ruido_ini": 0.1, "ruido_fim": 0.9})
    clean = mixed(seq, tmp_path / "depois.wav")
    assert len(clean) == len(plain)
    # na sequência: ruído só até 0,75 s, o tom depois
    drop = rms_db(clean[int(0.1 * R):int(0.6 * R)]) - rms_db(plain[int(0.1 * R):int(0.6 * R)])
    assert drop <= -15.0, drop
    a, b = tone_at(plain[:, 0], 1.2, 2.2), tone_at(clean[:, 0], 1.2, 2.2)
    assert abs(20 * math.log10(abs(b) / abs(a))) < 0.5
    assert abs(np.angle(b / a)) < 0.05  # mesmo instante: o deslocamento do WAV limpo está certo (1 amostra = 0,13)
    made = sorted(os.listdir(tmp_path / "limpos"))
    assert len(made) == 1 and made[0].endswith(".wav")
    again = mixed(seq, tmp_path / "de_novo.wav")   # o cache serve e a saída é a mesma
    assert sorted(os.listdir(tmp_path / "limpos")) == made and np.array_equal(again, clean)


@pytest.mark.ffmpeg
def test_mix_cancel_and_profile_that_became_silent(ffmpeg_ok, tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(somlimpo, "clean_dir", lambda: tmp_path / "limpos")
    x = tone_and_noise(secs=2.0, onset=1.0)
    x[:int(0.6 * R)] = 0.0   # o trecho do ruído ficou mudo: a mixagem não limpa, sai igual ao arquivo
    src = write_wav16(tmp_path / "a.wav", x)
    seq = audio_seq([src], secs=2.0)
    c = place(seq, src, 0, 48, 0.0)
    plain = mixed(seq, tmp_path / "antes.wav")
    seq.set_values(c.id, {**c.values, "ruido_perfil": 1.0, "ruido_ini": 0.1, "ruido_fim": 0.5})
    same = mixed(seq, tmp_path / "depois.wav")
    assert np.abs(same - plain).max() < 1e-4
    seq.set_values(c.id, {**c.values, "ruido_perfil": 0.9})
    stop = threading.Event()
    stop.set()
    assert not audiomix.render_mix(seq, str(tmp_path / "cancelado.wav"), cancel=stop)
    assert not [f for f in os.listdir(tmp_path / "limpos") if f.endswith(".wav") and "." in f[:-4]]


# ------------------------------------------------------------------ o trecho do botão "Aprender o ruído"
def test_learn_range_rules(tmp_path):
    (a,) = fake(tmp_path, "a.wav")
    seq = audio_seq([a], secs=30.0)
    c = place(seq, a, 48, 120, 2.0)    # quadros 48–168 = 2–7 s do arquivo
    assert somlimpo.learn_range(seq, c, 60, 72, 96) == pytest.approx((3.0, 4.0))   # entrada/saída dentro
    assert somlimpo.learn_range(seq, c, 60, 24, 96) == pytest.approx((2.5, 3.5))   # entrada fora: 1 s do cursor
    assert somlimpo.learn_range(seq, c, 160, None, None) == pytest.approx((6.0, 7.0))  # recua no fim do clipe
    with pytest.raises(somlimpo.CleanError, match="cursor"):
        somlimpo.learn_range(seq, c, 10, None, None)
    with pytest.raises(somlimpo.CleanError, match="curto"):
        somlimpo.learn_range(seq, c, 60, 72, 76)   # 4 quadros < 0,25 s
    short = place(seq, a, 300, 4, 0.0)            # o clipe inteiro tem menos de 0,25 s
    with pytest.raises(somlimpo.CleanError, match="curto"):
        somlimpo.learn_range(seq, short, 301, None, None)


# ------------------------------------------------------------------ zumbido da rede
def hum(base, secs=3.0, harmonics=6, amp=0.05) -> np.ndarray:
    t = np.arange(int(secs * R)) / R
    return sum(amp / k * np.sin(2 * np.pi * base * k * t + k) for k in range(1, harmonics + 1))


def music(secs=3.0) -> np.ndarray:
    """Notas que não são harmônicas da rede (e duas a ±10% de 60 Hz, onde o entalhe já não pode mexer)."""
    t = np.arange(int(secs * R)) / R
    return sum(0.05 * np.sin(2 * np.pi * f * t) for f in (54.0, 66.0, 220.0, 330.0, 440.0, 587.3, 880.0))


def test_hum_filters_text():
    assert somlimpo.hum_filters({"zumbido": "nao", "zumbido_harmonicos": 6}) == []
    got = somlimpo.hum_filters({"zumbido": "50", "zumbido_harmonicos": 3})
    assert got == ["bandreject=f=50:width_type=q:width=20", "bandreject=f=100:width_type=q:width=20",
                   "bandreject=f=150:width_type=q:width=20"]


@pytest.mark.ffmpeg
def test_hum_notches_remove_the_hum_and_keep_the_rest(ffmpeg_ok, tmp_path):
    x = hum(60.0) + music()
    src = write_wav16(tmp_path / "zumbido.wav", np.repeat(x[:, None], 2, axis=1))
    seq = audio_seq([src], secs=3.0)
    c = place(seq, src, 0, 72, 0.0)
    before = mixed(seq, tmp_path / "antes.wav")[:, 0]
    seq.set_values(c.id, {**c.values, "zumbido": "60", "zumbido_harmonicos": 6})
    graph = audiomix.build_graph(seq)[1]
    assert graph.index("bandreject=f=60:") < graph.index("atrim")
    after = mixed(seq, tmp_path / "depois.wav")[:, 0]
    for k in range(1, 7):
        drop = 20 * math.log10(abs(tone_at(after, 1.0, 2.5, 60.0 * k)) / abs(tone_at(before, 1.0, 2.5, 60.0 * k)))
        assert drop <= -30.0, (k, drop)
    for f in (54.0, 66.0, 220.0, 330.0, 440.0, 587.3, 880.0):
        kept = 20 * math.log10(abs(tone_at(after, 1.0, 2.5, f)) / abs(tone_at(before, 1.0, 2.5, f)))
        assert abs(kept) < 1.0, (f, kept)


def test_hum_detection():
    rng = np.random.default_rng(5)
    rate = somlimpo.HUM_RATE
    t = np.arange(3 * rate) / rate
    noise = rng.standard_normal(len(t)) * 0.02
    voice = 0.1 * np.sin(2 * np.pi * 180 * t) * (1 + np.sin(2 * np.pi * 3 * t))   # uma "voz" que oscila
    for base in (50, 60):
        x = noise + voice + sum(0.02 / k * np.sin(2 * np.pi * base * k * t) for k in (1, 2, 3))
        assert somlimpo.detect_hum(x, rate) == str(base)
    m = sum(0.05 * np.sin(2 * np.pi * f * t) for f in (220.0, 330.0, 440.0, 523.3))
    assert somlimpo.detect_hum(noise + m, rate) is None
    assert somlimpo.detect_hum(noise, rate) is None
    both = noise + sum(0.02 * np.sin(2 * np.pi * f * t) for f in (50, 100, 150, 60, 120, 180))
    assert somlimpo.detect_hum(both, rate) is None   # os dois parecidos: não escolhe


@pytest.mark.ffmpeg
def test_hum_detection_reads_the_file(ffmpeg_ok, tmp_path):
    src = write_wav16(tmp_path / "h.wav", np.repeat((hum(50.0) + music())[:, None], 2, axis=1))
    assert somlimpo.detect_hum_file(src, 0.0, 3.0) == "50"
    silent = write_wav16(tmp_path / "s.wav", np.zeros((R, 2)))
    assert somlimpo.detect_hum_file(silent, 0.0, 1.0) is None
