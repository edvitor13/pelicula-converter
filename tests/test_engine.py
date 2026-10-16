"""Motor na GPU: identidade, profundidade, bake de LUT, presets e scan (pulados sem OpenGL 3.3)."""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import engine as engine_mod
from pelicula import look, luts, params, presets

pytestmark = pytest.mark.gpu

W, H = 320, 180


def neutral(**over) -> dict:
    v = params.defaults()
    v["bitola"] = "nenhuma"
    v.update(over)
    return v


def render(eng, img, values, frame=0, depth=8, dither=False, lut=None):
    h, w = img.shape[:2]
    eng.set_input(img)
    return eng.render(look.build_plan(values, w, h, frame, 24.0, lut, dither=dither), depth)


def identity_cube(n: int) -> np.ndarray:
    ax = np.linspace(0.0, 1.0, n, dtype=np.float32)
    b, g, r = np.meshgrid(ax, ax, ax, indexing="ij")
    return np.stack([r.ravel(), g.ravel(), b.ravel()], axis=1)


def apply_cube(img: np.ndarray, data: np.ndarray, n: int) -> np.ndarray:
    """Interpolação trilinear de um LUT em ordem .cube (R mais rápido) sobre uma imagem 0..1."""
    lut = data.reshape(n, n, n, 3)  # [b, g, r]
    x = np.clip(img, 0, 1) * (n - 1)
    i0 = np.minimum(np.floor(x).astype(int), n - 2)
    f = x - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    out = 0
    for db in (0, 1):
        for dg in (0, 1):
            for dr in (0, 1):
                wgt = (fr if dr else 1 - fr) * (fg if dg else 1 - fg) * (fb if db else 1 - fb)
                out = out + wgt * lut[b0 + db, g0 + dg, r0 + dr]
    return out


# ------------------------------------------------------------------ básico
def test_engine_info(gl_engine):
    assert isinstance(gl_engine.renderer, str) and gl_engine.renderer
    assert set(gl_engine.progs) >= {"base", "extract", "blur", "noise", "final", "bake"}


def test_render_without_input_raises(gl_engine):
    other = engine_mod.Engine(gl_engine.ctx)  # mesmo contexto (um contexto por thread)
    with pytest.raises(RuntimeError):
        other.render(look.build_plan(neutral(), W, H, 0, 24.0))


@pytest.mark.parametrize("depth, dtype", [(8, np.uint8), (16, np.uint16)])
def test_render_shapes_and_dtypes(gl_engine, test_rgb, depth, dtype):
    out = render(gl_engine, test_rgb, presets.builtin_values("vision3_250d"), depth=depth)
    assert out.shape == (H, W, 3) and out.dtype == dtype
    assert out.flags.c_contiguous


def test_neutral_8bit_is_identity(gl_engine, test_rgb):
    out = render(gl_engine, test_rgb, neutral())
    diff = np.abs(out.astype(int) - test_rgb.astype(int))
    assert diff.max() <= 1
    assert diff.mean() < 0.01


def test_neutral_with_dither_stays_within_two_levels(gl_engine, test_rgb):
    out = render(gl_engine, test_rgb, neutral(), dither=True)
    diff = np.abs(out.astype(int) - test_rgb.astype(int))
    assert diff.max() <= 2 and diff.mean() < 0.5


def test_original_preset_is_identity(gl_engine, test_rgb):
    out = render(gl_engine, test_rgb, presets.builtin_values("original"))
    assert np.abs(out.astype(int) - test_rgb.astype(int)).max() <= 1


def test_neutral_16bit_is_identity_within_one_8bit_level(gl_engine, test_rgb):
    src16 = test_rgb.astype(np.uint16) * 257
    out = render(gl_engine, src16, neutral(), depth=16)
    diff = np.abs(out.astype(np.int64) - src16.astype(np.int64))
    # Só o branco puro perde um pouco (a curva neutra satura em +8 stops): ~1,3 nível de 8 bits.
    assert diff.max() <= 1.5 * 257
    assert diff[test_rgb.max(axis=2) < 250].max() <= 0.25 * 257
    assert diff.mean() < 16


