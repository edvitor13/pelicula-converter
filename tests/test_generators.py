"""Geradores (`pelicula/generators.py`): cor sólida, degradê e a ponta com contagem (com o bipe).

Determinismo (8 e 16 bits, `grab` = `SequenceReader` quadro a quadro), o desenho conferido por medidas (não por
hash: a ponta usa ângulo e raio do numpy, que podem variar de um ulp entre sistemas) e o bipe medido no som
mixado: começa na amostra do quadro do "2" (±1 amostra a 48 kHz).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from pelicula import audiomix, generators, sequence
from pelicula import timeline as tl

W, H = 192, 108


@pytest.fixture(autouse=True)
def _app(qapp):  # os números da ponta usam as fontes do app (Qt)
    return qapp


def seq_with(gen_id, fps="24/1", at=0, **data):
    seq = tl.Sequence(width=W, height=H, fps_str=fps)
    src = generators.new_source(gen_id, seq, **data)
    clip = seq.insert_media(src, at=at)[0]
    return seq, src, clip


# ------------------------------------------------------------------ fontes e JSON
def test_new_sources_and_json():
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    color = generators.new_source("cor", seq)
    assert color.kind == "cor" and not color.has_alpha and color.unbounded and color.data["cor"] == "#1f2a44"
    grad = generators.new_source("degrade", seq)
    assert grad.kind == "gerador" and grad.data["gerador"] == "degrade" and grad.data["cores"] == "2"
    leader = generators.new_source("contagem", seq)
    assert leader.frames == 192 and not leader.unbounded and leader.data["bipe"] is True
    assert generators.new_source("contagem", tl.Sequence(fps_str="30000/1001")).frames == 239
    for src in (color, grad, leader):
        back = tl.Source.from_json(json.loads(json.dumps(src.to_json())))
        assert back.data == src.data and generators.generator_of(back) is generators.generator_of(src)
    seq.insert_media(leader, at=0)
    assert "gerador" in seq.features()
    odd = tl.Source.virtual("gerador", W, H, data={"gerador": "nao_existe"})
    assert generators.generator_of(odd) is None


def test_fields_are_cleaned():
    gen = generators.GENERATORS["degrade"]
    v = generators.values(gen, {"forma": "espiral", "angulo": 999, "cor1": "nada", "cores": "3", "meio": "x"})
    assert v["forma"] == "linear" and v["angulo"] == 180 and v["cor1"] == "#0b1a33" and v["cores"] == "3"
    assert v["meio"] == 0.5
    leader = generators.GENERATORS["contagem"]
    assert generators.values(leader, {"bipe": "sim"})["bipe"] is True
    assert generators.values(leader, {"bipe": False})["bipe"] is False


# ------------------------------------------------------------------ desenho
def test_solid_color_is_exact():
    seq, src, clip = seq_with("cor", cor="#ff8000")
    img8 = sequence.render_source(seq, clip, 5, W, H, 8)
    img16 = sequence.render_source(seq, clip, 5, W, H, 16)
    assert img8.shape == (H, W, 3) and (img8 == np.array([255, 128, 0], np.uint8)).all()
    assert img16.dtype == np.uint16 and (img16 == np.array([65535, 32896, 0], np.uint16)).all()


def test_gradient_linear_radial_and_three_colors():
    seq, src, clip = seq_with("degrade", forma="linear", angulo=0, cor1="#000000", cor2="#ffffff")
    img = sequence.render_source(seq, clip, 0, W, H, 16).astype(np.float64) / 65535
    assert img[:, 0].max() < 0.01 and img[:, -1].min() > 0.99  # da esquerda (cor1) para a direita (cor2)
    assert np.all(np.diff(img[H // 2, :, 0]) >= 0) and np.ptp(img[:, W // 2, 0]) < 1e-9
    seq.sources[src.path].data.update(angulo=90)
    down = sequence.render_source(seq, clip, 0, W, H, 16).astype(np.float64) / 65535
    assert down[0].max() < 0.01 and down[-1].min() > 0.99  # 90°: de cima para baixo (y para baixo)
    seq.sources[src.path].data.update(forma="radial")
    rad = sequence.render_source(seq, clip, 0, W, H, 16).astype(np.float64) / 65535
    assert rad[H // 2, W // 2, 0] < 0.02 and rad[0, 0, 0] > 0.98
    seq.sources[src.path].data.update(forma="linear", angulo=0, cores="3", cor3="#ff0000", meio=0.5)
    three = sequence.render_source(seq, clip, 0, W, H, 16).astype(np.float64) / 65535
    assert np.abs(three[H // 2, W // 2] - 1.0).max() < 0.02 and np.abs(three[0, -1] - [1, 0, 0]).max() < 0.02
    # 8 bits: o pontilhado fica a menos de um código do valor exato
    img8 = sequence.render_source(seq, clip, 0, W, H, 8).astype(np.float64)
    assert np.abs(img8 - three * 255).max() <= 1.0


def test_leader_counts_8_to_2_then_black():
    for fps in (24.0, 25.0, 30000 / 1001):
        n2 = generators.two_frame(fps)
        assert n2 == int(np.ceil(6 * fps - 1e-6))
        assert generators.leader_state(0, fps) == (8, 0.0)
        assert generators.leader_state(n2 - 1, fps)[0] == 3
        assert generators.leader_state(n2, fps) == (2, 0.0)
        assert generators.leader_state(n2 + 1, fps) == (0, 0.0)
        assert generators.leader_state(int(round(fps)), fps)[0] == 7
    assert generators.leader_state(12, 24.0) == (8, 0.5)


def test_leader_frames():
    seq, src, clip = seq_with("contagem")
    half = sequence.render_source(seq, clip, 12, W, H, 8).astype(np.float64)  # "8", varredura na metade
    left, right = half[: H // 3, : W // 3].mean(), half[: H // 3, -W // 3:].mean()
    assert right < left - 30  # a metade da direita já foi varrida (sentido horário a partir do alto)
    start = sequence.render_source(seq, clip, 0, W, H, 8).astype(np.float64)
    assert abs(start[: H // 3, : W // 3].mean() - start[: H // 3, -W // 3:].mean()) < 2
    assert start[H // 2 - 20: H // 2 + 20, W // 2 - 12: W // 2 + 12].min() < 30  # o número, escuro, no centro
    assert sequence.render_source(seq, clip, 145, W, H, 8).max() == 0  # depois do "2": preto
    two = sequence.render_source(seq, clip, 144, W, H, 8)
    seven = sequence.render_source(seq, clip, 24, W, H, 8)
    assert two.max() > 200 and not np.array_equal(two, seven)


@pytest.mark.parametrize("gen_id", ["cor", "degrade", "contagem"])
def test_grab_equals_sequence_reader_in_8_and_16_bits(gen_id):
    seq, src, clip = seq_with(gen_id)
    t0 = 140 if gen_id == "contagem" else 100  # a ponta: a passagem 3 → 2 → preto
    for depth in (8, 16):
        reader = sequence.SequenceReader(seq, W, H, depth, t0, 6)
        try:
            for t in range(t0, t0 + 6):
                a = sequence.grab(seq, t, W, H, depth).layers[0].image
                b = reader.read().layers[0].image
                assert a.dtype == (np.uint8 if depth == 8 else np.uint16)
                assert np.array_equal(a, b), (gen_id, depth, t)
                assert np.array_equal(a, sequence.grab(seq, t, W, H, depth).layers[0].image)  # determinístico
        finally:
            reader.close()


def test_leader_from_a_worker_thread_matches_main():
    import threading
    seq, src, clip = seq_with("contagem")
    main = sequence.render_source(seq, clip, 30, W, H, 8)
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("img", sequence.render_source(seq, clip, 30, W, H, 8)))
    th.start()
    th.join()
    assert np.array_equal(main, out["img"])


def test_thumbnail_of_the_leader_shows_the_count():
    seq, src, clip = seq_with("contagem")
    thumb = sequence.source_thumbnail(src, 96, 54)
    assert thumb.shape == (54, 96, 3) and thumb.max() > 100


# ------------------------------------------------------------------ o bipe
def test_beep_tones_follow_the_clip():
    seq, src, clip = seq_with("contagem", at=10)
    t = audiomix.tones(seq)
    assert len(t) == 1 and t[0]["onset"] == (10 + 144) * 2000 and t[0]["samples"] == 2000
    assert t[0]["freq"] == 1000.0 and t[0]["gain_db"] == -20.0
    assert audiomix.has_audio(seq) and audiomix.tones(seq, 0, 150) == []  # trecho antes do "2": sem bipe
    part = audiomix.tones(seq, 100)
    assert part[0]["onset"] == (154 - 100) * 2000
    key = audiomix.mix_key(seq)
    seq.move(clip.id, 20)
    assert audiomix.mix_key(seq) != key and audiomix.tones(seq)[0]["onset"] == (20 + 144) * 2000
    seq.sources[src.path].data["bipe"] = False
    assert audiomix.tones(seq) == [] and not audiomix.has_audio(seq)
    seq.sources[src.path].data["bipe"] = True
    seq.track(tl.VIDEO, 0).muted = True  # faixa de vídeo escondida: sem bipe
    assert audiomix.tones(seq) == []
    plain = tl.Sequence(width=W, height=H)
    assert "tons" not in json.dumps(audiomix.build_graph(plain) or "")


@pytest.mark.ffmpeg
@pytest.mark.parametrize("fps,at,trim", [("24/1", 10, 0), ("30000/1001", 7, 0), ("25/1", 3, 40)])
def test_beep_onset_is_sample_accurate(ffmpeg_ok, tmp_path, fps, at, trim):
    seq, src, clip = seq_with("contagem", fps=fps, at=at)
    if trim:
        seq.trim_start(clip.id, trim)
        seq.move(clip.id, at)
        clip = seq.find(clip.id)
    frame = next(t for t in range(clip.start, clip.end) if seq.src_frame(clip, t) == generators.two_frame(src.fps))
    want = round(frame / seq.fps * audiomix.RATE)
    out = tmp_path / "bipe.wav"
    assert audiomix.render_mix(seq, str(out))
    r = audiomix.WavReader(str(out))
    x = r.read(0, r.frames).astype(np.float64)
    nz = np.nonzero(np.abs(x[:, 0]) > 1e-4)[0]
    onset = nz[0] - 1  # o seno começa em 0: a primeira amostra do tom é zero
    assert abs(onset - want) <= 1, (onset, want)
    length = round((frame + 1) / seq.fps * audiomix.RATE) - want
    assert abs((nz[-1] + 1) - (want + length)) <= 2
    peak = np.abs(x[want:want + length, 0]).max()
    assert abs(20 * np.log10(peak) - generators.BEEP_DB) < 0.2
    assert np.array_equal(x[:, 0], x[:, 1])
    spec = np.abs(np.fft.rfft(x[want:want + length, 0]))
    assert abs(np.argmax(spec) * audiomix.RATE / length - 1000.0) < audiomix.RATE / length
