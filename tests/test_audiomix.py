"""Mixagem do som da sequência (audiomix.py): grafo de filtros, chave da prévia e render real."""

from __future__ import annotations

import subprocess
import wave

import numpy as np
import pytest

from pelicula import audiomix, media
from pelicula import timeline as tl


def fake_files(tmp_path, *names):
    out = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b"x")
        out.append(str(p))
    return out


def seq_with(paths, frames=48):
    seq = tl.Sequence()
    for p in paths:
        seq.insert_media(tl.Source(p, 320, 180, 24.0, "24/1", frames, frames / 24, has_audio=True))
    return seq


@pytest.mark.parametrize("speed, chain", [(1.0, []), (2.0, ["atempo=2"]), (0.25, ["atempo=0.5", "atempo=0.5"]),
                                          (3.0, ["atempo=2", "atempo=1.5"]), (8.0, ["atempo=2"] * 3)])
def test_atempo_chain(speed, chain):
    assert audiomix._atempo(speed) == chain


def test_no_audio_gives_none(tmp_path):
    seq = tl.Sequence()
    seq.insert_media(tl.Source(str(tmp_path / "x.png"), 10, 10, is_image=True))
    assert audiomix.build_graph(seq) is None and not audiomix.has_audio(seq)
    (a,) = fake_files(tmp_path, "a.mp4")
    seq = seq_with([a])
    seq.kind_tracks(tl.AUDIO)[0].muted = True
    assert audiomix.build_graph(seq) is None
    assert audiomix.build_graph(seq_with(["nao_existe.mp4"])) is None


def test_graph_structure(tmp_path):
    a, b = fake_files(tmp_path, "a.mp4", "b.mp4")
    seq = seq_with([a, b])
    clips = [c for c in seq.clips if c.kind == tl.AUDIO]
    seq.set_values(clips[1].id, {**clips[1].values, "volume": -6.0, "fade_in": 0.5, "fade_out": 0.25,
                                 "balanco": -0.5, "graves": 3.0, "medios": -2.0, "agudos": 4.0, "voz": True,
                                 "reducao_ruido": 0.5, "normalizar": True})
    seq.kind_tracks(tl.AUDIO)[0].volume = 2.0
    seq.set_speed(clips[1].id, 2.0)
    inputs, graph = audiomix.build_graph(seq)
    assert inputs[:6] == ["-f", "lavfi", "-t", "3", "-i", "anullsrc=r=48000:cl=stereo"]
    # o clipe a 2× usa os 2 s do arquivo em 1 s (24 quadros) da sequência
    assert inputs.count("-i") == 3 and inputs[inputs.index(b) - 2] == "2"
    for piece in ("volume=-4dB", "afade=t=in:st=0:d=0.5", "afade=t=out:st=0.75:d=0.25", "pan=stereo|c0=1*c0|c1=0.5*c1",
                  "bass=g=3", "equalizer=f=1200", "treble=g=4", "highpass=f=90", "acompressor", "afftdn",
                  "loudnorm", "atempo=2", "adelay=2000|2000", "amix=inputs=3:duration=first", "normalize=0",
                  "atrim=duration=3[out]"):
        assert piece in graph, piece
    assert "volume=2dB" in graph  # primeiro clipe: só o volume da faixa


def test_range_trims_and_delays(tmp_path):
    a, b = fake_files(tmp_path, "a.mp4", "b.mp4")
    seq = seq_with([a, b])  # a: 0–48, b: 48–96
    segs = audiomix.segments(seq, 36, 60)
    assert len(segs) == 2
    first, second = segs
    assert first["trim_start"] == pytest.approx(1.5) and first["trim_len"] == pytest.approx(0.5)
    assert second["delay"] == pytest.approx(0.5) and second["trim_len"] == pytest.approx(0.5)
    _inputs, graph = audiomix.build_graph(seq, 36, 60)
    assert "atrim=start=1.5:duration=0.5" in graph and "adelay=500|500" in graph and "atrim=duration=1[out]" in graph
    assert audiomix.segments(seq, 96, 120) == []


def test_mix_key_follows_only_audio(tmp_path):
    (a,) = fake_files(tmp_path, "a.mp4")
    seq = seq_with([a])
    k0 = audiomix.mix_key(seq)
    v = [c for c in seq.clips if c.kind == tl.VIDEO][0]
    seq.set_values(v.id, {**v.values, "exposicao": 2.0})
    assert audiomix.mix_key(seq) == k0
    au = [c for c in seq.clips if c.kind == tl.AUDIO][0]
    seq.set_values(au.id, {**au.values, "volume": -3.0})
    assert audiomix.mix_key(seq) != k0