def test_odd_sizes_and_16bit_input(gl_engine, test_rgb):
    img = np.ascontiguousarray(test_rgb[:H - 1, :W - 1])
    out = render(gl_engine, img, neutral())
    assert out.shape == img.shape
    assert np.abs(out.astype(int) - img.astype(int)).max() <= 1
    out8 = render(gl_engine, img.astype(np.uint16) * 257, neutral(), depth=8)
    assert np.abs(out8.astype(int) - img.astype(int)).max() <= 1


def test_render_is_deterministic(gl_engine, test_rgb):
    v = presets.builtin_values("super8_kodachrome")
    a = render(gl_engine, test_rgb, v, frame=17, dither=True)
    render(gl_engine, test_rgb, v, frame=3)
    b = render(gl_engine, test_rgb, v, frame=17, dither=True)
    assert np.array_equal(a, b)


def test_animated_grain_changes_between_frames(gl_engine, test_rgb):
    v = neutral(grao_on=True, grao_forca=2.0)
    a = render(gl_engine, test_rgb, v, frame=0)
    b = render(gl_engine, test_rgb, v, frame=1)
    assert not np.array_equal(a, b)
    v["grao_animado"] = False
    assert np.array_equal(render(gl_engine, test_rgb, v, frame=0), render(gl_engine, test_rgb, v, frame=1))


def test_mix_zero_returns_original(gl_engine, test_rgb):
    v = presets.builtin_values("bleach_bypass")
    v["mix_geral"] = 0.0
    out = render(gl_engine, test_rgb, v)
    assert np.abs(out.astype(int) - test_rgb.astype(int)).max() <= 1


def test_exposure_brightens(gl_engine, test_rgb):
    dark = render(gl_engine, test_rgb, neutral(exposicao=-1.0)).mean()
    base = render(gl_engine, test_rgb, neutral()).mean()
    bright = render(gl_engine, test_rgb, neutral(exposicao=1.0)).mean()
    assert dark < base < bright


