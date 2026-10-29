"""Grão físico (M1 da 1.6, `pelicula/grao_fisico.py`, ARQUITETURA §30.7): o modelo booleano no negativo.

- o padrão ("ruido") não muda nada (a referência da BASE fica em `tests/test_grao.py`); o modelo físico só com o
  Laboratório, o grão e o "Grão no negativo" ligados;
- uma referência em numpy do modelo booleano (discos exatos numa grade fina, processo de Poisson global) contra a
  aproximação da GPU (células com hash): média da cobertura por densidade, curva da variância, sinal da assimetria e
  comprimento de correlação;
- a calibração (sigma D numa abertura de 48 µm = datasheet, azul > verde > vermelho), a cópia moldando o grão,
  determinismo, prévia = exportação, independência de resolução e o LUT exportado igual.
"""

from __future__ import annotations

import math

import moderngl
import numpy as np
import pytest

from pelicula import grao, grao_fisico as gf, look, params, shaders


def vals(**kw) -> dict:
    v = params.defaults()
    v.update(bitola="nenhuma", bitola_vinheta=0.0, lab_on=True, grao_on=True, lab_grao=True,
             lab_grao_modelo="fisico")
    v.update(kw)
    return params.sanitize(v)


def plan(v, w=1920, h=1080, frame=0, **kw):
    return look.build_plan(v, w, h, frame, 24.0, None, dither=False, **kw)


def render(engine, img, v, frame=0, depth=16):
    h, w = img.shape[:2]
    engine.set_input(img)
    out = engine.render(plan(v, w, h, frame), depth)
    return out.astype(np.float64) / (255.0 if depth == 8 else 65535.0)


def code16(lin) -> np.ndarray:
    lin = np.asarray(lin, dtype=np.float64)
    c = np.where(lin < 0.018, 4.5 * lin, 1.099 * np.power(np.maximum(lin, 1e-9), 0.45) - 0.099)
    return np.rint(np.clip(c, 0, 1) * 65535).astype(np.uint16)


# ------------------------------------------------------------------ plano
def test_default_is_the_noise_model_and_the_module_is_beta_and_off():
    from pelicula import modules
    assert params.PARAMS["lab_grao_modelo"].default == "ruido"
    assert [k for k, _l in params.GRAO_MODELOS] == ["ruido", "fisico"]
    m = modules.get("grao_fisico")
    assert m.status == modules.BETA and not modules.default_enabled("grao_fisico")
    assert all("grao_fisico" not in ids for _i, _n, _d, ids in modules.PROFILES)
    assert "grao_fisico" in modules.used_by(vals())
    assert "grao_fisico" not in modules.used_by(vals(lab_grao_modelo="ruido"))
    assert "grao_fisico" not in modules.used_by(vals(lab_grao=False))


def test_physical_model_only_with_the_negative_grain():
    assert plan(vals(lab_grao_modelo="ruido")).uniforms["u_grain_on"] == 2
    for v in (vals(lab_grao=False), vals(lab_on=False), vals(grao_on=False), vals(grao_forca=0.0)):
        p = plan(v)
        assert p.uniforms["u_grain_on"] in (0, 1) and not any(k.startswith("u_pg_") for k in p.uniforms)
    p = plan(vals())
    assert p.uniforms["u_grain_on"] == 3 and "u_ngrain" not in p.uniforms and p.grain_size == 0.0


def test_plan_values(monkeypatch):
    v = vals(iso="500", lab_revelacao=1.0, grao_forca=0.7, bitola="16mm")
    p = plan(v)
    gauge = look.GAUGES["16mm"]
    U = p.uniforms
    assert U["u_pg_r"] == pytest.approx(gf.R_K * grao.grain_size_1080(v, gauge))
    amt = 0.7 * gauge["grain_amt"] * 2 ** 0.35 * 1.15
    assert U["u_pg_amp"] == pytest.approx(tuple(k * amt for k in gf.KAPPA))
    assert U["u_pg_chroma"] == pytest.approx(v["grao_cor"])
    assert U["u_pg_seed"] == (v["grao_semente"] * 7919 + 0) % 2147483647
    assert plan(v, frame=5).uniforms["u_pg_seed"] == U["u_pg_seed"] + 5
    assert plan(dict(v, grao_animado=False), frame=5).uniforms["u_pg_seed"] == U["u_pg_seed"]
    # a fração com o grão resolvido nunca passa de AMP_MAX
    big = vals(grao_forca=3.0, bitola="8mm", iso="500", lab_revelacao=3.0)
    assert max(plan(big).uniforms["u_pg_amp"]) < gf.AMP_MAX  # o máximo dos ajustes fica abaixo do limite
    monkeypatch.setattr(gf, "KAPPA", (1.0, 1.0, 1.0))
    assert plan(big).uniforms["u_pg_amp"] == (gf.AMP_MAX,) * 3


