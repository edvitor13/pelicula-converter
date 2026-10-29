"""Grão físico: Tamanho do cristal e Variação do tamanho (1.6, fase 3; `grao_fisico.extras`, ARQUITETURA §30.8).

- o padrão (cristal 1, variação 0%) não muda o plano nem o programa (a referência da BASE fica em test_grao.py);
- a compensação do KAPPA é a de `tools/ajustar_grao.py` e mantém o sigma D da abertura de 48 µm na referência;
- os raios variáveis: E[ρ²] = 1 (a densidade média não muda), a variância do tamanho cresce com a variação, a
  cobertura média continua a lei de Nutting e a variância é a do modelo booleano exato com raios aleatórios;
- no look: brilho médio igual, LUT igual, determinismo, nada velho no programa, prévia = exportação, resolução.
"""

from __future__ import annotations

import math
from pathlib import Path

import moderngl
import numpy as np
import pytest

from pelicula import grao, grao_fisico as gf, look, params, shaders

ROOT = Path(__file__).resolve().parents[1]


def vals(**kw) -> dict:
    v = params.defaults()
    v.update(bitola="nenhuma", bitola_vinheta=0.0, lab_on=True, grao_on=True, lab_grao=True,
             lab_grao_modelo="fisico")
    v.update(kw)
    return params.sanitize(v)


def plan(v, w=1920, h=1080, frame=0):
    return look.build_plan(v, w, h, frame, 24.0, None, dither=False)


def code16(lin) -> np.ndarray:
    lin = np.asarray(lin, dtype=np.float64)
    c = np.where(lin < 0.018, 4.5 * lin, 1.099 * np.power(np.maximum(lin, 1e-9), 0.45) - 0.099)
    return np.rint(np.clip(c, 0, 1) * 65535).astype(np.uint16)


def render(engine, img, v, frame=0):
    h, w = img.shape[:2]
    engine.set_input(img)
    return engine.render(plan(v, w, h, frame), 16).astype(np.float64) / 65535.0


def _tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ajustar_grao", ROOT / "tools" / "ajustar_grao.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ padrão e plano
def test_defaults_are_neutral():
    d = params.defaults()
    assert d["lab_grao_cristal"] == 1.0 and d["lab_grao_variacao"] == 0.0
    assert params.PARAMS["lab_grao_cristal"].advanced and params.PARAMS["lab_grao_variacao"].advanced
    base = plan(vals()).uniforms
    assert "u_pg_var" not in base
    same = plan(vals(lab_grao_cristal=1.0, lab_grao_variacao=0.0)).uniforms
    assert same == base
    assert gf.kappa_factor(1.0, 0.0) == (1.0, 1.0, 1.0)
    # sem o modelo físico os dois ajustes não fazem nada
    noise = plan(vals(lab_grao_modelo="ruido")).uniforms
    assert plan(vals(lab_grao_modelo="ruido", lab_grao_cristal=2.0, lab_grao_variacao=1.0)).uniforms == noise


def test_plan_values():
    base = plan(vals()).uniforms
    u = plan(vals(lab_grao_cristal=1.5, lab_grao_variacao=0.6)).uniforms
    assert u["u_pg_r"] == pytest.approx(base["u_pg_r"] * 1.5)
    f = gf.kappa_factor(1.5, 0.6)
    np.testing.assert_allclose(u["u_pg_amp"], np.asarray(base["u_pg_amp"]) * f, rtol=1e-12)
    s, inv, rmax = u["u_pg_var"]
    assert s == pytest.approx(0.3) and inv > 1.0 and rmax == pytest.approx(math.exp(s * gf.Z_CLIP - s * s) * inv)
    # só o cristal: o mesmo programa de raio único
    assert "u_pg_var" not in plan(vals(lab_grao_cristal=0.7)).uniforms


def test_uniform_in_the_variant_program_only():
    assert "u_pg_var" not in gf.FINAL_PG and "uniform vec3 u_pg_var;" in gf.program("final_pgv")
    assert gf.FINAL_PG.count("pgRadius") == 0 and gf.program("final_pgv").count("pgRadius(h2)") == 1
    assert "labPathX" in gf.program("final_pgv_lx")


