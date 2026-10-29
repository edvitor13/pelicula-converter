"""Transparência (canal alfa): detecção no ffprobe, decodificação RGBA pré-multiplicada e montagem na GPU.

Os arquivos são gerados com o ffmpeg: ProRes 4444 (yuva444p10le), PNG com alfa, WebM VP9 com alfa (libvpx),
PNG com paleta e transparência, e uma "borda" (círculo branco com o resto transparente e preto) para conferir
que nada escurece a borda ao reduzir ou girar. O fundo é um clipe de cor na V1.
"""

from __future__ import annotations

import json
import subprocess

import numpy as np
import pytest

from pelicula import cli, export, media, project, sequence
from pelicula import timeline as tl

W, H = 320, 180
ALPHA_COLS = "if(lt(X,100),0,if(lt(X,220),255*(X-100)/120,255))"  # transparente | rampa | opaco
CIRCLE = "255*lt(hypot(X-160,Y-90),60)"


def _run(ffmpeg, args, out):
    res = subprocess.run([ffmpeg, "-v", "error", "-y", "-nostdin", *args, str(out)], capture_output=True)
    return res.returncode == 0 and out.exists()


@pytest.fixture(scope="session")
def alpha_files(ffmpeg_ok, tmp_path_factory):
    d = tmp_path_factory.mktemp("alfa")
    src = ["-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=24:d=1"]
    pattern = f"format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{ALPHA_COLS}'"
    circle = (f"format=rgba,geq=r='{CIRCLE}':g='{CIRCLE}':b='{CIRCLE}':a='{CIRCLE}'")
    jobs = {
        "fundo.png": ["-f", "lavfi", "-i", f"color=c=0x3366CC:s={W}x{H}", "-frames:v", "1"],
        "prores.mov": src + ["-vf", pattern, "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"],
        "alfa.png": src + ["-vf", pattern, "-frames:v", "1"],
        "vp9.webm": src + ["-vf", pattern, "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
                           "-b:v", "4M"],
        "borda.png": src + ["-vf", circle, "-frames:v", "1"],
        "borda.mov": src + ["-vf", circle, "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"],
        "opaco.mp4": src + ["-c:v", "libx264", "-pix_fmt", "yuv420p"],
    }
    out = {}
    for name, args in jobs.items():
        if _run(ffmpeg_ok, args, d / name):
            out[name] = str(d / name)
    pal = d / "paleta.png"
    if _run(ffmpeg_ok, ["-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:d=0.1", "-filter_complex",
                        f"[0:v]format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*gte(X,160)',split[a][b];"
                        "[a]palettegen=reserve_transparent=1[p];[b][p]paletteuse=alpha_threshold=128",
                        "-frames:v", "1", "-pix_fmt", "pal8"], pal):
        out["paleta.png"] = str(pal)
    pal_opaque = d / "paleta_opaca.png"
    if _run(ffmpeg_ok, ["-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:d=0.1", "-frames:v", "1", "-pix_fmt", "pal8"],
            pal_opaque):
        out["paleta_opaca.png"] = str(pal_opaque)
    return out


def need(files, *names):
    for n in names:
        if n not in files:
            pytest.skip(f"o ffmpeg desta máquina não gerou {n}")
    return [files[n] for n in names]


def need_libvpx():
    if "libvpx-vp9" not in media.decoders():
        pytest.skip("o ffmpeg desta máquina não tem o decodificador libvpx-vp9")