@pytest.mark.parametrize("h", [540, 1080, 2160])
def test_plan_is_in_px1080(h):
    """Raio e amplitude iguais em qualquer resolução (sem a compensação da prévia reduzida do grão de sempre)."""
    a, b = plan(vals(), h * 16 // 9, h).uniforms, plan(vals()).uniforms
    assert a["u_pg_r"] == b["u_pg_r"] and a["u_pg_amp"] == b["u_pg_amp"]
    assert a["u_pg_k"] == pytest.approx(1080 / h, rel=1e-7)


def test_net_grain_keeps_a_minimum_size_in_output_pixels():
    p = plan(vals(), 960, 540, net_grain=1.0).uniforms
    assert p["u_pg_r"] == pytest.approx(gf.R_K * look.NET_GRAIN_MIN_PX * 2.0)
    assert p["u_pg_chroma"] == pytest.approx(vals()["grao_cor"] * look.NET_GRAIN_CHROMA)


def test_uniforms_exist_in_the_program():
    """Todo uniform do plano físico existe no BASE ou no FINAL_PG, com o tipo certo."""
    import re
    declared = {}
    for src in (shaders.BASE, shaders.EXTRACT, shaders.BLUR, gf.FINAL_PG):
        declared.update({n: t for t, n in re.findall(r"uniform\s+(\w+)\s+(u_\w+)\s*;", src)})
    sizes = {"int": 1, "float": 1, "vec2": 2, "vec3": 3, "vec4": 4, "mat3": 9}
    for k, val in plan(vals(lab_processo="tech3", grao_respiracao=0.5)).uniforms.items():
        assert k in declared, k
        n = len(val) if isinstance(val, tuple) else 1
        assert n == sizes[declared[k]], k
        if declared[k] == "int":
            assert all(isinstance(x, int) for x in (val if isinstance(val, tuple) else (val,))), k
    assert "physGrain" not in shaders.FINAL and "physGrain" not in shaders.BAKE  # o FINAL e o BAKE de sempre


# ------------------------------------------------------------------ estatística exata e calibração
def _tool():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "tools" / "ajustar_grao.py"
    spec = importlib.util.spec_from_file_location("ajustar_grao", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_constants_are_the_calibration_of_the_tool():
    c = _tool().constants()
    assert c["KAPPA"] == gf.KAPPA and c["REF_DENSITY"] == gf.REF_DENSITY and c["R_K"] == gf.R_K
    assert c["NEG_SIGMA_D"] == grao.NEG_SIGMA_D
    assert gf.KAPPA[2] > gf.KAPPA[1] > gf.KAPPA[0]


def test_pixel_variance_peaks_in_the_middle():
    """Variância da cobertura vista pelo spot: zero sem grãos e cobrindo tudo, máxima perto de u = 1/2."""
    ds = np.linspace(0.0, 3.0, 121)
    var = np.array([gf.pixel_stats(d)[1] for d in ds])
    u = 1.0 - 10.0 ** -ds
    assert var[0] == 0.0 and var[-1] < 0.01 * var.max()
    assert 0.35 < u[int(np.argmax(var))] < 0.65
    # num ponto (sem o spot) a variância é exatamente u(1 − u), a de um sorteio coberto/descoberto; o spot a reduz
    np.testing.assert_allclose([gf.covariance(0.0, d) for d in ds], u * (1.0 - u), rtol=1e-12, atol=1e-15)
    assert (var[1:] < u[1:] * (1.0 - u[1:])).all()


# ------------------------------------------------------------------ referência em numpy × GPU
def reference_coverage(density: float, r: float = 12.0, size: int = 1200, seed: int = 1) -> np.ndarray:
    """O modelo booleano "de verdade": centros de Poisson num plano (sem células), discos desenhados numa grade fina
    (r pixels), e a cobertura vista pelo spot (os mesmos pontos, arredondados à grade)."""
    rng = np.random.default_rng(seed)
    pad = int(math.ceil(r * gf.REACH)) + 2
    n = size + 2 * pad
    lam = density * math.log(10.0) / (math.pi * r * r)
    cov = np.zeros((n, n), dtype=bool)
    k = int(math.ceil(r))
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    for cx, cy in rng.uniform(0, n, size=(rng.poisson(lam * n * n), 2)):
        ix, iy = int(cx), int(cy)
        disc = (xx + ix + 0.5 - cx) ** 2 + (yy + iy + 0.5 - cy) ** 2 < r * r
        x0, y0 = ix - k, iy - k
        sx0, sy0 = max(0, -x0), max(0, -y0)
        sx1, sy1 = min(2 * k + 1, n - x0), min(2 * k + 1, n - y0)
        if sx1 > sx0 and sy1 > sy0:
            cov[y0 + sy0:y0 + sy1, x0 + sx0:x0 + sx1] |= disc[sy0:sy1, sx0:sx1]
    acc = np.zeros((size, size))
    for ox, oy in np.rint(gf.offsets() * r).astype(int):
        acc += cov[pad + oy:pad + oy + size, pad + ox:pad + ox + size]
    return acc / gf.N_SAMPLES


COVERAGE_TEST = """
uniform vec3 u_D;
void main() {
    vec2 p = gl_FragCoord.xy * u_pg_k;
    f_out = vec4(physCoverage(u_D, p, uint(u_pg_seed)), 1.0);
}
"""


def gpu_coverage(engine, densities, r=6.0, size=768, seed=11, chroma=1.0) -> np.ndarray:
    """A cobertura da aproximação da GPU (`grao_fisico.GLSL`) numa imagem lisa: (size, size, 3), uma densidade por
    canal; r em pixels."""
    ctx = engine.ctx
    prog = ctx.program(vertex_shader=shaders.VERT, fragment_shader=shaders.COMMON + gf.GLSL + COVERAGE_TEST)
    vao = ctx.vertex_array(prog, [(engine.vbo, "2f", "in_pos")])
    tex = ctx.texture((size, size), 4, dtype="f4")
    fbo = ctx.framebuffer([tex])
    try:
        for k, val in (("u_D", tuple(float(d) for d in densities)), ("u_pg_k", 1.0), ("u_pg_r", float(r)),
                       ("u_pg_chroma", float(chroma)), ("u_pg_seed", int(seed))):
            prog[k].value = val
        fbo.use()
        vao.render(moderngl.TRIANGLE_STRIP)
        data = fbo.read(components=3, dtype="f4")
    finally:
        fbo.release()
        tex.release()
        vao.release()
        prog.release()
    return np.frombuffer(data, np.float32).reshape(size, size, 3).astype(np.float64)


def skew(x) -> float:
    x = np.asarray(x, dtype=np.float64).ravel()
    s = x.std()
    return float(((x - x.mean()) ** 3).mean() / s ** 3) if s > 0 else 0.0


def corr_length(img: np.ndarray, r: float) -> float:
    """Distância (em raios) em que a autocorrelação ao longo de x cai a 1/2."""
    x = img - img.mean()
    v = (x * x).mean()
    lags = np.arange(0, int(4 * r) + 1)
    c = np.array([(x[:, :x.shape[1] - L] * x[:, L:]).mean() / v for L in lags])
    i = int(np.argmax(c < 0.5))
    return float((lags[i - 1] + (c[i - 1] - 0.5) / (c[i - 1] - c[i])) / r)


DENSITIES = (0.05, 0.3, 1.0, 2.0)


@pytest.fixture(scope="module")
def gpu_stats(gl_engine):
    out = {}
    for d in DENSITIES:
        img = np.concatenate([gpu_coverage(gl_engine, (d, d, d), seed=s)[..., c] for s in (3, 4, 5, 6) for c in range(3)])
        out[d] = img
    return out


@pytest.fixture(scope="module")
def ref_stats():
    return {d: np.concatenate([reference_coverage(d, seed=s) for s in (1, 2, 3)]) for d in DENSITIES}


@pytest.mark.gpu
@pytest.mark.parametrize("d", DENSITIES)
def test_gpu_mean_coverage_is_the_coverage_law(gpu_stats, ref_stats, d):
    u = 1.0 - 10.0 ** -d
    assert gpu_stats[d].mean() == pytest.approx(u, abs=0.006)
    assert ref_stats[d].mean() == pytest.approx(u, abs=0.012)


@pytest.mark.gpu
@pytest.mark.parametrize("d", DENSITIES)
def test_gpu_variance_matches_the_exact_model_and_the_reference(gpu_stats, ref_stats, d):
    _u, var = gf.pixel_stats(d)
    assert gpu_stats[d].var() == pytest.approx(var, rel=0.08)   # 12 imagens: erro do sorteio de ~3% em D = 2
    assert ref_stats[d].var() == pytest.approx(var, rel=0.15)   # 3 imagens, spot arredondado à grade (+4%)


@pytest.mark.gpu
def test_gpu_variance_peaks_in_the_middle(gpu_stats):
    var = {d: gpu_stats[d].var() for d in DENSITIES}
    assert var[0.3] > var[0.05] and var[0.3] > var[2.0]


@pytest.mark.gpu
def test_skew_changes_sign(gpu_stats, ref_stats):
    """Grãos isolados na camada fina (assimetria > 0), buracos isolados na densa (< 0)."""
    for stats in (gpu_stats, ref_stats):
        assert skew(stats[0.05]) > 1.0
        assert skew(stats[2.0]) < -1.0
    for d in DENSITIES:
        assert np.sign(skew(gpu_stats[d])) == np.sign(skew(ref_stats[d]))


@pytest.mark.gpu
@pytest.mark.parametrize("d", (0.3, 1.0))
def test_correlation_length_is_the_radius(gl_engine, ref_stats, d):
    g = corr_length(gpu_coverage(gl_engine, (d, d, d), r=6.0)[..., 1], 6.0)
    ref = corr_length(ref_stats[d], 12.0)
    assert g == pytest.approx(ref, rel=0.08)
    assert 0.4 < g < 2.0


@pytest.mark.gpu
def test_layers_share_the_grain_with_less_color(gl_engine):
    """"Grão colorido" = fração dos centros própria de cada camada: 0 = as três camadas com os mesmos grãos."""
    mono = gpu_coverage(gl_engine, (1.0, 1.0, 1.0), chroma=0.0)
    assert np.array_equal(mono[..., 0], mono[..., 1]) and np.array_equal(mono[..., 1], mono[..., 2])
    color = gpu_coverage(gl_engine, (1.0, 1.0, 1.0), chroma=1.0)
    assert abs(np.corrcoef(color[..., 0].ravel(), color[..., 1].ravel())[0, 1]) < 0.03
    # aninhado: mais densidade = os mesmos grãos e mais alguns (com os centros comuns)
    nested = gpu_coverage(gl_engine, (0.4, 0.8, 1.6), chroma=0.0)
    assert (nested[..., 1] >= nested[..., 0]).all() and (nested[..., 2] >= nested[..., 1]).all()


# ------------------------------------------------------------------ no look
@pytest.mark.gpu
def test_aperture_sigma_d_is_the_datasheet(gl_engine):
    """No cinza médio, o sigma D de cada camada numa abertura de 48 µm (35 mm, ISO 250) é o do datasheet: a média
    da transmitância de `physGrain` numa abertura circular, no próprio shader do look."""
    h = 1440
    w = h
    k = 1080.0 / h
    ctx = gl_engine.ctx
    src = shaders.COMMON + gf.GLSL + """
uniform vec3 u_D;
void main() {
    f_out = vec4(physGrain(u_D, gl_FragCoord.xy * u_pg_k, uint(u_pg_seed)), 1.0);
}
"""
    prog = ctx.program(vertex_shader=shaders.VERT, fragment_shader=src)
    vao = ctx.vertex_array(prog, [(gl_engine.vbo, "2f", "in_pos")])
    tex = ctx.texture((w, h), 4, dtype="f4")
    fbo = ctx.framebuffer([tex])
    v = vals(bitola="35mm")
    U = plan(v).uniforms
    for name in ("u_pg_r", "u_pg_amp", "u_pg_chroma", "u_pg_seed"):
        prog[name].value = U[name]
    prog["u_pg_k"].value = k
    prog["u_D"].value = gf.REF_DENSITY
    fbo.use()
    vao.render(moderngl.TRIANGLE_STRIP)
    dd = np.frombuffer(fbo.read(components=3, dtype="f4"), np.float32).reshape(h, w, 3).astype(np.float64)
    fbo.release(), tex.release(), vao.release(), prog.release()
    assert U["u_pg_r"] == pytest.approx(gf.R_K * 0.8)
    # a abertura de 48 µm em pixels desta imagem; média da transmitância relativa por FFT
    diam = 0.048 * 1920 / 24.9 / k
    yy, xx = np.mgrid[0:h, 0:w]
    ker = (np.hypot(np.minimum(xx, w - xx), np.minimum(yy, h - yy)) < diam / 2).astype(np.float64)
    ker /= ker.sum()
    sig = []
    for c in range(3):
        t = 10.0 ** -dd[..., c]  # T'/T
        avg = np.real(np.fft.ifft2(np.fft.fft2(t) * np.fft.fft2(ker)))
        sig.append(np.std(-np.log10(avg)))
    np.testing.assert_allclose(sig, grao.NEG_SIGMA_D, rtol=0.08)
    assert sig[2] > sig[1] > sig[0]


def steps_image(w=1600, h=360, stops=(-6, -4, -2, 0, 2, 4)):
    img = np.zeros((h, w, 3))
    bw = w // len(stops)
    for i, st in enumerate(stops):
        img[:, i * bw:(i + 1) * bw] = 0.18 * 2.0 ** st
    return code16(img), bw


def band_stats(out, bw, n):
    return [(out[40:-40, i * bw + 20:(i + 1) * bw - 20].mean(axis=(0, 1)),
             out[40:-40, i * bw + 20:(i + 1) * bw - 20].std(axis=(0, 1))) for i in range(n)]


@pytest.mark.gpu
def test_the_print_curve_shapes_the_physical_grain(gl_engine):
    """Como na M3: a cópia esconde o grão nos pretos e nas altas luzes estouradas e o mostra nos tons médios; o
    azul tem mais grão; o brilho médio quase não muda (a média da transmitância é a mesma)."""
    stops = (-6, -4, -2, 0, 2, 4)
    img, bw = steps_image(stops=stops)
    clean = band_stats(render(gl_engine, img, vals(grao_on=False), 7), bw, len(stops))
    st = band_stats(render(gl_engine, img, vals(), 7), bw, len(stops))
    sd = np.array([s for _m, s in st])
    mid = stops.index(0)
    assert sd[mid].min() > 2 * sd[stops.index(4)].max()
    assert sd[mid].min() > 2 * sd[stops.index(-6)].max()
    r, g, b = sd[mid]
    assert b > g > r
    for (m0, _s0), (m1, _s1) in zip(clean, st):
        np.testing.assert_allclose(m1, m0, atol=4e-3)


@pytest.mark.gpu
def test_physical_grain_never_reaches_the_exported_lut(gl_engine):
    for v in (vals(lab_grao=False), vals(lab_grao=False, lab_copia="nenhuma"),
              vals(lab_grao=False, lab_processo="tech3", bitola="super8")):
        a = gl_engine.bake_lut(v, 17)
        b = gl_engine.bake_lut(dict(v, lab_grao=True), 17)
        assert np.array_equal(a, b)


@pytest.mark.gpu
def test_deterministic_per_frame(gl_engine):
    img, _bw = steps_image(480, 120, stops=(0, 1))
    v = vals()
    a, b = render(gl_engine, img, v, 7), render(gl_engine, img, v, 7)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, render(gl_engine, img, v, 8))           # muda a cada quadro
    still = dict(v, grao_animado=False)
    assert np.array_equal(render(gl_engine, img, still, 7), render(gl_engine, img, still, 8))
    # o quadro anterior não deixa nada no programa: ruído → físico → ruído
    noise = dict(v, lab_grao_modelo="ruido")
    n1 = render(gl_engine, img, noise, 7)
    render(gl_engine, img, v, 7)
    assert np.array_equal(n1, render(gl_engine, img, noise, 7))


@pytest.mark.gpu
def test_preview_equals_export(gl_engine, make_info):
    """A receita da prévia ("Salvar quadro") e a da exportação dão o mesmo quadro (16 bits, bit a bit)."""
    from pelicula import export, frame as framemod
    img, _bw = steps_image(320, 180, stops=(0, -1))
    v = vals()
    info = make_info(width=320, height=180)
    preview = framemod.Recipe.for_source(v, 24.0, 16, legal=True)
    exp = export.frame_pipeline(info, v, export.ExportSettings(codec="ffv1", container="mkv", pix="yuv444p16le"),
                                depth=16)
    a = preview.render(gl_engine, img, 3)
    b = exp.render(gl_engine, img, 3)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, framemod.Recipe.for_source(dict(v, lab_grao_modelo="ruido"), 24.0, 16,
                                                            legal=True).render(gl_engine, img, 3))


@pytest.mark.gpu
def test_statistics_do_not_depend_on_resolution(gl_engine):
    """A mesma estatística do grão (por pixel e na cópia) a 1080 e a 2160 linhas."""
    stats = []
    for h in (1080, 2160):
        img = code16(np.full((h // 2, h, 3), 0.18))
        out = render(gl_engine, img, vals(), 5)
        stats.append((out.mean(axis=(0, 1)), out.std(axis=(0, 1))))
    np.testing.assert_allclose(stats[0][0], stats[1][0], atol=1e-3)
    np.testing.assert_allclose(stats[0][1], stats[1][1], rtol=0.05)
