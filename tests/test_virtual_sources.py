"""Clipes sem arquivo (`timeline.Source.virtual` + `sequence.RENDERERS`): a base para títulos, geradores e legendas.

O gerador daqui é só de teste (não é recurso do app): metade esquerda transparente, metade direita na cor de
`src.data["cor"]`, com o brilho mudando a cada quadro da fonte (para conferir o tempo).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pelicula import audiomix, export, media, project, sequence
from pelicula import timeline as tl

W, H = 320, 180
KIND = "gerador"


def gen(seq, clip, frame, w, h, depth):
    """Gerador de teste: determinístico, só depende da fonte, do quadro e do tamanho."""
    src = seq.sources[clip.src]
    r, g, b = src.data.get("cor", [1.0, 0.5, 0.0])
    k = 0.3 + 0.07 * (frame % 10)
    a = np.zeros((h, w), np.float64)
    a[:, w // 2:] = 1.0
    img = np.dstack([r * k * a, g * k * a, b * k * a, a])  # pré-multiplicado (alfa 0 ou 1)
    mx = 255 if depth == 8 else 65535
    return np.rint(img * mx).astype(np.uint8 if depth == 8 else np.uint16)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, KIND, gen)
    return gen


def virtual(seconds=None, **data):
    return tl.Source.virtual(KIND, W, H, "24/1", seconds=seconds, data={"nome": "Barras", "cor": [1.0, 0.5, 0.0],
                                                                         **data})


def only_virtual(seconds=None):
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    src = virtual(seconds)
    clip = seq.insert_media(src, at=0)[0]
    return seq, src, clip


# ------------------------------------------------------------------ modelo e JSON
def test_virtual_source_json_round_trip_and_format_3():
    seq, src, clip = only_virtual()
    assert src.path.startswith("gerador:") and not src.is_file and src.unbounded and src.has_alpha
    assert src.name == "Barras" and clip.name == "Barras" and [c.kind for c in seq.clips] == [tl.VIDEO]
    assert clip.dur == seq.frames_for(tl.IMAGE_SECONDS)  # sem fim: entra como uma imagem
    d = json.loads(json.dumps(seq.to_json()))
    f = d["fontes"][0]
    assert f["tipo"] == KIND and f["dados"] == {"nome": "Barras", "cor": [1.0, 0.5, 0.0]} and f["alfa"] is True
    back = tl.Sequence.from_json(d)
    assert back.sources[src.path] == src and back.clips[0].src == src.path
    assert {"gerador", "alfa"} <= seq.features()
    assert project.Project(sequence=d).to_json()["formato"] == project.FORMAT_15
    with pytest.raises(ValueError):
        tl.Source.virtual(tl.SOURCE_FILE, W, H)
    with pytest.raises(ValueError):
        tl.Source.virtual("nao_existe", W, H)
    # um arquivo comum grava como antes (sem "dados", sem "tipo")
    plain = tl.Source("C:/v/a.mp4", W, H, 24.0, "24/1", 48, 2.0).to_json()
    assert "dados" not in plain and "tipo" not in plain


def test_virtual_clip_time_follows_the_clip():
    seq, src, clip = only_virtual()
    seq.move(clip.id, 10)
    assert seq.layers_at(15)[0].src_frame == 5
    seq.set_speed(clip.id, 2.0)
    assert seq.layers_at(15)[0].src_frame == 10
    assert seq.max_dur(clip) >= seq.frames_for(3600)  # pode esticar como uma imagem
    bounded = virtual(seconds=2.0)
    s2 = tl.Sequence(width=W, height=H, fps_str="24/1")
    c2 = s2.insert_media(bounded, at=0)[0]
    assert not bounded.unbounded and c2.dur == 48 and s2.max_dur(c2) == 48


def test_file_helpers_ignore_virtual_sources():
    seq, src, clip = only_virtual()
    gone = tl.Source("C:/nao/existe.mp4", W, H, 24.0, "24/1", 240, 10.0, has_audio=True, pix_fmt="yuv420p",
                     color_range="tv")
    seq.insert_media(gone, at=0, vtrack=1)
    assert sequence.missing_sources(seq) == ["C:/nao/existe.mp4"]
    seq.relink(src.path, "C:/outro.mp4")
    assert src.path in seq.sources and "C:/outro.mp4" not in seq.sources
    assert export.job_inputs(sequence.media_info(seq), seq) == ["C:/nao/existe.mp4"]
    assert Path(sequence.media_info(seq).path).name == "existe_edicao.mp4"
    assert sequence.legal_range(seq) is True  # o vídeo de faixa legal decide; o gerador conta como imagem
    alone, _src, _clip = only_virtual()
    assert sequence.missing_sources(alone) == [] and alone.is_trivial() is None and alone.direct_file() is None
    info = sequence.media_info(alone)
    assert Path(info.path).parent == Path.home() and ":" not in Path(info.path).name
    assert sequence.legal_range(alone) is False  # RGB de faixa cheia, como uma imagem
    assert sequence.first_video_source(alone) is None


@pytest.mark.ffmpeg
def test_audio_mix_ignores_virtual_clips(sample_video):
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    before = audiomix.build_graph(seq), audiomix.segments(seq)
    c = seq.insert_media(virtual(), at=0, vtrack=1)[0]
    seq.trim_end(c.id, 12)  # dentro do vídeo: a montagem não fica mais longa
    assert (audiomix.build_graph(seq), audiomix.segments(seq)) == before


@pytest.mark.ffmpeg
def test_project_keeps_virtual_sources_without_relative_paths(tmp_path, sample_video):
    seq = tl.Sequence.for_source(media.probe_source(sample_video))
    v = virtual()
    seq.insert_media(v, at=0, vtrack=1)
    p = project.Project(media_path=sample_video, sequence=seq.to_json())
    path = str(tmp_path / "gerado.plc")
    project.save(p, path)
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    fontes = {f["caminho"]: f for f in raw["edicao"]["fontes"]}
    assert "relativo" not in fontes[v.path] and "relativo" in fontes[sample_video]
    assert raw["formato"] == project.FORMAT_15
    back = tl.Sequence.from_json(project.load(path).sequence)
    assert back.sources[v.path] == v


# ------------------------------------------------------------------ desenho
@pytest.mark.parametrize("depth", [8, 16])
def test_grab_and_reader_use_the_same_renderer(renderer, depth):
    seq, src, clip = only_virtual()
    reader = sequence.SequenceReader(seq, W, H, depth, 0, 12)
    try:
        seen = set()
        for t in range(12):
            a, b = sequence.grab(seq, t, W, H, depth).layers, reader.read().layers
            assert len(a) == len(b) == 1
            assert a[0].image.shape == (H, W, 4) and a[0].image.dtype == (np.uint8 if depth == 8 else np.uint16)
            assert np.array_equal(a[0].image, b[0].image), t
            seen.add(a[0].image.tobytes())
        assert len(seen) == 10  # o quadro da fonte anda (10 brilhos)
        assert reader.error == ""
    finally:
        reader.close()


def test_renderer_output_is_checked_and_converted(monkeypatch):
    seq, src, clip = only_virtual()
    monkeypatch.setitem(sequence.RENDERERS, KIND, lambda s, c, f, w, h, d: np.full((h, w, 4), 255, np.uint8))
    img = sequence.render_source(seq, clip, 0, 8, 6, 16)
    assert img.dtype == np.uint16 and img.max() == 65535  # 8 bits numa leitura de 16: ×257
    monkeypatch.setitem(sequence.RENDERERS, KIND, lambda s, c, f, w, h, d: np.full((h, w, 3), 0.5, np.float32))
    assert sequence.render_source(seq, clip, 0, 8, 6, 8).max() == 128
    monkeypatch.setitem(sequence.RENDERERS, KIND, lambda s, c, f, w, h, d: np.zeros((h + 1, w, 4), np.uint8))
    with pytest.raises(ValueError, match="gerador"):
        sequence.grab(seq, 0, W, H, 8)
    reader = sequence.SequenceReader(seq, W, H, 8, 0, 1)
    try:
        layers = reader.read().layers
        assert layers[0].image.shape[2] == 4 and layers[0].image.max() == 0  # erro: camada transparente
        assert "gerador" in reader.error
    finally:
        reader.close()


def test_kind_without_renderer_is_a_transparent_layer(monkeypatch):
    # "gerador" tem o gerador do app (generators.py): aqui o tipo fica sem gerador, como num projeto mais novo
    monkeypatch.delitem(sequence.RENDERERS, KIND, raising=False)
    seq, src, clip = only_virtual()
    assert KIND not in sequence.RENDERERS
    layers = sequence.grab(seq, 0, W, H, 8).layers
    assert len(layers) == 1 and layers[0].image.shape[2] == 4 and layers[0].image.max() == 0
    assert sequence.source_thumbnail(src, 32, 18).shape == (18, 32, 3)


@pytest.mark.gpu
def test_virtual_clip_over_a_file_and_preview_equals_export(gl_engine, renderer, sample_image, ffmpeg_ok):
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    seq.insert_media(media.probe_source(sample_image), at=0)
    clip = seq.insert_media(virtual(), at=0, vtrack=1)[0]
    alone = seq.copy()
    alone.set_values(clip.id, {**clip.values, "opacidade": 0.0})
    for depth in (8, 16):
        reader = sequence.SequenceReader(seq, W, H, depth, 0, 6, hq=True)
        try:
            for t in range(6):
                preview = gl_engine.compose(sequence.grab(seq, t, W, H, depth, hq=True), seq, W, H, depth)
                assert np.array_equal(preview, gl_engine.compose(reader.read(), seq, W, H, depth)), (depth, t)
                bg = gl_engine.compose(sequence.grab(alone, t, W, H, depth, hq=True), alone, W, H, depth)
                assert np.array_equal(preview[:, :W // 2], bg[:, :W // 2]), "transparente: o arquivo de baixo"
                want = gen(seq, clip, t, W, H, depth)[:, W // 2:, :3]
                assert np.abs(preview[:, W // 2:].astype(int) - want.astype(int)).max() <= (1 if depth == 8 else 257)
        finally:
            reader.close()
    assert np.array_equal(gl_engine.compose(sequence.grab(seq, 0, W, H, 8), seq, W, H, 8),
                          gl_engine.compose(sequence.grab(seq, 0, W, H, 8), seq, W, H, 8))  # determinístico
