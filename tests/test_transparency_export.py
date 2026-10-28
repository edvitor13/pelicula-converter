"""Fundo transparente da montagem e exportar com transparência (canal alfa).

A montagem de teste: um gerador (só de teste) com metade esquerda transparente, uma faixa meio transparente no
alto e a metade direita opaca, sobre a tela com "Fundo transparente". Confere a tela RGBA (`Engine.compose`), o
alfa do look (a cor sai igual à de sempre, o alfa segue a geometria), os arquivos exportados (ProRes 4444, PNG,
TIFF e WebM VP9 com alfa, lidos de volta) e que um projeto opaco exporta exatamente como antes.
"""

from __future__ import annotations

import json
import subprocess

import numpy as np
import pytest

from helpers import read_all
from pelicula import cli, export, frame, media, presets, project, sequence
from pelicula import timeline as tl
from pelicula.export import ExportJob, ExportSettings

W, H = 96, 54
KIND = "gerador"


def gen(seq, clip, f, w, h, depth):
    """Esquerda transparente, direita opaca, faixa do alto com alfa 0,5 (pré-multiplicado)."""
    a = np.zeros((h, w), np.float64)
    a[:, w // 2:] = 1.0
    a[: h // 4] *= 0.5
    k = 0.6 + 0.05 * (f % 4)
    img = np.dstack([0.9 * k * a, 0.5 * k * a, 0.25 * k * a, a])
    mx = 255 if depth == 8 else 65535
    return np.rint(img * mx).astype(np.uint8 if depth == 8 else np.uint16)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, KIND, gen)


def montage(transparent=True, seconds=1.0):
    seq = tl.Sequence(width=W, height=H, fps_str="24/1", transparent=transparent, background=(0.2, 0.3, 0.4))
    src = tl.Source.virtual(KIND, W, H, "24/1", seconds=seconds, data={"nome": "metade"})
    seq.insert_media(src, at=0)
    return seq


def expected_alpha(h=H, w=W) -> np.ndarray:
    a = np.zeros((h, w))
    a[:, w // 2:] = 1.0
    a[: h // 4] *= 0.5
    return a


# ------------------------------------------------------------------ modelo e JSON
def test_transparent_background_json_and_feature():
    seq = montage()
    d = json.loads(json.dumps(seq.to_json()))
    assert d["fundo_transparente"] is True and "fundo_transparente" in seq.features()
    assert tl.Sequence.from_json(d).transparent
    off = montage(transparent=False)
    assert "fundo_transparente" not in off.to_json() and "fundo_transparente" not in off.features()
    src = tl.Source("C:/v/a.mp4", W, H, 24.0, "24/1", 24, 1.0)
    plain = tl.Sequence.for_source(src)
    assert plain.is_trivial() == src.path
    plain.transparent = True
    assert plain.is_trivial() is None  # o projeto guarda a montagem (a escolha do fundo)


def test_alpha_formats_per_codec():
    assert export.supports_alpha("prores") and export.supports_alpha("vp9") and export.supports_alpha("png_seq")
    assert not export.supports_alpha("x264") and not export.supports_alpha("x265")
    assert export.alpha_pix("prores", "yuv422p10le") == "yuva444p10le"
    assert export.alpha_pix("png_seq", "rgb48be") == "rgba64be" and export.alpha_pix("png_seq", "rgb24") == "rgba"
    assert export.alpha_pix("tiff_seq", "rgb48le") == "rgba64le" and export.alpha_pix("vp9", "yuv420p") == "yuva420p"
    assert export.alpha_pix("x264", "yuv420p") == "yuv420p"
    assert export.opaque_pix("png_seq", "rgba64be") == "rgb48be" and export.opaque_pix("x264", "yuv420p") == "yuv420p"
    for codec in export.ALPHA_PIX:
        assert all(p in export.CODECS[codec]["pix"] for p in export.ALPHA_PIX[codec].values())
    s = ExportSettings(codec="prores", container="mov", pix="yuva444p10le", profile="3")
    assert export.wants_alpha(s) and export.high_depth(s)
    assert not export.wants_alpha(ExportSettings(codec="x264", pix="yuv420p"))


def test_encoder_command_with_alpha(make_info):
    info = make_info(has_audio=False)
    s = ExportSettings(codec="prores", container="mov", pix="yuva444p10le", profile="3", audio="none")
    cmd = export.build_encoder_cmd("x.mov", info, s, W, H, "24/1", 16, 0.0, 1.0)
    assert cmd[cmd.index("-pix_fmt") + 1] == "rgba64le" and "yuva444p10le" in cmd
    assert cmd[cmd.index("-profile:v") + 1] == "4"  # só o 4444 guarda o alfa
    s8 = ExportSettings(codec="png_seq", container="png", pix="rgba", audio="none")
    cmd8 = export.build_encoder_cmd("x.png", info, s8, W, H, "24/1", 8, 0.0, 1.0)
    assert cmd8[cmd8.index("-pix_fmt") + 1] == "rgba"
    opaque = ExportSettings(codec="prores", container="mov", pix="yuv422p10le", profile="3", audio="none")
    cmd_o = export.build_encoder_cmd("x.mov", info, opaque, W, H, "24/1", 16, 0.0, 1.0)
    assert cmd_o[cmd_o.index("-pix_fmt") + 1] == "rgb48le" and cmd_o[cmd_o.index("-profile:v") + 1] == "3"


# ------------------------------------------------------------------ montagem RGBA
@pytest.mark.gpu
@pytest.mark.parametrize("depth", [8, 16])
def test_compose_alpha_is_the_montage_coverage(gl_engine, renderer, depth):
    seq = montage()
    layers = sequence.grab(seq, 0, W, H, depth)
    out = gl_engine.compose(layers, seq, W, H, depth, alpha=True)
    mx = 255 if depth == 8 else 65535
    assert out.shape == (H, W, 4)
    assert np.abs(out[..., 3] / mx - expected_alpha()).max() <= 1.0 / mx
    # cor direta: a metade opaca e a faixa meio transparente têm a mesma cor
    assert np.abs(out[H // 2, -1, :3].astype(int) - out[1, -1, :3].astype(int)).max() <= (1 if depth == 8 else 257)
    # os pixels transparentes recebem a cor vizinha (não o fundo), para o look não escurecer a borda
    assert np.abs(out[H // 2, 0, :3].astype(int) - out[H // 2, -1, :3].astype(int)).max() <= (2 if depth == 8 else 520)
    # sem `alpha`, a tela é opaca como sempre: "Fundo transparente" não muda nada
    opaque = gl_engine.compose(layers, seq, W, H, depth)
    off = montage(transparent=False)
    assert np.array_equal(opaque, gl_engine.compose(sequence.grab(off, 0, W, H, depth), off, W, H, depth))
    assert np.array_equal(out, gl_engine.compose(layers, seq, W, H, depth, alpha=True))  # determinístico


@pytest.mark.gpu
def test_compose_alpha_over_an_opaque_lower_clip(gl_engine, renderer, monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, "cor", lambda s, c, f, w, h, d: np.full(
        (h, w, 3), 128 if d == 8 else 32896, np.uint8 if d == 8 else np.uint16))
    seq = montage()
    for c in seq.clips:
        c.track = 1  # o gerador na V2
    under = tl.Source.virtual("cor", W, H, "24/1", seconds=1.0, data={"nome": "c"}, alpha=False)
    seq.insert_media(under, at=0, vtrack=0)
    out = gl_engine.compose(sequence.grab(seq, 0, W, H, 8), seq, W, H, 8, alpha=True)
    assert out[..., 3].min() == 255  # a cor de baixo cobre tudo
    assert np.abs(out[H // 2, 0, :3].astype(int) - 128).max() <= 1  # e aparece onde o gerador é transparente


# ------------------------------------------------------------------ look com alfa
def _look(engine, values, rgba, depth=8, index=0):
    r = frame.Recipe(values, 24.0, depth, legal=False, alpha=True)
    return r.look(engine, rgba, index)


@pytest.fixture
def rgba(gl_engine, renderer):
    seq = montage()
    return gl_engine.compose(sequence.grab(seq, 0, W, H, 16), seq, W, H, 16, alpha=True)


@pytest.mark.gpu
def test_look_keeps_the_color_and_carries_the_alpha(gl_engine, rgba):
    film = presets.builtin_values("vision3_500t")
    film.update(grao_forca=1.5)
    out = _look(gl_engine, film, rgba, 16, 3)
    assert out.shape == (H, W, 4) and out.dtype == np.uint16
    # a cor é exatamente a do look sem alfa
    gl_engine.set_input(rgba)
    plan = frame.Recipe(film, 24.0, 16, legal=False).plan(W, H, 3)
    assert np.array_equal(out[..., :3], gl_engine.render(plan, 16))
    # grão, halação e bloom não mexem no alfa; o "Original" devolve o alfa da montagem
    plain = _look(gl_engine, presets.builtin_values("original"), rgba, 16)
    assert np.array_equal(out[..., 3], plain[..., 3]) and np.array_equal(plain[..., 3], rgba[..., 3])
    assert np.array_equal(out, _look(gl_engine, film, rgba, 16, 3))  # determinístico


@pytest.mark.gpu
def test_alpha_follows_the_geometry_and_the_frame(gl_engine, rgba):
    base = presets.builtin_values("original")
    a0 = rgba[..., 3].astype(np.float64) / 65535
    # Moldura em 2,39: as barras ficam transparentes, a janela guarda o alfa da montagem
    out = _look(gl_engine, dict(base, mold_on=True, proporcao="2.39", borda_suave=0.0), rgba, 16)
    assert out[0, -1, 3] == 0 and out[-1, -1, 3] == 0 and out[H // 2, -1, 3] == 65535
    assert out[H // 2, 0, 3] == 0
    # Scan da película: a tira (bordas, furos) é opaca; o quadro do meio guarda o alfa
    out = _look(gl_engine, dict(base, scan_on=True), rgba, 16)
    assert out[..., 3].min() < 1000 and out[:, 0, 3].min() == 65535 and out[:, -1, 3].min() == 65535
    # Tremor do projetor: o alfa anda com a imagem (a borda da metade opaca muda de lugar)
    weave = dict(base, proj_on=True, tremor_x=6.0, tremor_y=0.0, tremor_rot=0.0)
    moved = [_look(gl_engine, weave, rgba, 16, i)[..., 3] for i in range(4)]
    assert any(not np.array_equal(m, rgba[..., 3]) for m in moved)
    # Força geral 0: o alfa da entrada, sem geometria
    still = _look(gl_engine, dict(weave, mix_geral=0.0), rgba, 16, 1)
    assert np.abs(still[..., 3] / 65535 - a0).max() < 1e-3


@pytest.mark.gpu
def test_look_with_fit_borders_is_transparent_outside(gl_engine, renderer):
    from pelicula import fit as fitmod
    seq = montage()
    info = sequence.media_info(seq)
    for mode, outside in ((fitmod.BORDAS, 0), (fitmod.DESFOCADO, 255)):
        s = ExportSettings(codec="png_seq", container="png", pix="rgba", audio="none", frame="96x96", fit=mode)
        r = export.frame_pipeline(info, presets.builtin_values("original"), s, seq=seq)
        assert r.alpha
        out = r.render(gl_engine, sequence.grab(seq, 0, r.fit.dec_w, r.fit.dec_h, 8), 0)
        assert out.shape == (96, 96, 4) and out[0, 0, 3] == outside and out[48, -2, 3] == 255


# ------------------------------------------------------------------ arquivos exportados
def _decode_rgba(path: str, w: int, h: int, codec_hint: str = "") -> np.ndarray:
    dec = media.alpha_decoder("vp9") if codec_hint == "vp9" else []
    res = subprocess.run([media.ffmpeg(), "-v", "error", *dec, "-i", path, "-f", "rawvideo", "-pix_fmt", "rgba64le",
                          "pipe:1"], capture_output=True)
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
    return np.frombuffer(res.stdout, np.uint16).reshape(-1, h, w, 4)


def _export(engine, seq, s, out) -> ExportJob:
    info = sequence.media_info(seq)
    job = ExportJob(info=info, values=presets.builtin_values("original"), settings=s, out_path=str(out),
                    start_frame=0, end_frame=2, sequence=seq)
    export.run_job(job, engine)
    assert job.status == "concluido", job.error
    return job


ROUND_TRIPS = [
    ("prores", ExportSettings(codec="prores", container="mov", pix="yuva444p10le", profile="4", audio="none"),
     "prores_ks", 0.01),
    ("png16", ExportSettings(codec="png_seq", container="png", pix="rgba64be", audio="none", dither=False),
     "png", 1 / 65535),
    ("png8", ExportSettings(codec="png_seq", container="png", pix="rgba", audio="none"), "png", 1 / 255),
    ("tiff", ExportSettings(codec="tiff_seq", container="tif", pix="rgba64le", audio="none", dither=False),
     "tiff", 1 / 65535),
    ("vp9", ExportSettings(codec="vp9", container="webm", pix="yuva420p", quality=20, preset="4", audio="none"),
     "libvpx-vp9", 0.06),
]


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("name,s,encoder,tol", ROUND_TRIPS, ids=[r[0] for r in ROUND_TRIPS])
def test_exported_alpha_matches_the_montage(gl_engine, renderer, tmp_path, name, s, encoder, tol):
    if encoder not in media.encoders():
        pytest.skip(f"o ffmpeg desta máquina não tem o {encoder}")
    if name == "vp9" and not media.alpha_decoder("vp9"):
        pytest.skip("o ffmpeg desta máquina não tem o decodificador libvpx-vp9")
    seq = montage()
    out = tmp_path / f"alfa.{s.container}"
    _export(gl_engine, seq, s, out)
    want = expected_alpha()
    if export.is_sequence(s):
        files = sorted(export.sequence_dir(str(out)).glob(f"*.{s.container}"))
        assert len(files) == 3, files
        probe = media.probe(str(files[0]))
        assert probe.has_alpha and probe.pix_fmt.startswith("rgba"), probe.pix_fmt
        frames = np.concatenate([_decode_rgba(str(f), W, H) for f in files])
    else:
        probe = media.probe(str(out))
        assert probe.has_alpha
        if name == "prores":
            assert probe.pix_fmt.startswith("yuva444p") and probe.profile.startswith("4444")
        frames = _decode_rgba(str(out), W, H, "vp9" if name == "vp9" else "")
    assert len(frames) == 3
    alpha = frames[..., 3] / 65535.0
    inner = np.s_[:, 2:-2, 2:-2]  # o VP9 (4:2:0, com perdas) borra a borda do alfa
    err = np.abs(alpha - want[None])[inner] if name == "vp9" else np.abs(alpha - want[None])
    assert err.max() <= tol + 1e-9, (name, err.max())


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_opaque_export_of_a_transparent_montage_is_the_opaque_export(gl_engine, renderer, tmp_path):
    s = ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="none", dither=False)
    a = tmp_path / "transp.mkv"
    b = tmp_path / "opaco.mkv"
    _export(gl_engine, montage(transparent=True), s, a)
    _export(gl_engine, montage(transparent=False), s, b)
    fa = read_all(media.FrameReader(media.probe(str(a)), W, H, 16))
    fb = read_all(media.FrameReader(media.probe(str(b)), W, H, 16))
    assert len(fa) == len(fb) == 3 and all(np.array_equal(x, y) for x, y in zip(fa, fb))


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_save_still_with_alpha_and_cli_frame(gl_engine, renderer, tmp_path):
    seq = montage()
    img = frame.Recipe.for_source(presets.builtin_values("original"), 24.0, 16, legal=False, seq=seq,
                                  alpha=True).render(gl_engine, sequence.grab(seq, 0, W, H, 16), 0)
    for ext in (".png", ".tif"):
        path = tmp_path / f"q{ext}"
        export.save_still(img, str(path))
        info = media.probe(str(path))
        assert info.has_alpha, ext
        back = _decode_rgba(str(path), W, H)[0]
        assert np.array_equal(back, img), ext
    with pytest.raises(ValueError):
        export.save_still(img, str(tmp_path / "q.jpg"))


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_preview_is_the_exported_rgba_frame(gl_engine, renderer, tmp_path):
    """A prévia da janela de exportação (`preview_frame`) é o quadro gravado, com o alfa."""
    seq = montage()
    film = presets.builtin_values("vision3_500t")
    s = ExportSettings(codec="png_seq", container="png", pix="rgba64be", audio="none", dither=False)
    out = tmp_path / "q.png"
    info = sequence.media_info(seq)
    job = ExportJob(info=info, values=film, settings=s, out_path=str(out), start_frame=0, end_frame=2, sequence=seq)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    files = sorted(export.sequence_dir(str(out)).glob("*.png"))
    for n in (0, 2):
        prev = export.preview_frame(gl_engine, info, film, s, n, seq=seq, depth=16)
        assert prev.shape == (H, W, 4)
        assert np.array_equal(prev, _decode_rgba(str(files[n]), W, H)[0]), n


def test_checkerboard_view():
    from pelicula.ui import alphaview
    rgba = np.zeros((16, 16, 4), np.uint8)
    rgba[:, 8:] = (200, 100, 50, 255)
    out = alphaview.over_checker(rgba)
    assert out.shape == (16, 16, 3) and out.dtype == np.uint8
    assert tuple(out[0, 0]) == (alphaview.LIGHT,) * 3 and tuple(out[0, 8 - 1 + 1]) == (200, 100, 50)
    assert tuple(out[8, 0]) == (alphaview.DARK,) * 3
    half = np.dstack([np.full((8, 8, 3), 100, np.uint8), np.full((8, 8), 128, np.uint8)])
    straight = alphaview.over_checker(half)
    premul = alphaview.over_checker(np.dstack([half[..., :3] // 2, half[..., 3]]), premultiplied=True)
    assert np.abs(straight.astype(int) - premul.astype(int)).max() <= 1
    rgb16 = np.full((4, 4, 3), 65535, np.uint16)
    assert alphaview.over_checker(rgb16).max() == 255


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_alpha_export_of_an_opaque_file_is_fully_opaque(gl_engine, sample_info, tmp_path):
    """Um arquivo sem transparência num formato com alfa: o alfa sai todo opaco (o quadro tem 4 canais)."""
    if "prores_ks" not in media.encoders():
        pytest.skip("o ffmpeg desta máquina não tem o prores_ks")
    s = ExportSettings(codec="prores", container="mov", pix="yuva444p10le", profile="4", audio="none")
    out = tmp_path / "opaco4444.mov"
    job = ExportJob(info=sample_info, values=presets.builtin_values("vision3_500t"), settings=s, out_path=str(out),
                    start_frame=0, end_frame=1)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    frames = _decode_rgba(str(out), sample_info.width, sample_info.height)
    assert len(frames) == 2 and frames[..., 3].min() >= 65535 - 64