def test_mix_key_is_the_same_on_the_copy(tmp_path):
    """A janela calcula a chave numa cópia; se a do modelo fosse outra, a mixagem nova seria jogada fora (#51)."""
    a, b, d = fake_files(tmp_path, "a.mp4", "b.mp4", "d.mp4")
    seq = seq_with([a, b, d])
    assert audiomix.mix_key(seq) == audiomix.mix_key(seq.copy())
    first = next(c for c in seq.clips if c.src == a and c.kind == tl.VIDEO)
    seq.delete([first.id])  # a fonte continua na montagem sem clipe; a cópia não a leva
    assert a in seq.sources and a not in seq.copy().sources
    assert audiomix.mix_key(seq) == audiomix.mix_key(seq.copy())
    last = next(c for c in seq.clips if c.src == d and c.kind == tl.VIDEO)
    seq.move(last.id, 0)  # a ordem da lista deixa de ser a ordem no tempo; a cópia grava em ordem de tempo
    seq.move(next(c.id for c in seq.clips if c.src == b and c.kind == tl.VIDEO), 500)
    assert audiomix.mix_key(seq) == audiomix.mix_key(seq.copy())
    au = next(c for c in seq.clips if c.src == d and c.kind == tl.AUDIO)
    seq.move(au.id, au.start, 1)  # outra faixa
    assert audiomix.mix_key(seq) == audiomix.mix_key(seq.copy())
    assert seq.retime(au.id, reverse=True)  # reverso: a entrada do clipe é gravada com mais casas
    assert audiomix.mix_key(seq) == audiomix.mix_key(seq.copy())


def test_mix_key_ignores_a_source_without_clip(tmp_path):
    a, b = fake_files(tmp_path, "a.mp4", "b.mp4")
    seq = seq_with([a])
    k0 = audiomix.mix_key(seq)
    seq.add_source(tl.Source(b, 320, 180, 24.0, "24/1", 48, 2.0, has_audio=True))
    assert audiomix.mix_key(seq) == k0


def _tone_file(ffmpeg, path, freq, secs):
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={secs}",
                    "-c:a", "pcm_s16le", str(path)], check=True, timeout=60)
    return media.probe_source(str(path))


def _heard(path, t0=0.2, t1=0.8):
    reader = audiomix.WavReader(str(path))
    x = reader.read(int(t0 * reader.rate), int((t1 - t0) * reader.rate))
    x = x[:, 0] if x.ndim > 1 else x
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(spectrum) * reader.rate / len(x)), float(np.sqrt(np.mean(x ** 2)))


@pytest.mark.ffmpeg
def test_mix_after_deleting_moving_and_changing_track(ffmpeg_ok, tmp_path):
    """O que a exportação grava depois de apagar o 1º clipe: o som do que ficou, com volume e faixa (#51)."""
    seq = tl.Sequence()
    for name, freq in (("a.wav", 440), ("b.wav", 1000)):
        seq.insert_media(_tone_file(ffmpeg_ok, tmp_path / name, freq, 2))
    a, b = [str(tmp_path / n) for n in ("a.wav", "b.wav")]
    seq.delete([next(c.id for c in seq.clips if c.src == a)])
    clip = next(c for c in seq.clips if c.src == b)
    seq.move(clip.id, 0)
    assert audiomix.render_mix(seq, str(tmp_path / "1.wav"))
    freq, level = _heard(tmp_path / "1.wav")
    assert freq == pytest.approx(1000, abs=5) and level > 0.01
    seq.set_values(clip.id, {**clip.values, "volume": -6.0})
    assert audiomix.render_mix(seq, str(tmp_path / "2.wav"))
    assert 20 * np.log10(_heard(tmp_path / "2.wav")[1] / level) == pytest.approx(-6.0, abs=0.2)
    seq.move(clip.id, 0, 1)
    assert clip.track == 1
    assert audiomix.render_mix(seq, str(tmp_path / "3.wav"))
    assert _heard(tmp_path / "3.wav")[0] == pytest.approx(1000, abs=5)


@pytest.mark.parametrize("version,option", [((9, 0), "-/filter_complex"), ((7, 1, 2), "-/filter_complex"),
                                            ((6, 1, 1), "-filter_complex_script"), (None, "-/filter_complex")])