# ------------------------------------------------------------------ detecção
@pytest.mark.ffmpeg
def test_probe_detects_alpha(alpha_files):
    prores, png, opaco = need(alpha_files, "prores.mov", "alfa.png", "opaco.mp4")
    assert media.probe(prores).has_alpha and media.probe(prores).pix_fmt.startswith("yuva444p")
    assert media.probe(png).has_alpha and media.probe_source(png).has_alpha
    assert not media.probe(opaco).has_alpha and not media.probe_source(opaco).has_alpha
    if "vp9.webm" in alpha_files:  # o ffprobe mostra yuv420p; a marca alpha_mode=1 diz que há alfa
        info = media.probe(alpha_files["vp9.webm"])
        assert info.pix_fmt == "yuv420p" and info.has_alpha
    if "paleta.png" in alpha_files:
        assert media.probe(alpha_files["paleta.png"]).pix_fmt == "pal8"
        assert media.probe(alpha_files["paleta.png"]).has_alpha
    if "paleta_opaca.png" in alpha_files:
        assert not media.probe(alpha_files["paleta_opaca.png"]).has_alpha


def test_stream_has_alpha_rules():
    assert media.stream_has_alpha({"pix_fmt": "yuva444p12le", "codec_name": "prores"})
    assert media.stream_has_alpha({"pix_fmt": "gbrap16le"}) and media.stream_has_alpha({"pix_fmt": "rgba64le"})
    assert media.stream_has_alpha({"pix_fmt": "ya8"}) and media.stream_has_alpha({"pix_fmt": "bgra"})
    assert not media.stream_has_alpha({"pix_fmt": "yuv420p", "codec_name": "h264", "tags": {"alpha_mode": "1"}})
    assert media.stream_has_alpha({"pix_fmt": "yuv420p", "codec_name": "vp9", "tags": {"ALPHA_MODE": "1"}})
    assert not media.stream_has_alpha({"pix_fmt": "yuv420p", "codec_name": "vp9", "tags": {"alpha_mode": "0"}})
    assert not media.stream_has_alpha({"pix_fmt": "rgb0"}) and not media.stream_has_alpha({})


def test_source_keeps_alpha_in_json_and_marks_the_feature(make_info):
    info = make_info(has_alpha=True, pix_fmt="yuva444p12le")
    src = tl.Source.from_info(info)
    assert src.has_alpha and src.to_info().has_alpha
    seq = tl.Sequence.for_source(src)
    d = json.loads(json.dumps(seq.to_json()))
    assert d["fontes"][0]["alfa"] is True and "alfa" in seq.features() and d["formato"] == tl.FORMAT_15
    assert tl.Sequence.from_json(d).sources[src.path].has_alpha
    # um arquivo com alfa sem mudanças continua "sem edição", mas o modo Película o lê pela montagem
    assert seq.is_trivial() == src.path and seq.direct_file() is None
    plain = tl.Sequence.for_source(tl.Source.from_info(make_info()))
    assert plain.direct_file() == plain.is_trivial()


def test_old_export_queue_without_alpha_field_opens(make_info):
    job = export.ExportJob(info=make_info(), values={}, settings=export.ExportSettings(), out_path="C:/o.mp4")
    d = job.to_dict()
    del d["midia"]["has_alpha"]  # fila guardada pela 1.4
    assert export.ExportJob.from_dict(d).info.has_alpha is False


@pytest.mark.ffmpeg
def test_cli_reads_alpha_files_through_the_montage(alpha_files):
    png, opaco = need(alpha_files, "alfa.png", "opaco.mp4")
    seq = cli.alpha_sequence(png)
    assert seq is not None and seq.sources[png].has_alpha
    assert cli.alpha_sequence(opaco) is None
    p = project.Project(media_path=png)
    assert cli._source_and_values(_save(p, png), None, [])[4] is not None


def _save(p, near):
    from pathlib import Path
    path = str(Path(near).with_name("projeto_alfa.plc"))
    project.save(p, path)
    return path


