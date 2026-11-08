"""1.9: dados dos efeitos no projeto e o tempo para os efeitos (ARQUITETURA §49.8–49.9).

`Clip.fx` (JSON "efeitos"), `Source.analysis` (JSON "analise", fora do desfazer), os recursos do formato 7 deles, as
janelas de tempo (`vfx.WINDOWS` → `Sequence.frame_window`) e os quadros vizinhos (`Sequence.neighbor_frames` →
`LayerImage.neighbors`, iguais em `grab` e no `SequenceReader`).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from pelicula import aninhar, media, sequence, vfx
from pelicula import timeline as tl

W, H = 160, 90


def fsrc(path="C:/nao/existe.mp4", frames=48):
    return tl.Source(path, W, H, 24.0, "24/1", frames, frames / 24.0, pix_fmt="yuv420p", color_range="tv")


def seq_with(src=None):
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    c = seq.insert_media(src or fsrc(), at=0, with_audio=False)[0]
    return seq, c


# ------------------------------------------------------------------ Clip.fx e Source.analysis
def test_clip_fx_round_trip_only_when_used():
    seq, c = seq_with()
    assert "efeitos" not in c.to_json() and "efeitos_clipe_dados" not in seq.features()
    c.fx["mascara"] = {"pontos": [[0.1, 0.2], [0.5, 0.9]], "suave": 3.0}
    d = c.to_json()
    assert d["efeitos"] == {"mascara": {"pontos": [[0.1, 0.2], [0.5, 0.9]], "suave": 3.0}}
    back = tl.Clip.from_json(json.loads(json.dumps(d)))
    assert back.fx == c.fx and back.fx is not c.fx
    assert "efeitos_clipe_dados" in seq.features() and seq.block_format() == tl.FORMAT
    assert tl.Clip.from_json({**d, "efeitos": [1, 2]}).fx == {}


def test_split_nest_and_unnest_carry_the_fx():
    seq, c = seq_with()
    c.fx["rastro"] = {"id": "a"}
    right = seq.find(seq.split(20, [c.id])[0])
    assert right.fx == {"rastro": {"id": "a"}} and right.fx is not c.fx
    res = aninhar.nest(seq, [c.id, right.id])
    inner = res.inner
    assert all(x.fx == {"rastro": {"id": "a"}} for x in inner.clips)
    aninhar.unnest(seq, res.clips[0].id)
    assert sorted(len(x.fx) for x in seq.clips if x.kind == tl.VIDEO) == [1, 1]


def test_source_analysis_saved_but_out_of_undo():
    seq, c = seq_with()
    src = seq.sources[c.src]
    hist = tl.History(seq)
    assert "analise_fonte" not in seq.features()
    src.analysis["rastro"] = {"carimbo": {}, "pontos": vfx.pack(np.zeros((4, 2), np.float32))}
    assert not hist.push(seq)  # análise não é passo de desfazer
    assert "analise_fonte" in seq.features() and seq.block_format() == tl.FORMAT
    back = tl.Sequence.from_json(json.loads(json.dumps(seq.to_json())))
    assert back.sources[c.src].analysis == src.analysis
    seq.set_values(c.id, {"exposicao": 0.5})
    assert hist.push(seq)
    undone = hist.undo(seq)
    assert undone.sources[c.src].analysis == src.analysis  # a análise de agora continua
    seq.sources[c.src].analysis.clear()
    redone = hist.redo(seq)
    assert redone.sources[c.src].analysis == {}


def test_a_source_that_comes_back_brings_its_analysis():
    seq, c = seq_with()
    hist = tl.History(seq)
    seq.sources[c.src].analysis["fluxo"] = {"x": 1}
    seq.set_values(c.id, {"exposicao": 0.3})
    hist.push(seq)
    seq.delete([c.id])
    seq.sources.pop(c.src, None)
    hist.push(seq)
    back = hist.undo(seq)
    assert back.sources[c.src].analysis == {"fluxo": {"x": 1}}


# ------------------------------------------------------------------ janelas e vizinhos
def test_frame_window_prefers_effects_and_falls_back_to_the_shutter():
    seq, c = seq_with()
    assert seq.frame_window(c, 5) is None
    assert seq.frame_window(c, 5, 180.0) == seq.src_window(c, 5, 180.0)
    vfx.WINDOWS["teste"] = lambda s, clip, t: [(t, 0.5), (t + 1, 0.5)] if clip.id == c.id else None
    try:
        assert seq.frame_window(c, 5, 180.0) == [(5, 0.5), (6, 0.5)]
        assert seq.frame_window(c, 5, 180.0, effects=False) == seq.src_window(c, 5, 180.0)
    finally:
        del vfx.WINDOWS["teste"]


def test_neighbor_frames_clamp_and_follow_reverse():
    seq, c = seq_with(fsrc(frames=10))
    assert seq.neighbor_frames(c, 0, 0) is None
    assert seq.neighbor_frames(c, 0, 2) == [(-2, 0), (-1, 0), (1, 1), (2, 2)]
    assert seq.neighbor_frames(c, 9, 1) == [(-1, 8), (1, 9)]
    seq.set_values(c.id, {**c.values, "congelar": True})
    assert seq.neighbor_frames(c, 3, 1) is None
    rev, rc = seq_with(fsrc(frames=10))
    rc.reverse = True
    f = rev.src_frame(rc, 4)
    assert rev.neighbor_frames(rc, 4, 1) == [(-1, min(f + 1, 9)), (1, max(f - 1, 0))]


@pytest.fixture
def near_effect():
    eff = vfx.register(vfx.Effect("teste_vizinhos", "efeitos_visuais", vfx.ORDER["tempo"], active=lambda v: True,
                                  passes=lambda ctx: [], radius=lambda v: 2))
    yield eff
    vfx.unregister(eff.id)


@pytest.mark.ffmpeg
def test_neighbors_from_grab_equal_the_reader(ffmpeg_ok, tmp_path, near_effect):
    import subprocess
    path = tmp_path / "v.mp4"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=24:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    seq.insert_media(media.probe_source(str(path)), at=0, with_audio=False)
    assert vfx.neighbor_radius({}) == 2
    reader = sequence.SequenceReader(seq, W, H, 8)
    try:
        for t in range(seq.duration):
            a = reader.read()
            b = sequence.grab(seq, t, W, H, 8)
            la, lb = a.layers[0], b.layers[0]
            assert [k for k, _i in la.neighbors] == [-2, -1, 1, 2] == [k for k, _i in lb.neighbors]
            for (_k, x), (_k2, y) in zip(la.neighbors, lb.neighbors):
                assert np.array_equal(x, y), f"quadro {t}"
            assert np.array_equal(la.image, lb.image)
        assert reader.error == ""
    finally:
        reader.close()
    assert sequence.grab(seq, 3, W, H, 8, no_effects=True).layers[0].neighbors is None


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_a_pass_reads_the_previous_frame(gl_engine, ffmpeg_ok, tmp_path):
    """A entrada "n-1" de um passo é o quadro anterior do arquivo: o clipe mostra, no quadro t, o que mostraria em t − 1."""
    import subprocess
    path = tmp_path / "v.mp4"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=24:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    seq.insert_media(media.probe_source(str(path)), at=0, with_audio=False)
    plain = [gl_engine.compose(sequence.grab(seq, t, W, H, 8), seq, W, H, 8) for t in (4, 5)]
    glsl = "uniform sampler2D t_n;\nvoid main() { f_out = texture(t_n, v_uv); }"
    eff = vfx.register(vfx.Effect("teste_anterior", "efeitos_visuais", vfx.ORDER["tempo"], active=lambda v: True,
                                  passes=lambda ctx: [vfx.Pass("n", glsl, inputs={"t_n": "n-1"})], radius=lambda v: 1))
    try:
        got = gl_engine.compose(sequence.grab(seq, 5, W, H, 8), seq, W, H, 8)
    finally:
        vfx.unregister(eff.id)
    assert np.array_equal(got, plain[0]) and not np.array_equal(got, plain[1])