# ------------------------------------------------------------------ calibração
def test_tables_are_the_tool_calibration():
    """Uma amostra das tabelas (o cálculo inteiro leva ~30 s): cristal 2 e variação 100% no verde, e os nós."""
    tool = _tool()
    assert tool.CRYSTAL_KNOTS == gf.CRYSTAL_KNOTS and tool.VARIATION_KNOTS == gf.VARIATION_KNOTS
    ap = tool._ref_aperture()
    d = gf.REF_DENSITY[1]
    base = tool.physical_rel_sigma_v(d, ap, 0.0)
    assert gf.CRYSTAL_K[1][-1] == pytest.approx(base / tool.physical_rel_sigma_v(d, ap / 2.0, 0.0), abs=1e-5)
    assert gf.VARIATION_K[1][-1] == pytest.approx(base / tool.physical_rel_sigma_v(d, ap, 1.0), abs=1e-5)
    # a conta nova bate com a de sempre (a do KAPPA) sem variação
    assert base == pytest.approx(tool.physical_aperture_rel_sigma(d, ap), rel=1e-5)
    # cristal maior = menos KAPPA (mais correlação na abertura); mais variação = menos KAPPA (E[ρ⁴] > 1)
    for row in gf.CRYSTAL_K:
        assert (np.diff(row) < 0).all() and row[4] == 1.0
    for row in gf.VARIATION_K:
        assert (np.diff(row) < 0).all() and row[0] == 1.0


def test_radius_distribution_keeps_the_mean_area():
    tool = _tool()
    for var in (0.25, 0.6, 1.0):
        rho, w = tool._radius_quadrature(var, 4001)
        assert float((rho ** 2 * w).sum()) == pytest.approx(1.0, abs=1e-6)
        s, _inv, rmax = gf.radius_params(var)
        assert rho.max() == pytest.approx(rmax, rel=1e-9)
    # a mesma conta do shader (Box–Muller cortado) em numpy, com muitas amostras
    rng = np.random.default_rng(3)
    u1 = (rng.integers(0, 1 << 24, 2_000_000) + 0.5) / 16777216.0
    u2 = rng.integers(0, 1 << 24, 2_000_000) / 16777216.0
    z = np.clip(np.sqrt(-2 * np.log(u1)) * np.cos(2 * np.pi * u2), -gf.Z_CLIP, gf.Z_CLIP)
    s, inv, _ = gf.radius_params(1.0)
    r = np.exp(s * z - s * s) * inv
    assert (r ** 2).mean() == pytest.approx(1.0, abs=3e-3)


RADIUS_TEST = """
uniform int u_n0;
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    uint h2 = pcg(uint(p.x + p.y * 1024 + u_n0));
    f_out = vec4(pgRadius(h2), 0.0, 0.0, 1.0);
}
"""


@pytest.mark.gpu
def test_gpu_radius_spread_grows_with_the_variation(gl_engine):
    """A variância do tamanho do grão (do log do raio) cresce com a variação; E[ρ²] = 1 sempre."""
    ctx = gl_engine.ctx
    src = shaders.COMMON + gf.GLSL_V + RADIUS_TEST
    prog = ctx.program(vertex_shader=shaders.VERT, fragment_shader=src)
    vao = ctx.vertex_array(prog, [(gl_engine.vbo, "2f", "in_pos")])
    tex = ctx.texture((1024, 512), 4, dtype="f4")
    fbo = ctx.framebuffer([tex])
    spreads = []
    try:
        for var in (0.1, 0.5, 1.0):
            prog["u_pg_var"].value = gf.radius_params(var)
            prog["u_n0"].value = 7
            fbo.use()
            vao.render(moderngl.TRIANGLE_STRIP)
            r = np.frombuffer(fbo.read(components=1, dtype="f4"), np.float32).astype(np.float64)
            assert (r * r).mean() == pytest.approx(1.0, abs=6e-3)
            assert r.max() <= gf.radius_params(var)[2] * (1 + 1e-5)
            spreads.append(np.log(r).std())
    finally:
        for o in (fbo, tex, vao, prog):
            o.release()
    assert spreads[0] < spreads[1] < spreads[2]
    assert spreads[2] == pytest.approx(gf.VAR_SIGMA, rel=0.04)  # o corte em ±2,5 quase não muda o desvio


COVERAGE_TEST = """
uniform vec3 u_D;
void main() {
    vec2 p = gl_FragCoord.xy * u_pg_k;
    f_out = vec4(physCoverage(u_D, p, uint(u_pg_seed)), 1.0);
}
"""


