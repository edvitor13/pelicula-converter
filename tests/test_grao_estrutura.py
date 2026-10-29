"""Estrutura pela densidade (M1 da 1.6, fase 3; `pelicula/grao_estrutura.py`, ARQUITETURA §30.8).

- o padrão (0%) não muda nada: nenhum uniform novo no plano e o FINAL de sempre (a referência da BASE fica em
  `tests/test_grao.py`);
- as constantes são as de `tools/ajustar_grao.py` (tabelas do datasheet H-1-5207 e as camadas do modelo booleano);
- a calibração por camada contra os pontos lidos do datasheet;
- a referência em numpy (`grao_estrutura.channel`) contra o GLSL (`gsChannel`, bit a bit a menos do float32) e a
  estatística dela (variância por densidade, sinal da assimetria);
- no look: força, assimetria e comprimento de correlação de cada camada medidos na GPU, os pesos por tom por cima,
  o brilho médio igual, o grão no negativo, LUT igual, determinismo, prévia = exportação, independência da resolução.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import moderngl
import numpy as np
import pytest

from pelicula import grao, grao_estrutura as gs, look, params, shaders

ROOT = Path(__file__).resolve().parents[1]


def vals(**kw) -> dict:
    v = params.defaults()
    v.update(bitola="nenhuma", bitola_vinheta=0.0, grao_on=True)
    v.update(kw)
    return params.sanitize(v)


def plan(v, w=640, h=360, frame=0, **kw):
    return look.build_plan(v, w, h, frame, 24.0, None, dither=False, **kw)


def code16(lin) -> np.ndarray:
    lin = np.asarray(lin, dtype=np.float64)
    c = np.where(lin < 0.018, 4.5 * lin, 1.099 * np.power(np.maximum(lin, 1e-9), 0.45) - 0.099)
    return np.rint(np.clip(c, 0, 1) * 65535).astype(np.uint16)


def render(engine, img, v, frame=0, depth=16):
    h, w = img.shape[:2]
    engine.set_input(img)
    out = engine.render(plan(v, w, h, frame), depth)
    return out.astype(np.float64) / (255.0 if depth == 8 else 65535.0)


def skew(x) -> float:
    x = np.asarray(x, dtype=np.float64).ravel()
    s = x.std()
    return float(((x - x.mean()) ** 3).mean() / s ** 3)


def _tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ajustar_grao", ROOT / "tools" / "ajustar_grao.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ padrão e plano
def test_defaults_are_neutral_and_the_plan_has_nothing_new():
    d = params.defaults()
    assert d["grao_estrutura"] == 0.0 and d["grao_aglomeracao"] == 0.0
    assert params.PARAMS["grao_aglomeracao"].advanced and not params.PARAMS["grao_estrutura"].advanced
    for v in (vals(), vals(lab_on=True, lab_grao=True), vals(grao_aglomeracao=1.0)):
        assert not any(k.startswith("u_gs_") for k in plan(v).uniforms)


def test_plan_values_and_where_the_structure_applies():
    u = plan(vals(grao_estrutura=0.6, grao_aglomeracao=0.3)).uniforms
    assert u["u_grain_on"] == 1 and u["u_gs_amt"] == 0.6 and u["u_gs_clump"] == 0.3
    u = plan(vals(grao_estrutura=0.6, lab_on=True, lab_grao=True)).uniforms
    assert u["u_grain_on"] == 2 and u["u_gs_amt"] == 0.6
    # o modelo físico é a própria estrutura; sem grão, nada
    assert "u_gs_amt" not in plan(vals(grao_estrutura=1.0, lab_on=True, lab_grao=True,
                                       lab_grao_modelo="fisico")).uniforms
    assert "u_gs_amt" not in plan(vals(grao_estrutura=1.0, grao_on=False)).uniforms
    assert "u_gs_amt" not in plan(vals(grao_estrutura=1.0, grao_forca=0.0)).uniforms


def test_uniforms_exist_in_the_program():
    src = gs.program("final_gs")
    for name in plan(vals(grao_estrutura=1.0)).uniforms:
        if name.startswith("u_gs_"):
            assert f"uniform float {name};" in src
    assert shaders.FINAL.count("applyGrainS") == 0 and shaders.BAKE.count("gsNeg") == 0
    lx = gs.program("final_gs_lx")
    assert "labPathX" in lx and lx.count("dn += gsNeg(dn, nmid);") == 2  # labPath e a cópia com o laboratório


# ------------------------------------------------------------------ constantes e datasheet
def test_constants_are_the_calibration_of_the_tool():
    c = _tool().structure_constants()
    for k, v in c.items():
        assert getattr(gs, k) == v, k
    assert gs.STRUCT_SKEW[0] > 1.0 and abs(gs.STRUCT_SKEW[1]) < 0.3 and gs.STRUCT_SKEW[2] < -1.0
    assert gs.STRUCT_SIZE[0] > gs.STRUCT_SIZE[2] == 1.0 and gs.STRUCT_COARSE[2] == 0.0
    r, g, b = gs.STRUCT_RATIO
    assert b > 1.8 * g and r == pytest.approx(g)
    assert 0.2126 * r + 0.7152 * g + 0.0722 * b == pytest.approx(1.0, abs=1e-4)


def test_lognormal_transform_matches_the_skew():
    for target in (gs.STRUCT_SKEW[0], gs.STRUCT_SKEW[2]):
        s = _tool().lognormal_for_skew(target)
        assert _tool().lognormal_skew(s) == pytest.approx(target, abs=1e-6)


def _datasheet_points():
    tool = _tool()
    neg = tool.load("H-1-5207")
    return tool.structure_sigma_d_points(neg, tool.structure_grey_log_e(neg))


def test_sigma_d_per_density_is_the_datasheet_per_layer():
    """A força por densidade é o sigma D lido do H-1-5207 em cada camada (a tabela em √ρ passa pelos pontos)."""
    pts = _datasheet_points()
    for ch, c in enumerate("RGB"):
        rho, sd = pts[c]
        got = gs.sigma_d(rho, ch)
        np.testing.assert_allclose(got, sd, rtol=0.12)
        # no grão no negativo, a força em 100% é o sigma D absoluto do datasheet
        np.testing.assert_allclose(gs.envelope(rho, ch, True) * grao.NEG_SIGMA_D[ch], got, rtol=1e-12)
    # pico suave nas exposições baixas e médias, queda nas altas; azul > verde ≈ vermelho
    for ch in range(3):
        q = np.asarray(gs.STRUCT_SIGMA_D_Q[ch])
        assert q[:10].max() > q[10] > q[-1]
        assert 0.1 ** 2 < (np.argmax(q) * gs.Q_STEP) ** 2 < 0.5
    q = np.asarray(gs.STRUCT_SIGMA_D_Q)
    assert (q[2] > q[1]).all() and (q[2] > q[0]).all()
    assert gs.sigma_d(1.0, 1) == pytest.approx(gs.STRUCT_SIGMA_D_GREY[1])


def test_grey_on_the_granularity_figure():
    """O cinza fica onde as curvas de densidade da figura chegam à densidade do cinza das curvas sensitométricas: as
    três camadas concordam a menos de 0,06 log E (dois stops = 0,6)."""
    tool = _tool()
    neg = tool.load("H-1-5207")
    assert tool.structure_grey_log_e(neg) == pytest.approx(gs.STRUCT_LOG_E_GREY, abs=1e-3)
    rho = np.asarray(gs.STRUCT_RHO_X)
    assert (np.diff(rho, axis=1) >= 0).all() and np.allclose(rho[:, 8], 1.0)


def test_datasheet_source_is_recorded():
    data = json.loads((ROOT / "pelicula" / "data" / "datasheets" / "H-1-5207.json").read_text(encoding="utf-8"))
    gran = data["granularidade"]
    assert {"leitura_estrutura", "densidade", "pontos_extras"} <= set(gran)
    assert len(data["sha256"]) == 64 and gran["leitura_estrutura"]["metodo"]
    # os pontos de antes não mudaram: NEG_SIGMA_D (o grão no negativo de sempre) continua a média deles
    assert _tool().constants()["NEG_SIGMA_D"] == grao.NEG_SIGMA_D


# ------------------------------------------------------------------ referência em numpy
def test_reference_statistics_per_layer():
    """Campo gaussiano → T_s: média 0, variância = envelope² e a assimetria do modelo booleano em cada camada."""
    rng = np.random.default_rng(5)
    n = 400_000
    nf = rng.standard_normal((n, 4))
    nc = rng.standard_normal((n, 4))
    for layer, d in enumerate(gs.STRUCT_LAYER_D):
        rho = d / gs.dref()[1] * (0.6 if layer == 0 else 1.0 if layer == 1 else 1.5)  # dentro da camada
        g = gs.channel(nf, nc, 1, np.full(n, rho), 0.22, 0.3, 1.0, 0.0, True)
        env = gs.envelope(rho, 1, True)
        assert abs(g.mean()) < 0.01 * env
        assert g.std() == pytest.approx(env, rel=0.01)
        assert skew(g) == pytest.approx(gs.STRUCT_SKEW[layer], abs=0.12)
    # Estrutura em 0: exatamente o grão de sempre (a mistura de aspereza e cor de applyGrain)
    g0 = gs.channel(nf, nc, 0, np.full(n, 1.3), 0.22, 0.3, 0.0, 0.7, False)
    r, c = 0.22, 0.3
    m = (nf * (1 - r) + nc * r) / math.sqrt((1 - r) ** 2 + r * r)
    want = (m[:, 3] * (1 - c) + m[:, 0] * c) / math.sqrt((1 - c) ** 2 + c * c)
    np.testing.assert_allclose(g0, want, rtol=1e-12, atol=1e-12)


def test_layer_weights_are_a_smooth_partition():
    rho = np.geomspace(1e-3, 3.0, 400)
    s01, s12 = gs.layer_weights(rho, 1)
    w = np.stack([1 - s01, s01 - s12, s12])
    assert (w >= -1e-12).all() and np.allclose(w.sum(axis=0), 1.0)
    assert (np.diff(s01) >= 0).all() and (np.diff(s12) >= 0).all()
    sig, delta = gs.layer_params(rho, 1, 1.0, 0.0)
    assert sig[0] == pytest.approx(gs.STRUCT_SIGMA[0]) and sig[-1] == pytest.approx(gs.STRUCT_SIGMA[2])
    _s, d1 = gs.layer_params(rho, 1, 1.0, 1.0)
    assert d1[-1] == 1.0 and delta[-1] == 0.0 and np.allclose(d1[:100], delta[:100])


# ------------------------------------------------------------------ GLSL = referência
CHANNEL_TEST = """
uniform sampler2D t_nf;
uniform sampler2D t_nc;
uniform sampler2D t_rho;
uniform float u_rough;
uniform float u_chroma;
uniform int u_neg;
uniform int u_stops;
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 nf = texelFetch(t_nf, p, 0);
    vec4 nc = texelFetch(t_nc, p, 0);
    vec3 r = texelFetch(t_rho, p, 0).rgb;
    if (u_stops == 1) r = vec3(gsRhoX(0, r.r), gsRhoX(1, r.g), gsRhoX(2, r.b));
    f_out = vec4(gsChannel(nf, nc, 0, r.r, u_rough, u_chroma, u_neg), gsChannel(nf, nc, 1, r.g, u_rough, u_chroma, u_neg),
                 gsChannel(nf, nc, 2, r.b, u_rough, u_chroma, u_neg), 1.0);
}
"""


@pytest.mark.gpu
@pytest.mark.parametrize("neg,stops,amount,clump", [(1, 0, 1.0, 0.0), (0, 1, 0.7, 0.5), (1, 0, 0.35, 1.0)])
def test_glsl_is_the_numpy_reference(gl_engine, neg, stops, amount, clump):
    ctx = gl_engine.ctx
    w, h = 256, 64
    rng = np.random.default_rng(9)
    nf = rng.standard_normal((h, w, 4)).astype(np.float32)
    nc = rng.standard_normal((h, w, 4)).astype(np.float32)
    if stops:
        r = rng.uniform(-10, 10, (h, w, 4)).astype(np.float32)
    else:
        r = (rng.uniform(0, 1.8, (h, w, 4)) ** 2).astype(np.float32)
    prog = ctx.program(vertex_shader=shaders.VERT, fragment_shader=shaders.COMMON + gs._glsl_common() + CHANNEL_TEST)
    vao = ctx.vertex_array(prog, [(gl_engine.vbo, "2f", "in_pos")])
    texs = [ctx.texture((w, h), 4, data=a.tobytes(), dtype="f4") for a in (nf, nc, r)]
    out = ctx.texture((w, h), 4, dtype="f4")
    fbo = ctx.framebuffer([out])
    try:
        for i, (name, t) in enumerate(zip(("t_nf", "t_nc", "t_rho"), texs)):
            t.use(i)
            prog[name].value = i
        for k, val in (("u_rough", 0.22), ("u_chroma", 0.3), ("u_neg", neg), ("u_stops", stops),
                       ("u_gs_amt", amount), ("u_gs_clump", clump)):
            prog[k].value = val
        fbo.use()
        vao.render(moderngl.TRIANGLE_STRIP)
        got = np.frombuffer(fbo.read(components=3, dtype="f4"), np.float32).reshape(h, w, 3).astype(np.float64)
    finally:
        for o in (fbo, out, *texs, vao, prog):
            o.release()
    for ch in range(3):
        rho = gs.rho_of_stops(r[..., ch], ch) if stops else r[..., ch]
        want = gs.channel(nf, nc, ch, rho, 0.22, 0.3, amount, clump, bool(neg))
        np.testing.assert_allclose(got[..., ch], want, rtol=2e-4, atol=2e-4)


# ------------------------------------------------------------------ no look (GPU)
BIG = dict(bitola="8mm", bitola_desfoque_on=False, bitola_vinheta=0.0, grao_tamanho=4.0, grao_cor=0.0)


def scene_code16(stops: float) -> int:
    """O código de 16 bits que a entrada padrão (a curva de exibição do app, `toLinear` id 0) lê como `stops` da
    cena: é o x que a estrutura vê (`linToStops`)."""
    y = np.linspace(0.0, 1.0, 65536)
    x = look._disp_to_stops(y)
    return int(np.rint(np.interp(stops, x, y) * 65535))


def flat(stops: float, w=1920, h=1080) -> np.ndarray:
    return np.full((h, w, 3), scene_code16(stops), dtype=np.uint16)


def resp_w(L: float, v: dict) -> float:
    return (v["grao_sombras"] * math.exp(-((L - 0.10) / 0.16) ** 2) + v["grao_meios"] * math.exp(-((L - 0.45) / 0.22) ** 2)
            + v["grao_luzes"] * math.exp(-((L - 0.88) / 0.16) ** 2))


def _corr_half(x: np.ndarray, maxlag: int) -> float:
    x = x - x.mean()
    v = (x * x).mean()
    c = np.array([(x[:, :x.shape[1] - L] * x[:, L:]).mean() / v for L in range(maxlag)])
    i = int(np.argmax(c < 0.5))
    return float(i - 1 + (c[i - 1] - 0.5) / (c[i - 1] - c[i]))


def _expected_half(c_frac: float, sig: float, cell: float) -> float:
    """Meia-correlação (px) de T_s do campo misturado: corr = (e^(s²·C) − 1) / (e^(s²) − 1)."""
    tool = _tool()
    r, b = tool._noise_corr()
    hh = np.linspace(0.0, 8.0, 8001)
    C = ((1 - c_frac) ** 2 * np.interp(hh, r, b, right=0.0)
         + c_frac ** 2 * np.interp(hh * tool.COARSE_SCALE, r, b, right=0.0)) / ((1 - c_frac) ** 2 + c_frac ** 2)
    if abs(sig) > 1e-4:
        C = np.expm1(sig * sig * C) / np.expm1(sig * sig)
    return float(np.interp(0.5, C[::-1], hh[::-1])) * cell


@pytest.fixture(scope="module")
def layer_frames(gl_engine):
    """Imagens lisas na exposição de cada camada (fina, média, densa) com grão grande e monocromático, 4 quadros."""
    out = {}
    # força baixa: o grão não chega a ser cortado no preto da saída (a estatística é a do campo)
    for name, st, clump in (("fina", -4.6, 0.0), ("media", -2.87, 0.0), ("densa", 1.0, 0.0), ("aglomerada", 1.0, 1.0)):
        v = vals(**BIG, grao_estrutura=1.0, grao_aglomeracao=clump, grao_forca=0.3)
        clean = render(gl_engine, flat(st), vals(**BIG, grao_on=False))
        frames = [render(gl_engine, flat(st), v, f) for f in (1, 2, 3, 4)]
        out[name] = (v, st, clean, frames)
    return out


@pytest.mark.gpu
@pytest.mark.parametrize("name,layer", [("fina", 0), ("media", 1), ("densa", 2)])
def test_each_layer_has_its_skew_and_strength(gl_engine, layer_frames, name, layer):
    v, st, clean, frames = layer_frames[name]
    U = plan(v, 1920, 1080).uniforms
    L = float(np.dot(clean.mean(axis=(0, 1)), (0.2126, 0.7152, 0.0722)))
    for ch in range(3):
        g = np.concatenate([(f - clean)[..., ch].ravel() for f in frames])
        rho = float(gs.rho_of_stops(st, ch))
        sig, _d = gs.layer_params(rho, ch, 1.0, 0.0)
        want_sd = U["u_grain_amt"] * resp_w(L, v) * float(gs.envelope(rho, ch, False))
        assert g.std() == pytest.approx(want_sd, rel=0.06), (name, ch)
        assert abs(g.mean()) < 0.03 * want_sd + 2e-6
        assert skew(g) == pytest.approx(_tool().lognormal_skew(float(sig)), abs=0.2), (name, ch)
    s1 = skew(np.concatenate([(f - clean)[..., 1].ravel() for f in frames]))
    assert np.sign(s1) == np.sign(gs.STRUCT_SKEW[layer]) or abs(gs.STRUCT_SKEW[layer]) < 0.3


@pytest.mark.gpu
@pytest.mark.parametrize("name", ["fina", "densa", "aglomerada"])
def test_each_layer_has_its_size(gl_engine, layer_frames, name):
    v, st, clean, frames = layer_frames[name]
    p = plan(v, 1920, 1080)
    cell = 1920 / max(2, math.ceil(1920 / p.grain_size))
    rho = float(gs.rho_of_stops(st, 1))
    sig, delta = gs.layer_params(rho, 1, 1.0, v["grao_aglomeracao"])
    c = v["grao_aspereza"] + (1 - v["grao_aspereza"]) * float(delta)
    want = _expected_half(c, float(sig), cell)
    got = np.mean([_corr_half((f - clean)[..., 1], int(4 * cell)) for f in frames])
    assert got == pytest.approx(want, rel=0.08), name


@pytest.mark.gpu
def test_clumping_grows_the_dense_grain(layer_frames):
    def half(name):
        _v, _st, clean, frames = layer_frames[name]
        return np.mean([_corr_half((f - clean)[..., 1], 60) for f in frames])
    assert half("aglomerada") > 1.6 * half("densa")


@pytest.mark.gpu
def test_tone_weights_still_apply_on_top(gl_engine):
    img = flat(0.0, 480, 270)
    clean = render(gl_engine, img, vals(**BIG, grao_on=False))
    full = render(gl_engine, img, vals(**BIG, grao_estrutura=1.0), 3)
    none = render(gl_engine, img, vals(**BIG, grao_estrutura=1.0, grao_meios=0.0, grao_sombras=0.0,
                                       grao_luzes=0.0), 3)
    assert np.array_equal(none, clean)
    half = render(gl_engine, img, vals(**BIG, grao_estrutura=1.0, grao_meios=0.5, grao_sombras=0.4,
                                       grao_luzes=0.225), 3)
    np.testing.assert_allclose((half - clean).std(), 0.5 * (full - clean).std(), rtol=0.02)


@pytest.mark.gpu
def test_mean_brightness_is_kept_and_zero_is_the_old_grain(gl_engine):
    stops = (-3, -1.5, 0, 1.5)  # longe do preto e do branco: lá a saída corta o grão (com ou sem a estrutura)
    img = np.concatenate([flat(s, 480, 270) for s in stops], axis=1)
    clean = render(gl_engine, img, vals(**BIG, grao_on=False))
    for amt in (0.5, 1.0):
        out = np.mean([render(gl_engine, img, vals(**BIG, grao_estrutura=amt, grao_aglomeracao=0.5,
                                           grao_forca=0.5), f)
                       for f in (1, 2, 3)], axis=0)
        for i in range(len(stops)):
            band = (slice(None), slice(i * 480, (i + 1) * 480))
            np.testing.assert_allclose(out[band].mean(axis=(0, 1)), clean[band].mean(axis=(0, 1)), atol=6e-4)
    # a variante com 0% não é usada: o grão de sempre, bit a bit
    a = render(gl_engine, img, vals(**BIG), 2)
    assert np.array_equal(a, render(gl_engine, img, vals(**BIG, grao_aglomeracao=0.8), 2))


@pytest.mark.gpu
def test_negative_grain_follows_the_density(gl_engine):
    """No grão no negativo, a estrutura usa a densidade de cada camada dentro do Laboratório: o brilho médio de
    cada faixa quase não muda, o grão continua moldado pela cópia, e a variante com véu/pré-exposição compila."""
    stops = (-6, -2, 0, 2, 4)
    img = np.concatenate([flat(s, 320, 240) for s in stops], axis=1)
    lab = dict(bitola="35mm", bitola_desfoque_on=False, bitola_vinheta=0.0, lab_on=True, lab_grao=True)
    clean = render(gl_engine, img, vals(**lab, grao_on=False))
    m3 = render(gl_engine, img, vals(**lab), 4)
    st = render(gl_engine, img, vals(**lab, grao_estrutura=1.0), 4)
    assert gl_engine.progs.get("final_gs") is not None
    for i in range(len(stops)):
        band = (slice(20, -20), slice(i * 320 + 20, (i + 1) * 320 - 20))
        np.testing.assert_allclose(st[band].mean(axis=(0, 1)), clean[band].mean(axis=(0, 1)), atol=3e-3)
    sd = [st[20:-20, i * 320 + 20:(i + 1) * 320 - 20].std(axis=(0, 1)) for i in range(len(stops))]
    assert sd[2].min() > 2 * sd[4].max() and sd[2].min() > 2 * sd[0].max()
    assert not np.array_equal(m3, st)
    lx = render(gl_engine, img, vals(**lab, grao_estrutura=1.0, lab_vencida=20), 4)
    assert gl_engine.progs.get("final_gs_lx") is not None and abs(lx.mean() - st.mean()) > 0.003


@pytest.mark.gpu
def test_structure_never_reaches_the_exported_lut(gl_engine):
    for v in (vals(), vals(lab_on=True, lab_grao=True), vals(lab_on=True, lab_copia="nenhuma")):
        a = gl_engine.bake_lut(v, 17)
        b = gl_engine.bake_lut(dict(v, grao_estrutura=1.0, grao_aglomeracao=1.0), 17)
        assert np.array_equal(a, b)


@pytest.mark.gpu
def test_deterministic_and_nothing_stale(gl_engine):
    img = np.concatenate([flat(s, 160, 90) for s in (-4, 0, 3)], axis=1)
    v = vals(grao_estrutura=1.0, bitola="16mm")
    a = render(gl_engine, img, v, 7)
    assert np.array_equal(a, render(gl_engine, img, v, 7))
    assert not np.array_equal(a, render(gl_engine, img, v, 8))
    plain = vals(bitola="16mm")
    p1 = render(gl_engine, img, plain, 7)
    render(gl_engine, img, v, 7)
    assert np.array_equal(p1, render(gl_engine, img, plain, 7))


@pytest.mark.gpu
def test_preview_equals_export(gl_engine, make_info):
    from pelicula import export, frame as framemod
    img = np.concatenate([flat(s, 160, 180) for s in (-3, 1)], axis=1)
    for v in (vals(grao_estrutura=0.8), vals(grao_estrutura=0.8, lab_on=True, lab_grao=True)):
        info = make_info(width=320, height=180)
        preview = framemod.Recipe.for_source(v, 24.0, 16, legal=True)
        exp = export.frame_pipeline(info, v, export.ExportSettings(codec="ffv1", container="mkv",
                                                                   pix="yuv444p16le"), depth=16)
        assert np.array_equal(preview.render(gl_engine, img, 3), exp.render(gl_engine, img, 3))


@pytest.mark.gpu
def test_statistics_do_not_depend_on_resolution(gl_engine):
    """A estrutura muda o grão de sempre do mesmo jeito a 1080 e a 2160 linhas (a razão para o grão de sempre: o
    desvio por pixel do grão de sempre muda quando a célula chega ao mínimo de 1 px, então o grão é grande)."""
    stats = []
    for h in (1080, 2160):
        img = np.concatenate([flat(s, h // 2, h // 2) for s in (-3.5, 1)], axis=1)
        q = h // 2
        sd = []
        for est in (0.0, 1.0):
            out = render(gl_engine, img, vals(**BIG, grao_estrutura=est, grao_forca=0.5), 5)
            sd.append(np.array([out[:, :q].std(axis=(0, 1)), out[:, q:].std(axis=(0, 1))]))
        stats.append(sd[1] / sd[0])
    np.testing.assert_allclose(stats[0], stats[1], rtol=0.04)
