"""Encaixe num quadro de outra proporção (fit.py): geometria, passada da GPU e paridade prévia × exportação.

- `fit.plan()` sem GPU: cortar, bordas e fundo desfocado em vídeo deitado → vertical, vertical → deitado,
  quadrado, tamanhos ímpares e a montagem do modo Edição.
- Na GPU: dentro da caixa, `Engine.render_fit` devolve exatamente o quadro de `Engine.render`; o recorte de
  `Engine.compose(crop=...)` é exatamente o pedaço da tela inteira.
- Ponta a ponta (FFV1 16 bits, sem perdas): cada quadro gravado é idêntico ao da prévia da janela de exportação
  (`export.preview_frame`), nos modos Película e Edição.
"""

from __future__ import annotations

import numpy as np
import pytest

from helpers import SAMPLE_H, SAMPLE_W, read_all
from pelicula import export, fit, look, media, presets, sequence
from pelicula import timeline as tl
from pelicula.export import ExportJob, ExportSettings


# ------------------------------------------------------------------ geometria (sem GPU)
def _inside(f: fit.Fit) -> None:
    x, y, w, h = f.box
    assert 0 <= x and 0 <= y and x + w <= f.out_w and y + h <= f.out_h and w >= 2 and h >= 2


@pytest.mark.parametrize("src, out", [((1920, 1080), (1080, 1920)), ((1080, 1920), (1920, 1080)),
                                      ((1920, 1080), (1080, 1080)), ((1080, 1920), (1080, 1350)),
                                      ((321, 181), (101, 151)), ((3000, 2000), (1080, 1920)),
                                      ((720, 1280), (1080, 1080))])
def test_cut_crops_the_file_to_the_frame_aspect_before_the_look(src, out):
    f = fit.plan(*src, *out, fit.CORTAR)
    assert f.mode == fit.CORTAR and (f.dec_w, f.dec_h) == out and f.box == (0, 0, *out)
    assert f.look_size == out and not f.composite and f.canvas_crop is None
    x, y, w, h = f.crop
    assert x % 2 == y % 2 == w % 2 == h % 2 == 0  # 4:2:0 não recorta meio pixel de croma
    assert 0 <= x and 0 <= y and x + w <= src[0] and y + h <= src[1]
    assert w == src[0] - src[0] % 2 or h == src[1] - src[1] % 2  # um dos lados fica inteiro
    assert w / h == pytest.approx(out[0] / out[1], rel=0.02)
    assert abs((src[0] - w) / 2 - x) <= 1 and abs((src[1] - h) / 2 - y) <= 1  # centralizado


@pytest.mark.parametrize("mode", [fit.BORDAS, fit.DESFOCADO])
@pytest.mark.parametrize("src, out, box", [
    ((1920, 1080), (1080, 1920), (0, 656, 1080, 608)),   # deitado no vertical: faixas em cima e embaixo
    ((1080, 1920), (1920, 1080), (656, 0, 608, 1080)),   # vertical no deitado: faixas dos lados
    ((1920, 1080), (1080, 1080), (0, 236, 1080, 608)),   # quadrado
    ((1080, 1080), (1080, 1350), (0, 135, 1080, 1080)),  # quadrado no 4:5
    ((320, 180), (101, 151), (0, 47, 101, 57)),          # tamanhos ímpares: margens iguais
])
def test_borders_and_blur_fit_the_whole_picture_with_equal_margins(mode, src, out, box):
    f = fit.plan(*src, *out, mode)
    assert f.mode == mode and f.composite and f.box == box and (f.dec_w, f.dec_h) == box[2:]
    assert f.crop is None and f.canvas_crop is None
    _inside(f)
    x, y, w, h = f.box
    assert x == f.out_w - x - w and y == f.out_h - y - h
    assert w / h == pytest.approx(src[0] / src[1], abs=0.02 * src[0] / src[1] + 1 / h)


@pytest.mark.parametrize("mode", ["", "esticar", None, fit.CORTAR, fit.BORDAS, fit.DESFOCADO])
def test_same_aspect_or_no_mode_only_resizes(mode):
    for src, out in (((1920, 1080), (1280, 720)), ((1080, 1920), (1080, 1920)), ((321, 181), (171, 96))):
        f = fit.plan(*src, *out, mode or "")
        assert f.mode == "" and (f.dec_w, f.dec_h) == out and f.box == (0, 0, *out)
        assert f.crop is None and f.canvas_crop is None and not f.composite
    if mode not in fit.MODE_IDS:  # sem modo nunca recorta nem põe bordas
        f = fit.plan(1920, 1080, 1080, 1920, mode or "")
        assert f.mode == "" and (f.dec_w, f.dec_h) == (1080, 1920)


@pytest.mark.parametrize("src, out", [((1920, 1080), (1080, 1920)), ((1080, 1920), (1920, 1080)),
                                      ((1280, 720), (1080, 1080)), ((320, 180), (101, 151))])