def gpu_coverage_v(engine, densities, var, r=6.0, size=768, seed=11) -> np.ndarray:
    ctx = engine.ctx
    prog = ctx.program(vertex_shader=shaders.VERT, fragment_shader=shaders.COMMON + gf.GLSL_V + COVERAGE_TEST)
    vao = ctx.vertex_array(prog, [(engine.vbo, "2f", "in_pos")])
    tex = ctx.texture((size, size), 4, dtype="f4")
    fbo = ctx.framebuffer([tex])
    try:
        for k, val in (("u_D", tuple(float(d) for d in densities)), ("u_pg_k", 1.0), ("u_pg_r", float(r)),
                       ("u_pg_chroma", 1.0), ("u_pg_seed", int(seed)), ("u_pg_var", gf.radius_params(var))):
            prog[k].value = val
        fbo.use()
        vao.render(moderngl.TRIANGLE_STRIP)
        data = fbo.read(components=3, dtype="f4")
    finally:
        for o in (fbo, tex, vao, prog):
            o.release()
    return np.frombuffer(data, np.float32).reshape(size, size, 3).astype(np.float64)


def exact_pixel_variance(density: float, var: float) -> float:
    """Variância exata de û (spot de N pontos) com raios aleatórios: Cov = (1 − u)²(e^(λ·E[γ_ρ(h)]) − 1)."""
    rho, w = _tool()._radius_quadrature(var, 401)
    o = gf.offsets()
    h = np.linalg.norm(o[:, None] - o[None], axis=-1)
    eg = sum(wi * ri * ri * gf.overlap_area(h / ri) for ri, wi in zip(rho, w))
    lam = density * gf.LN10 / math.pi
    return float(((10.0 ** -density) ** 2 * np.expm1(lam * eg)).mean())


@pytest.mark.gpu
def test_gpu_coverage_with_variable_radii_is_the_boolean_model(gl_engine):
    dens = (0.1, 0.5, 1.5)
    # grãos de até 2,7 raios: a média de uma imagem varia mais; 6 sementes (desvio da média ≈ 0,004 em D = 0,1)
    cov = np.concatenate([gpu_coverage_v(gl_engine, dens, 1.0, seed=s) for s in range(1, 7)], axis=0)
    for c, d in enumerate(dens):
        assert cov[..., c].mean() == pytest.approx(1.0 - 10.0 ** -d, abs=0.01)
        assert cov[..., c].var() == pytest.approx(exact_pixel_variance(d, 1.0), rel=0.06)
    # mais variação = mais variância por pixel (grãos grandes cobrem vários pontos do spot juntos)
    fixed = gpu_coverage_v(gl_engine, dens, 0.0)
    assert cov[..., 1].var() > fixed[..., 1].var()


# ------------------------------------------------------------------ no look
@pytest.mark.gpu
@pytest.mark.parametrize("over", [dict(lab_grao_cristal=1.6), dict(lab_grao_variacao=1.0),
                                  dict(lab_grao_cristal=0.7, lab_grao_variacao=0.5)],
                         ids=["cristal", "variacao", "os_dois"])
def test_aperture_sigma_d_stays_the_datasheet(gl_engine, over):
    """O sigma D numa abertura de 48 µm, no cinza médio, continua o do datasheet com o cristal e a variação: a média
    da transmitância de `physGrain` numa abertura circular (como em test_grao_fisico)."""
    h = w = 1440
    k = 1080.0 / h
    ctx = gl_engine.ctx
    var = over.get("lab_grao_variacao", 0.0)
    glsl = gf.GLSL_V if var > 0 else gf.GLSL
    src = shaders.COMMON + glsl + """
uniform vec3 u_D;
void main() {
    f_out = vec4(physGrain(u_D, gl_FragCoord.xy * u_pg_k, uint(u_pg_seed)), 1.0);
}
"""
    prog = ctx.program(vertex_shader=shaders.VERT, fragment_shader=src)
    vao = ctx.vertex_array(prog, [(gl_engine.vbo, "2f", "in_pos")])
    tex = ctx.texture((w, h), 4, dtype="f4")
    fbo = ctx.framebuffer([tex])
    U = plan(vals(bitola="35mm", **over)).uniforms
    try:
        names = ["u_pg_r", "u_pg_amp", "u_pg_chroma", "u_pg_seed"] + (["u_pg_var"] if var > 0 else [])
        for name in names:
            prog[name].value = U[name]
        prog["u_pg_k"].value = k
        prog["u_D"].value = gf.REF_DENSITY
        fbo.use()
        vao.render(moderngl.TRIANGLE_STRIP)
        dd = np.frombuffer(fbo.read(components=3, dtype="f4"), np.float32).reshape(h, w, 3).astype(np.float64)
    finally:
        for o in (fbo, tex, vao, prog):
            o.release()
    diam = 0.048 * 1920 / 24.9 / k
    yy, xx = np.mgrid[0:h, 0:w]
    ker = (np.hypot(np.minimum(xx, w - xx), np.minimum(yy, h - yy)) < diam / 2).astype(np.float64)
    ker /= ker.sum()
    sig = []
    for c in range(3):
        t = 10.0 ** -dd[..., c]
        avg = np.real(np.fft.ifft2(np.fft.fft2(t) * np.fft.fft2(ker)))
        sig.append(np.std(-np.log10(avg)))
    np.testing.assert_allclose(sig, grao.NEG_SIGMA_D, rtol=0.08)