# ------------------------------------------------------------------ decodificação
@pytest.mark.ffmpeg
@pytest.mark.parametrize("name", ["prores.mov", "alfa.png", "vp9.webm"])
@pytest.mark.parametrize("depth", [8, 16])
def test_decode_is_premultiplied_rgba(alpha_files, name, depth):
    (path,) = need(alpha_files, name)
    if name.endswith(".webm"):
        need_libvpx()
    info = media.probe(path)
    rgba = media.grab_frame(info, 0, W, H, depth, alpha=True)
    rgb = media.grab_frame(info, 0, W, H, depth)
    mx = 255 if depth == 8 else 65535
    assert rgba.shape == (H, W, 4) and rgb.shape == (H, W, 3)
    a = rgba[..., 3].astype(float) / mx
    assert a[:, :95].max() <= 0.003 and a[:, 225:].min() >= 0.99  # transparente | opaco (com folga de formato)
    assert np.all(np.diff(a[90, 105:215]) >= -0.01)  # a rampa sobe
    assert rgba[:, :95, :3].max() <= 0.003 * mx  # pré-multiplicado: transparente = sem cor
    tol = 3 if depth == 8 else 3 * 257
    opaque = rgba[:, 230:, :3].astype(int)
    assert np.abs(opaque - rgb[:, 230:].astype(int)).max() <= tol + 0.004 * mx
    mid = rgba[:, 140:180].astype(float)
    straight = rgb[:, 140:180].astype(float)
    assert np.abs(mid[..., :3] - straight * mid[..., 3:4] / mx).max() <= tol + 0.004 * mx


@pytest.mark.ffmpeg
def test_native_vp9_decoder_drops_alpha_and_libvpx_keeps_it(alpha_files, ffmpeg_ok, monkeypatch):
    (path,) = need(alpha_files, "vp9.webm")
    need_libvpx()
    info = media.probe(path)
    assert media.alpha_decoder(info.codec) == ["-c:v", "libvpx-vp9"] and media.decodes_alpha(info)
    assert media.grab_frame(info, 0, W, H, 8, alpha=True)[..., 3].min() == 0
    # o decodificador nativo (o padrão do ffmpeg) descarta o alfa: era o fundo opaco do defeito
    raw = subprocess.run([ffmpeg_ok, "-v", "error", "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt",
                          "rgba", "pipe:1"], capture_output=True).stdout
    assert raw and np.frombuffer(raw, np.uint8)[3::4].min() == 255
    # compilação do ffmpeg sem o libvpx: o clipe sai opaco (3 canais), sem erro
    monkeypatch.setattr(media, "decoders", lambda: frozenset())
    assert media.alpha_decoder(info.codec) == [] and not media.decodes_alpha(info)
    assert media.grab_frame(info, 0, W, H, 8, alpha=True).shape == (H, W, 3)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
def test_palette_png_with_transparency(alpha_files, depth):
    (path,) = need(alpha_files, "paleta.png")
    info = media.probe(path)
    img = media.grab_frame(info, 0, W, H, depth, alpha=True)
    mx = 255 if depth == 8 else 65535
    assert img.shape == (H, W, 4)
    assert img[:, :150, 3].max() == 0 and img[:, 170:, 3].min() == mx


@pytest.mark.ffmpeg
def test_sources_without_alpha_decode_as_before(alpha_files):
    (path,) = need(alpha_files, "opaco.mp4")
    info = media.probe(path)
    img = media.grab_frame(info, 3, W, H, 8)
    assert img.shape == (H, W, 3)
    r = media.FrameReader(info, W, H, 8, 3, 1)
    try:
        assert r.channels == 3 and r.pix == "rgb24" and np.array_equal(r.read(), img)
    finally:
        r.close()


# ------------------------------------------------------------------ montagem na GPU
def _over_background(files, name, **values):
    fundo, path = need(files, "fundo.png", name)
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    bg = media.probe_source(fundo)
    seq.insert_media(bg, at=0)
    clip = seq.insert_media(media.probe_source(path), at=0, vtrack=1, with_audio=False)[0]
    seq.clips[0].dur = max(seq.clips[0].dur, clip.dur)
    if values:
        seq.set_values(clip.id, {**clip.values, **values})
    return seq, clip