def test_cut_in_edit_mode_crops_the_assembled_canvas(src, out):
    f = fit.plan(*src, *out, fit.CORTAR, edit=True)
    assert f.mode == fit.CORTAR and f.crop is None and f.box == (0, 0, *out)
    cx, cy, cw, ch = f.canvas_crop
    assert (cw, ch) == out
    assert f.dec_w >= out[0] and f.dec_h >= out[1] and (f.dec_w == out[0] or f.dec_h == out[1])
    assert f.dec_w / f.dec_h == pytest.approx(src[0] / src[1], rel=0.02)
    assert (cx, cy) == ((f.dec_w - out[0]) // 2, (f.dec_h - out[1]) // 2)
    f2 = fit.plan(*src, *out, fit.BORDAS, edit=True)
    assert f2.box == fit.plan(*src, *out, fit.BORDAS).box


def test_blur_radius_follows_the_final_frame():
    assert fit.plan(1920, 1080, 1080, 1920, fit.DESFOCADO).blur_sigma() == pytest.approx(fit.BLUR_PX * 1920 / 1080)
    assert fit.plan(1920, 1080, 540, 960, fit.DESFOCADO).blur_sigma() == pytest.approx(fit.BLUR_PX * 960 / 1080)


def test_export_frame_and_fit_choose_the_geometry(make_info):
    info = make_info(width=1920, height=1080)
    p = export.frame_pipeline(info, presets.builtin_values("original"),
                              ExportSettings(frame="1080x1920", fit="bordas"))
    assert p.fit.mode == fit.BORDAS and p.fit.box == (0, 656, 1080, 608)
    p = export.frame_pipeline(info, {}, ExportSettings(frame="1080x1920", fit="???"))
    assert p.fit.mode == fit.CORTAR  # quadro fixo nunca estica o vídeo
    p = export.frame_pipeline(info, {}, ExportSettings(frame="", fit="bordas", resolution="720"))
    assert p.fit.mode == "" and (p.fit.out_w, p.fit.out_h) == (1280, 720)
    p = export.frame_pipeline(info, {}, ExportSettings(frame="1080x1920", fit="desfocado"), scale=0.25)
    assert (p.fit.out_w, p.fit.out_h) == (270, 480) and p.fit.box == (0, 164, 270, 152)
    assert export.output_size(info, ExportSettings(frame="1080x1350", resolution="2160")) == (1080, 1350)
    assert export.output_size(info, ExportSettings(frame="1081x1351")) == (1080, 1350)  # vídeo: dimensões pares
    assert export.output_size(info, ExportSettings(codec="ffv1", frame="1081x1351")) == (1081, 1351)


@pytest.mark.parametrize("text, expected", [("1080x1920", (1080, 1920)), (" 1080 × 1350 ", (1080, 1350)),
                                            ("1920X1080", (1920, 1080)), ("", None), ("1080", None),
                                            ("0x10", None), ("abcxdef", None), ("99999x2", None), (None, None)])
def test_parse_frame(text, expected):
    assert export.parse_frame(text) == expected


# ------------------------------------------------------------------ GPU
@pytest.fixture
def film():
    return presets.builtin_values("vision3_500t")  # grão, halação, vinheta, cópia


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
@pytest.mark.parametrize("mode", [fit.BORDAS, fit.DESFOCADO])
def test_render_fit_keeps_the_look_pixel_exact_inside_the_box(gl_engine, test_rgb, film, depth, mode):
    f = fit.plan(SAMPLE_W, SAMPLE_H, 180, 320, mode)
    x, y, w, h = f.box
    img = test_rgb[:h, :w] if depth == 8 else test_rgb[:h, :w].astype(np.uint16) * 257
    gl_engine.set_input(np.ascontiguousarray(img))
    plan = look.build_plan(film, w, h, 7, 24.0, None, dither=depth == 8)
    ref = gl_engine.render(plan, depth)
    gl_engine.set_input(np.ascontiguousarray(img))
    out = gl_engine.render_fit(look.build_plan(film, w, h, 7, 24.0, None, dither=depth == 8), depth, f)
    assert out.shape == (320, 180, 3) and out.dtype == ref.dtype
    assert np.array_equal(out[y:y + h, x:x + w], ref)
    bands = np.concatenate([out[:y], out[y + h:]])
    if mode == fit.BORDAS:
        assert not bands.any()
    else:
        assert bands.mean() > 0.04 * (255 if depth == 8 else 65535)  # um fundo de verdade, não preto
        assert bands.mean() < ref.mean()  # escurecido
        # desfocado: sem bordas duras (a diferença entre vizinhos é bem menor que na imagem)
        assert np.abs(np.diff(bands.astype(np.int64), axis=1)).mean() < np.abs(
            np.diff(ref.astype(np.int64), axis=1)).mean() * 0.5
        gl_engine.set_input(np.ascontiguousarray(img))
        again = gl_engine.render_fit(look.build_plan(film, w, h, 7, 24.0, None, dither=depth == 8), depth, f)
        assert np.array_equal(out, again)  # determinístico


@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_compose_crop_is_the_exact_piece_of_the_canvas(gl_engine, sample_video_layers, depth):
    seq, layers = sample_video_layers(depth)
    full = gl_engine.compose(layers, seq, SAMPLE_W, SAMPLE_H, depth)
    part = gl_engine.compose(layers, seq, SAMPLE_W, SAMPLE_H, depth, crop=(70, 10, 101, 151))
    assert part.shape == (151, 101, 3)
    assert np.array_equal(part, full[10:161, 70:171])
    assert np.array_equal(gl_engine.compose(layers, seq, SAMPLE_W, SAMPLE_H, depth), full)  # sem recorte de novo


@pytest.fixture
def sample_video_layers(ffmpeg_ok, sample_video):
    def make(depth):
        seq = tl.Sequence.for_source(media.probe_source(sample_video))
        return seq, sequence.grab(seq, 5, SAMPLE_W, SAMPLE_H, depth, hq=True)
    return make


# ------------------------------------------------------------------ ponta a ponta: exportação == prévia
def _ffv1(**over) -> ExportSettings:
    s = ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="none", dither=False)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _check_parity(engine, info, values, s, out, start, end, seq=None):
    job = ExportJob(info=info, values=values, settings=s, out_path=str(out), start_frame=start, end_frame=end,
                    sequence=seq)
    export.run_job(job, engine)
    assert job.status == "concluido", job.error
    w, h = export.output_size(info, s)
    o = media.probe(str(out))
    assert (o.width, o.height) == (w, h)
    decoded = read_all(media.FrameReader(o, w, h, 16))
    assert len(decoded) == end - start + 1 == job.done
    for k in (0, len(decoded) // 2, len(decoded) - 1):
        prev = export.preview_frame(engine, info, values, s, start + k, seq=seq, depth=16)
        assert prev.shape == (h, w, 3)
        assert np.array_equal(decoded[k], prev), f"quadro {start + k} difere da prévia"
    return decoded


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("frame, mode", [("180x320", "cortar"), ("180x320", "bordas"), ("180x320", "desfocado"),
                                         ("160x160", "cortar"), ("101x151", "bordas"), ("101x151", "cortar")])
def test_film_mode_export_matches_the_export_preview(gl_engine, ffmpeg_ok, sample_info, tmp_path, film, frame, mode):
    s = _ffv1(frame=frame, fit=mode)
    decoded = _check_parity(gl_engine, sample_info, film, s, tmp_path / "plataforma.mkv", 3, 9)
    w, h = export.parse_frame(frame)
    f = export.frame_pipeline(sample_info, film, s).fit
    if f.composite:
        x, y, bw, bh = f.box
        bands = np.concatenate([decoded[0][:y], decoded[0][y + bh:]])
        assert (not bands.any()) if mode == "bordas" else bands.mean() > 2000


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("mode", ["cortar", "bordas", "desfocado"])
def test_vertical_video_to_landscape_frame(gl_engine, ffmpeg_ok, sample_vertical_video, tmp_path, film, mode):
    info = media.probe(sample_vertical_video)
    _check_parity(gl_engine, info, film, _ffv1(frame="320x180", fit=mode), tmp_path / "deitado.mkv", 0, 5)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_cut_lays_the_look_out_on_the_final_frame(gl_engine, ffmpeg_ok, sample_info, film):
    """Cortar = recortar o arquivo antes do look: o quadro é o look aplicado ao recorte (vinheta, bordas e grão
    seguem o quadro final), não um recorte do quadro com o look."""
    s = _ffv1(frame="180x320", fit="cortar")
    p = export.frame_pipeline(sample_info, film, s)
    src = media.grab_frame(sample_info, 4, 180, 320, 16, hq=True, crop=p.fit.crop)
    gl_engine.set_input(src)
    ref = gl_engine.render(look.build_plan(film, 180, 320, 4, sample_info.fps, None, dither=False), 16)
    assert np.array_equal(export.preview_frame(gl_engine, sample_info, film, s, 4, depth=16), ref)


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("frame, mode", [("180x320", "cortar"), ("180x320", "desfocado"), ("160x160", "bordas")])
def test_edit_mode_export_matches_the_export_preview(gl_engine, ffmpeg_ok, sample_video, sample_image, tmp_path,
                                                    film, frame, mode):
    a = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(a)
    v = [c for c in seq.clips if c.kind == tl.VIDEO][0]
    seq.trim_end(v.id, 16)
    top, = seq.insert_media(media.probe_source(sample_image), at=2, vtrack=1)
    seq.trim_end(top.id, 12)
    seq.set_values(top.id, {**top.values, "escala": 0.4, "pos_x": 0.25, "opacidade": 0.8})
    info = sequence.media_info(seq)
    _check_parity(gl_engine, info, film, _ffv1(frame=frame, fit=mode), tmp_path / "edicao.mkv", 2, 9, seq=seq)