def test_long_graph_uses_script(tmp_path, monkeypatch, version, option):
    """O grafo num arquivo: `-/filter_complex` no ffmpeg 7 ou mais novo, a opção antiga no 6 (Ubuntu 24.04)."""
    from pelicula import deps
    paths = fake_files(tmp_path, *[f"c{i}.mp4" for i in range(3)])
    seq = seq_with(paths)
    ff = f"ffmpeg-{version}"
    monkeypatch.setattr(media, "ffmpeg", lambda: ff)
    monkeypatch.setattr(deps, "inspect", lambda path: deps.FFmpegInfo(path, "", version, None))
    monkeypatch.setattr(audiomix, "_SCRIPT_OPTION", {})
    script = tmp_path / "grafo.txt"
    cmd = audiomix.build_mix_cmd(seq, str(tmp_path / "o.wav"), script_path=str(script))
    assert cmd[cmd.index(option) + 1] == str(script) and "amix" in script.read_text(encoding="utf-8")
    cmd = audiomix.build_mix_cmd(seq, str(tmp_path / "o.wav"))
    assert cmd[cmd.index("-filter_complex") + 1].endswith("[out]")
    assert cmd[-1].endswith("o.wav") and "pcm_s24le" in cmd


# ------------------------------------------------------------------ ffmpeg de verdade
def _wav(path):
    with wave.open(str(path), "rb") as w:
        n, rate, ch, width = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
    samples = (data[:, 0].astype(np.int32) | (data[:, 1].astype(np.int32) << 8) | (data[:, 2].astype(np.int32) << 16))
    samples = np.where(samples >= 1 << 23, samples - (1 << 24), samples) / float(1 << 23)
    return rate, ch, width, samples.reshape(-1, ch)


@pytest.mark.ffmpeg
def test_render_mix_real(ffmpeg_ok, sample_video, tmp_path):
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    seq.insert_media(src)  # duas vezes seguidas: 2 s de som
    out = tmp_path / "mix.wav"
    assert audiomix.render_mix(seq, str(out))
    rate, ch, width, s = _wav(out)
    assert (rate, ch, width) == (48000, 2, 3)
    assert len(s) == pytest.approx(2 * 48000, abs=48)
    assert np.abs(s).max() > 0.05
    # volume -60 dB no segundo clipe: a segunda metade quase em silêncio
    second = [c for c in seq.clips if c.kind == tl.AUDIO][1]
    seq.set_values(second.id, {**second.values, "volume": -60.0})
    assert audiomix.render_mix(seq, str(out))
    _r, _c, _w, s = _wav(out)
    assert np.abs(s[: 40000]).max() > 0.05 and np.abs(s[52000:]).max() < 0.005
    # trecho do meio
    assert audiomix.render_mix(seq, str(out), 12, 36)
    _r, _c, _w, s = _wav(out)
    assert len(s) == pytest.approx(48000, abs=48)


@pytest.mark.ffmpeg
def test_render_mix_with_effects_runs(ffmpeg_ok, sample_video, tmp_path):
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    a = [c for c in seq.clips if c.kind == tl.AUDIO][0]
    seq.set_values(a.id, {**a.values, "voz": True, "reducao_ruido": 0.6, "normalizar": True, "graves": 4.0,
                          "medios": 2.0, "agudos": -3.0, "balanco": 0.7, "fade_in": 0.3, "fade_out": 0.3})
    seq.set_speed(a.id, 0.5)
    out = tmp_path / "fx.wav"
    assert audiomix.render_mix(seq, str(out))
    rate, ch, _w, s = _wav(out)
    assert len(s) == pytest.approx(seq.duration / 24 * 48000, abs=100)


@pytest.mark.ffmpeg
def test_render_mix_cancel_and_error(ffmpeg_ok, sample_video, tmp_path):
    import threading
    seq = tl.Sequence.for_source(media.probe_source(sample_video))
    ev = threading.Event()
    ev.set()
    assert audiomix.render_mix(seq, str(tmp_path / "c.wav"), cancel=ev) is False
    with pytest.raises(RuntimeError):
        audiomix.render_mix(seq, str(tmp_path / "pasta_que_nao_existe" / "x.wav"))


@pytest.mark.ffmpeg
def test_peaks(ffmpeg_ok, sample_video, sample_image):
    p = audiomix.peaks(sample_video)
    assert p is not None and p.dtype == np.float32 and len(p) == pytest.approx(100, abs=3)
    assert 0.05 < p.max() <= 1.0
    assert audiomix.peaks(sample_video) is p  # cache
    assert audiomix.peaks(sample_image) is None
    assert audiomix.peaks("nao_existe.wav") is None