def test_frame_bars(gl_engine, test_rgb):
    out = render(gl_engine, test_rgb, neutral(mold_on=True, proporcao="2.39", cor_barras=[0.0, 0.0, 0.0]))
    bar = int(round((H - W / 2.39) / 2))
    assert out[: bar - 2].max() == 0 and out[H - bar + 2:].max() == 0
    assert out[H // 2].max() > 0


# ------------------------------------------------------------------ bake de LUT
@pytest.mark.parametrize("n", [9, 17, 33])
def test_bake_lut_shape_and_identity(gl_engine, n):
    data = gl_engine.bake_lut(neutral(), n)
    assert data.shape == (n ** 3, 3) and data.dtype == np.float32
    err = np.abs(data - identity_cube(n))
    assert err.max() < 0.006 and err.mean() < 0.001


def test_baked_lut_matches_render_for_color_only_look(gl_engine, test_rgb):
    v = neutral(cor_on=True, copia="k2383", contraste=1.1, saturacao=1.2, sombras_forca=0.2, luzes_forca=0.15)
    n = 33
    data = gl_engine.bake_lut(v, n)
    via_lut = apply_cube(test_rgb.astype(np.float64) / 255.0, data, n) * 255.0
    out = render(gl_engine, test_rgb, v).astype(np.float64)
    diff = np.abs(via_lut - out)
    assert diff.mean() < 0.6
    assert np.percentile(diff, 99.5) <= 3.0


def test_bake_lut_save_and_reload_applies_same_look(gl_engine, test_rgb, tmp_path):
    v = neutral(cor_on=True, copia="f3513", saturacao=0.8)
    n = 17
    data = gl_engine.bake_lut(v, n)
    path = str(tmp_path / "look.cube")
    luts.save_cube(path, data, n, "teste")
    assert engine_mod.lut_info(path) == (n, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    # aplicar o LUT exportado "no lugar do look" deve chegar perto do look original
    lut_vals = neutral(lut_on=True, lut_arquivo=path, lut_posicao="lugar", lut_entrada="rec709")
    via_lut = render(gl_engine, test_rgb, lut_vals, lut=engine_mod.lut_info(path)).astype(int)
    direct = render(gl_engine, test_rgb, v).astype(int)
    diff = np.abs(via_lut - direct)
    assert diff.mean() < 1.0 and np.percentile(diff, 99) <= 4


def test_identity_lut_after_look_changes_nothing(gl_engine, test_rgb, tmp_path):
    path = str(tmp_path / "id.cube")
    luts.save_cube(path, identity_cube(33), 33, "id")
    v = presets.builtin_values("portra_400")
    v["grao_on"] = False  # o LUT corta em 0..1 antes do grão; sem grão a comparação é direta
    base = render(gl_engine, test_rgb, v).astype(int)
    v.update(lut_on=True, lut_arquivo=path, lut_posicao="depois", lut_entrada="rec709", lut_forca=1.0)
    out = render(gl_engine, test_rgb, v, lut=engine_mod.lut_info(path)).astype(int)
    assert np.abs(out - base).max() <= 2


def test_cached_lut_and_lut_info(tmp_path):
    p = tmp_path / "a.cube"
    luts.save_cube(str(p), identity_cube(5), 5, "a")
    a = engine_mod.cached_lut(str(p))
    assert a is engine_mod.cached_lut(str(p))
    assert engine_mod.cached_lut("") is None and engine_mod.cached_lut(str(tmp_path / "x.cube")) is None
    bad = tmp_path / "ruim.cube"
    bad.write_text("nada", encoding="utf-8")
    assert engine_mod.lut_info(str(bad)) is None
    assert engine_mod.lut_info(str(tmp_path / "nao_existe.cube")) is None


# ------------------------------------------------------------------ presets e scan
@pytest.mark.parametrize("pid", [p["id"] for p in presets.BUILTIN])
def test_every_preset_renders_and_changes_image(gl_engine, test_rgb, qapp, pid):
    v = presets.builtin_values(pid)
    out = render(gl_engine, test_rgb, v, frame=5, dither=True)
    out16 = render(gl_engine, test_rgb, v, frame=5, depth=16)
    lut = gl_engine.bake_lut(v, 9)
    assert np.isfinite(lut).all()
    diff = np.abs(out.astype(int) - test_rgb.astype(int)).mean()
    if pid == "original":
        assert diff < 0.5
    else:
        assert diff > 2.0, f"{pid} quase não mudou a imagem ({diff:.2f})"
        assert out.std() > 5, f"{pid} gerou imagem chapada"
    assert np.abs(out16.astype(np.float64) / 257.0 - out).mean() < 2.0


def test_scan_render_draws_perforations_and_edge_text(gl_engine, test_rgb, qapp):
    gl_engine._text_key = None  # sem cache de um texto desenhado antes do QGuiApplication existir
    v = neutral(scan_on=True, scan_formato="35mm", scan_texto="auto", iso="500")
    eng = gl_engine
    eng.set_input(test_rgb)
    plan = look.build_plan(v, W, H, 0, 24.0, None, dither=False)
    assert "500T" in plan.edge_text
    with_text = eng.render(plan, 8)
    assert plan.uniforms["u_text_aspect"] > 5.0
    no_text = render(eng, test_rgb, dict(v, scan_texto="nenhum"))
    plain = render(eng, test_rgb, neutral())
    assert not np.array_equal(with_text, plain)
    # coluna dos furos (x ≈ 3,4 mm de 36,75 mm visíveis): furo claro e película escura
    mmpp = 35.0 * 1.05 / W
    col = int(round((3.41 + 35.0 * 0.025) / mmpp))
    strip = with_text[:, col - 2:col + 3].max(axis=2)
    assert strip.max() > 180 and strip.min() < 60
    # o texto aparece só nas faixas das bordas (0,35..1,75 mm e 33,25..34,65 mm)
    d = np.abs(with_text.astype(int) - no_text.astype(int)).sum(axis=(0, 2))

    def px(mm):
        return int((mm + 35.0 * 0.025) / mmpp)

    left, right = d[px(0.35):px(1.75) + 2].sum(), d[px(33.25):px(34.65) + 2].sum()
    assert left + right > 0
    assert d[px(1.75) + 6:px(33.25) - 6].sum() == 0


def test_scan_without_qt_app_text_is_skipped(gl_engine, test_rgb, qapp, monkeypatch):
    from pelicula import edgetext
    monkeypatch.setattr(edgetext, "render", lambda text, height=64: None)
    gl_engine._text_key = None
    try:
        v = neutral(scan_on=True, scan_texto="kodak_2383")
        gl_engine.set_input(test_rgb)
        plan = look.build_plan(v, W, H, 0, 24.0, None, dither=False)
        out = gl_engine.render(plan, 8)
        assert plan.uniforms["u_text_aspect"] == 0.0
        assert out.shape == (H, W, 3)
    finally:
        gl_engine._text_key = None