def steps_image(w=960, h=270, stops=(-4, -1, 0, 2)):
    img = np.zeros((h, w, 3))
    bw = w // len(stops)
    for i, st in enumerate(stops):
        img[:, i * bw:(i + 1) * bw] = 0.18 * 2.0 ** st
    return code16(img), bw


@pytest.mark.gpu
def test_mean_brightness_and_lut_are_kept(gl_engine):
    img, bw = steps_image()
    base = np.mean([render(gl_engine, img, vals(), f) for f in (1, 2)], axis=0)
    for over in (dict(lab_grao_variacao=1.0), dict(lab_grao_cristal=2.0, lab_grao_variacao=0.4)):
        out = np.mean([render(gl_engine, img, vals(**over), f) for f in (1, 2)], axis=0)
        for i in range(4):
            band = (slice(20, -20), slice(i * bw + 10, (i + 1) * bw - 10))
            np.testing.assert_allclose(out[band].mean(axis=(0, 1)), base[band].mean(axis=(0, 1)), atol=2.5e-3)
    v = vals()
    assert np.array_equal(gl_engine.bake_lut(v, 17), gl_engine.bake_lut(dict(v, lab_grao_cristal=2.0,
                                                                            lab_grao_variacao=1.0), 17))


@pytest.mark.gpu
def test_deterministic_and_nothing_stale(gl_engine):
    img, _bw = steps_image(320, 90)
    v = vals(lab_grao_variacao=0.7, lab_grao_cristal=1.3)
    a = render(gl_engine, img, v, 7)
    assert np.array_equal(a, render(gl_engine, img, v, 7))
    assert not np.array_equal(a, render(gl_engine, img, v, 8))
    plain = render(gl_engine, img, vals(), 7)
    render(gl_engine, img, v, 7)
    assert np.array_equal(plain, render(gl_engine, img, vals(), 7))
    assert not np.array_equal(plain, a)
    lx = render(gl_engine, img, dict(v, lab_vencida=15.0), 7)  # final_pgv_lx
    assert gl_engine.progs.get("final_pgv_lx") is not None and not np.array_equal(lx, a)


@pytest.mark.gpu
def test_preview_equals_export(gl_engine, make_info):
    from pelicula import export, frame as framemod
    img, _bw = steps_image(320, 180)
    v = vals(lab_grao_variacao=0.5, lab_grao_cristal=1.2)
    info = make_info(width=320, height=180)
    preview = framemod.Recipe.for_source(v, 24.0, 16, legal=True)
    exp = export.frame_pipeline(info, v, export.ExportSettings(codec="ffv1", container="mkv", pix="yuv444p16le"),
                                depth=16)
    assert np.array_equal(preview.render(gl_engine, img, 3), exp.render(gl_engine, img, 3))


@pytest.mark.gpu
def test_statistics_do_not_depend_on_resolution(gl_engine):
    stats = []
    for h in (1080, 2160):
        img = code16(np.full((h // 2, h, 3), 0.18))
        out = render(gl_engine, img, vals(lab_grao_variacao=1.0, lab_grao_cristal=1.4), 5)
        stats.append((out.mean(axis=(0, 1)), out.std(axis=(0, 1))))
    np.testing.assert_allclose(stats[0][0], stats[1][0], atol=1e-3)
    np.testing.assert_allclose(stats[0][1], stats[1][1], rtol=0.05)