def _bg(files, depth=8):
    """A cor do fundo como o app a lê (o PNG de cor sólida passa pelo yuv no ffmpeg: não é 0x3366CC exato)."""
    img = media.grab_frame(media.probe(files["fundo.png"]), 0, W, H, depth).astype(int)
    assert (img == img[0, 0]).all()
    return img[0, 0]


def _compose(engine, seq, t=0, depth=8, size=(W, H)):
    fl = sequence.grab(seq, t, size[0], size[1], depth, hq=True)
    return engine.compose(fl, seq, size[0], size[1], depth)


def _alpha_of(path, depth=8):
    a = media.grab_frame(media.probe(path), 0, W, H, depth, hq=True, alpha=True)[..., 3].astype(float)
    a /= 255.0 if depth == 8 else 65535.0
    e = 1 / 256
    return np.clip((a - e) / (1 - 2 * e), 0.0, 1.0)  # as pontas firmes do shader (clipAlpha)


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("name", ["prores.mov", "alfa.png", "vp9.webm"])
def test_background_shows_through_the_transparent_part(gl_engine, alpha_files, name):
    if name.endswith(".webm"):
        need_libvpx()
    seq, clip = _over_background(alpha_files, name)
    out = _compose(gl_engine, seq).astype(int)
    bg = _bg(alpha_files)
    assert (out[:, :95] == bg).all(), "o fundo tem que aparecer igual onde o alfa é 0"
    path = alpha_files[name]
    # a montagem lê em alta qualidade (hq): a mesma interpolação da cor 4:2:0 que a referência
    straight = media.grab_frame(media.probe(path), 0, W, H, 8, hq=True).astype(float)
    a = _alpha_of(path)[..., None]
    want = straight * a + bg * (1 - a)
    assert np.abs(out[:, 225:] - straight[:, 225:]).max() <= 3, "opaco: o clipe sem o fundo"
    assert np.abs(out[:, 100:220] - want[:, 100:220]).max() <= 3, "alfa parcial mistura com o fundo"
    # 16 bits: o mesmo, com o fundo exato
    out16 = _compose(gl_engine, seq, depth=16).astype(int)
    assert (out16[:, :95] == _bg(alpha_files, 16)).all()


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_opacity_crop_blend_and_transition_keep_the_transparency(gl_engine, alpha_files):
    seq, clip = _over_background(alpha_files, "alfa.png", opacidade=0.5)
    out = _compose(gl_engine, seq).astype(int)
    bg = _bg(alpha_files)
    straight = media.grab_frame(media.probe(alpha_files["alfa.png"]), 0, W, H, 8, hq=True).astype(float)
    assert (out[:, :95] == bg).all()
    assert np.abs(out[:, 225:] - (straight[:, 225:] * 0.5 + bg * 0.5)).max() <= 3
    seq.set_values(clip.id, {**clip.values, "opacidade": 1.0, "corte_dir": 0.2})
    out = _compose(gl_engine, seq).astype(int)
    assert (out[:, :95] == bg).all() and (np.abs(out[:, 262:] - bg) <= 1).all()
    for mode in ("tela", "multiplicar", "sobrepor", "adicionar", "clarear", "escurecer"):
        seq.set_values(clip.id, {**clip.values, "corte_dir": 0.0, "mesclagem": mode})
        out = _compose(gl_engine, seq).astype(int)
        assert (out[:, :95] == bg).all(), mode
        assert not (out[:, 230:] == bg).all(), mode
    seq.set_values(clip.id, {**clip.values, "mesclagem": "normal"})
    # transição (alfa da camada): o fundo continua igual onde o clipe é transparente
    layers = seq.layers_at(0)
    fl = sequence.grab(seq, 0, W, H, 8, hq=True)
    fl.layers[1].layer = tl.Layer(layers[1].clip, 0, 0.5)
    out = gl_engine.compose(fl, seq, W, H, 8).astype(int)
    assert (out[:, :95] == bg).all()
    assert np.abs(out[:, 225:] - (straight[:, 225:] * 0.5 + bg * 0.5)).max() <= 3


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("name", ["borda.png", "borda.mov"])
def test_no_dark_fringe_when_scaling_and_rotating(gl_engine, alpha_files, name):
    # círculo branco; fora dele o arquivo guarda preto com alfa 0. Sobre um fundo branco, nada pode escurecer.
    fundo, path = need(alpha_files, "fundo.png", name)
    seq = tl.Sequence(width=W, height=H, fps_str="24/1", background=(1.0, 1.0, 1.0))
    clip = seq.insert_media(media.probe_source(path), at=0, with_audio=False)[0]
    for values, size in (({"escala": 0.37, "rotacao": 13.0}, (W, H)),   # GPU: bilinear + mipmaps
                         ({}, (W // 2, H // 2)),                          # ffmpeg reduz na decodificação
                         ({"escala": 2.3, "pos_x": 0.1}, (W, H))):        # ampliado
        seq.set_values(clip.id, {**editparams_defaults(), **values})
        out = _compose(gl_engine, seq, size=size)
        assert out.min() >= 250, (name, values, int(out.min()))
        out16 = _compose(gl_engine, seq, depth=16, size=size)
        assert out16.min() >= 250 * 257, (name, values)


def editparams_defaults():
    from pelicula import editparams
    return editparams.VIDEO.defaults()


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_preview_and_export_read_the_same_alpha_frames(gl_engine, alpha_files):
    (path,) = need(alpha_files, "prores.mov")
    seq, clip = _over_background(alpha_files, "prores.mov", escala=0.8, rotacao=5.0)
    reader = sequence.SequenceReader(seq, W, H, 16, 0, 6, hq=True)
    try:
        for t in range(6):
            fl = reader.read()
            direct = sequence.grab(seq, t, W, H, 16, hq=True)
            for a, b in zip(fl.layers, direct.layers):
                assert a.image.shape == b.image.shape and np.array_equal(a.image, b.image), t
            assert np.array_equal(gl_engine.compose(fl, seq, W, H, 16), gl_engine.compose(direct, seq, W, H, 16))
    finally:
        reader.close()
    assert direct.layers[1].image.shape[2] == 4 and direct.layers[0].image.shape[2] == 3


@pytest.mark.gpu
def test_three_channel_layers_are_unchanged(gl_engine, test_rgb):
    s = tl.Source("cena.png", W, H, 24.0, "24/1", 1, 0.0, is_image=True)
    seq = tl.Sequence.for_source(s)
    fl = sequence.FrameLayers(0, [sequence.LayerImage(layer, test_rgb) for layer in seq.layers_at(0)])
    assert np.array_equal(gl_engine.compose(fl, seq, W, H, 8), test_rgb)
    opaque = np.dstack([test_rgb, np.full(test_rgb.shape[:2], 255, np.uint8)])
    fl4 = sequence.FrameLayers(0, [sequence.LayerImage(layer, opaque) for layer in seq.layers_at(0)])
    assert np.abs(gl_engine.compose(fl4, seq, W, H, 8).astype(int) - test_rgb).max() <= 1  # alfa 1 = a imagem


def test_auto_color_looks_only_at_the_visible_part():
    from pelicula import compositor
    rng = np.random.default_rng(7)
    rgb = (rng.random((64, 64, 3)) * 120 + 60).astype(np.uint8)
    rgba = np.zeros((64, 128, 4), np.uint8)  # metade transparente (preta), metade o quadro opaco
    rgba[:, 64:, :3], rgba[:, 64:, 3] = rgb, 255
    assert compositor.auto_adjust(rgba) == compositor.auto_adjust(np.ascontiguousarray(rgba[:, 64:, :3]))
    assert compositor.auto_adjust(np.zeros((8, 8, 4), np.uint8)) == compositor.auto_adjust(np.zeros((8, 8, 3),
                                                                                                    np.uint8))
