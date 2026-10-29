"""Proteger cores saturadas (1.6, `proteger_cores`): compressão suave do gamut depois da matriz da câmera.

A referência é a "ACES Reference Gamut Compression" (Academy Software Foundation / AMPAS; especificação em
CC BY 4.0, docs.acescentral.com/rgc/specification). A fórmula abaixo é reescrita aqui em float64 a partir da
especificação, sem depender do GLSL: d = (A − c)/|A| com A = máx(r, g, b); abaixo do limiar t a distância não muda;
acima, d' = t + (d − t)/(1 + ((d − t)/s)^p)^(1/p), com s tal que o limite l vá para 1.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pelicula import look, params, presets, shaders

ACES_THR = (0.815, 0.803, 0.880)    # limiares (ciano, magenta, amarelo) da especificação
ACES_LIM = (1.147, 1.264, 1.312)    # limites da especificação
ACES_PWR = 1.2
CAMERA_GAMUTS = sorted(set(look.INPUT_GAMUT.values()))


# ------------------------------------------------------------------ referência (float64)
def ref_distance(d, lim, thr, p=ACES_PWR):
    d = np.asarray(d, dtype=np.float64)
    s = (lim - thr) / (((1.0 - thr) / (lim - thr)) ** (-p) - 1.0) ** (1.0 / p)
    x = np.maximum(d - thr, 0.0)
    return np.where(d < thr, d, thr + x / (1.0 + (x / s) ** p) ** (1.0 / p))


def ref_compress(rgb, lim, thr=ACES_THR):
    rgb = np.asarray(rgb, dtype=np.float64)
    a = rgb.max(axis=-1, keepdims=True)
    safe = np.where(a == 0.0, 1.0, np.abs(a))
    d = (a - rgb) / safe
    cd = np.stack([ref_distance(d[..., i], lim[i], thr[i]) for i in range(3)], -1)
    return np.where(a == 0.0, rgb, a - cd * safe)


def slog3_enc(x):  # Sony, "Technical Summary for S-Gamut3.Cine/S-Log3 and S-Gamut3/S-Log3": CV = código/1023
    x = np.asarray(x, dtype=np.float64)
    hi = (420.0 + np.log10((np.maximum(x, 0.01125) + 0.01) / (0.18 + 0.01)) * 261.5) / 1023.0
    lo = (x * (171.2102946929 - 95.0) / 0.01125000 + 95.0) / 1023.0
    return np.where(x >= 0.01125, hi, lo)


def boundary(n: int = 33) -> np.ndarray:
    """Cores da fronteira de um gamut: faces do cubo RGB com um canal em 0 (as mais saturadas que ele grava)."""
    t = np.linspace(0.0, 1.0, n)
    s, u = (a.ravel() for a in np.meshgrid(t, t))
    z = np.zeros_like(s)
    pts = np.concatenate([np.stack([z, s, u], 1), np.stack([s, z, u], 1), np.stack([s, u, z], 1)])
    return pts[pts.max(axis=1) > 0]


# ------------------------------------------------------------------ sem GPU
def test_constants_are_the_ones_of_the_aces_specification():
    assert look.GC_THRESHOLDS == ACES_THR and look.GC_LIMITS_ACES == ACES_LIM and look.GC_POWER == ACES_PWR
    src = shaders.COMMON
    assert "const vec3 GC_THR = vec3(0.815, 0.803, 0.880);" in src and "const float GC_PWR = 1.2;" in src


def test_reference_curve_keeps_the_inside_and_maps_the_limit_to_the_border():
    for lim, thr in zip(ACES_LIM, ACES_THR):
        d = np.linspace(0.0, thr, 50, endpoint=False)
        np.testing.assert_array_equal(ref_distance(d, lim, thr), d)          # dentro do limiar: nada muda
        assert float(ref_distance(lim, lim, thr)) == pytest.approx(1.0, abs=1e-12)  # o limite vai à borda
        x = np.linspace(0.0, 4.0, 4001)
        y = ref_distance(x, lim, thr)
        assert np.all(np.diff(y) > 0)                                         # monótona: a ordem das cores fica
        slope = np.diff(y) / np.diff(x)
        k = int(np.searchsorted(x, thr))
        assert slope[k] == pytest.approx(1.0, abs=2e-2)                       # sem quina no limiar
        s = (lim - thr) / (((1.0 - thr) / (lim - thr)) ** (-ACES_PWR) - 1.0) ** (1.0 / ACES_PWR)
        assert y.max() < thr + s                                              # assíntota: nada vai ao infinito


@pytest.mark.parametrize("gamut", CAMERA_GAMUTS)
def test_limits_cover_the_whole_camera_gamut(gamut):
    """Com 100%, a cor mais saturada que a câmera grava cai dentro do Rec.709 (nenhum canal negativo)."""
    lim = look.gamut_limits(gamut)
    assert all(a >= b for a, b in zip(lim, ACES_LIM))
    rgb = boundary() @ look.gamut_to_709(gamut).T
    out = ref_compress(rgb, lim)
    assert out.min() > -1e-9
    if gamut == "709":
        assert lim == ACES_LIM


def test_param_is_neutral_and_kept_by_presets():
    p = params.PARAMS["proteger_cores"]
    assert p.default == 0.0 and p.min == 0.0 and p.max == 1.0 and p.percent
    assert "proteger_cores" in presets.SOURCE_KEYS
    v = dict(params.defaults(), entrada="slog3")
    U = look.build_plan(v, 64, 36, 0, 24.0).uniforms
    assert "u_gc_amt" not in U and "u_gc_lim" not in U       # desligado: o plano de sempre
    assert look.SPARSE_UNIFORMS == {"u_gc_amt": 0.0}         # e o Engine manda o 0 antes dele
    U = look.build_plan(dict(v, proteger_cores=0.4), 64, 36, 0, 24.0).uniforms
    assert U["u_gc_amt"] == pytest.approx(0.4) and U["u_gc_lim"] == look.gamut_limits("sgamut3cine")
    # a 1.5 não conhece o ajuste: fora do padrão o projeto vai para o formato 4
    known = params.known_1_5()["look"]
    assert not params.beyond_1_5(params.FILM, known, v)
    assert params.beyond_1_5(params.FILM, known, dict(v, proteger_cores=0.4))


# ------------------------------------------------------------------ na GPU
PROBE = shaders.COMMON + """
uniform sampler2D t_x;
uniform vec3 u_lim;
uniform mat3 u_m;
uniform int u_mode;
void main() {
    vec3 x = texelFetch(t_x, ivec2(gl_FragCoord.xy), 0).rgb;
    f_out = vec4(u_mode == 0 ? gamutCompress(x, u_lim) : protectGamut(u_m * x), 1.0);
}
"""


class Probe:
    def __init__(self, eng):
        self.ctx = eng.ctx
        self.prog = self.ctx.program(vertex_shader=shaders.VERT, fragment_shader=PROBE)
        self.vao = self.ctx.vertex_array(self.prog, [(eng.vbo, "2f", "in_pos")])

    def run(self, rgb, lim, mode: int = 0, m=np.eye(3), amount: float = 1.0) -> np.ndarray:
        import moderngl
        a = np.ascontiguousarray(np.asarray(rgb, dtype=np.float32).reshape(-1, 3))
        n = a.shape[0]
        tex = self.ctx.texture((n, 1), 3, data=a.tobytes(), dtype="f4")
        out = self.ctx.texture((n, 1), 4, dtype="f4")
        fbo = self.ctx.framebuffer([out])
        try:
            tex.use(0)
            for k, v in (("t_x", 0), ("u_lim", tuple(lim)), ("u_mode", mode), ("u_m", look.mat3_uniform(m)),
                         ("u_gc_amt", amount), ("u_gc_lim", tuple(lim))):
                if k in self.prog:
                    self.prog[k].value = v
            fbo.use()
            self.vao.render(moderngl.TRIANGLE_STRIP)
            data = fbo.read(components=3, dtype="f4")
        finally:
            fbo.release()
            out.release()
            tex.release()
        return np.frombuffer(data, np.float32).reshape(n, 3).astype(np.float64)


@pytest.fixture(scope="module")
def probe(gl_engine):
    return Probe(gl_engine)


@pytest.mark.gpu
def test_shader_matches_the_reference(probe):
    g = np.linspace(-0.6, 1.6, 12)
    rgb = np.stack(np.meshgrid(g, g, g), -1).reshape(-1, 3)
    rgb = np.concatenate([rgb, [[0, 0, 0], [0.18, 0.18, 0.18], [-0.1, -0.2, -0.3], [4.0, -0.5, 0.2]]])
    for gamut in ("709", "sgamut3cine", "awg4", "rwg"):
        lim = look.gamut_limits(gamut)
        want = ref_compress(rgb, lim)
        got = probe.run(rgb, lim)
        np.testing.assert_allclose(got, want, rtol=2e-5, atol=2e-6, err_msg=gamut)


@pytest.mark.gpu
@pytest.mark.parametrize("gamut", ["sgamut3cine", "awg3", "dwg", "cinemagamut", "fgamutc"])
def test_full_protection_brings_the_camera_gamut_inside_709(probe, gamut):
    """protectGamut com 100% sobre a matriz da câmera: a fronteira do gamut sai sem canal negativo (o negativo do
    Laboratório deixa de ver um canal "sem exposição"); com 0, a cor é a de sempre, bit a bit."""
    m = look.gamut_to_709(gamut)
    lim = look.gamut_limits(gamut)
    cam = boundary() * 0.5
    plain = cam @ m.T
    assert plain.min() < -0.05                                    # sem proteção há canal negativo
    out = probe.run(cam, lim, mode=1, m=m, amount=1.0)
    assert out.min() > -1e-5
    off = probe.run(cam, lim, mode=1, m=m, amount=0.0)
    np.testing.assert_allclose(off, plain, rtol=1e-5, atol=1e-6)


def _sweep(gamut: str, n: int = 96) -> np.ndarray:
    """Manchas de saturação crescente (do cinza ao primário/secundário puro) no gamut da câmera, em luz linear."""
    hues = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 1, 1], [1, 0, 1], [1, 1, 0], [1, 0.25, 0], [0, 0.4, 1]],
                    dtype=np.float64)
    s = np.linspace(0.0, 1.0, n)[:, None, None]
    gray = np.full((1, 1, 3), 1.0 / 3.0)
    pure = (hues / hues.sum(axis=1, keepdims=True))[None]
    return (gray * (1.0 - s) + pure * s) * 0.18 * 3.0             # (n, matizes, 3): mesma soma de luz


def _render(eng, values, img16):
    h, w = img16.shape[:2]
    eng.set_input(img16)
    out = eng.render(look.build_plan(values, w, h, 0, 24.0, None, dither=False, legal=False), 16)
    return out.astype(np.float64) / 65535.0


@pytest.mark.gpu
@pytest.mark.parametrize("pid", ["original", "vision3_500t", "lab_v3_250d_2383"])
def test_saturated_sgamut3_sweep_is_continuous(gl_engine, pid):
    """Manchas sintéticas em S-Gamut3.Cine (S-Log3) varrendo a saturação: com 100% a saída é contínua, sem degraus
    (nenhum canal chega a zero no meio da varredura); as pouco saturadas não mudam; 0% é idêntico a não ter o
    ajuste. Abaixo de 100% as cores mais extremas ainda podem passar da borda do Rec.709 (é uma mistura)."""
    cam = _sweep("sgamut3cine")                                   # (n, matizes, 3)
    img = np.round(slog3_enc(cam) * 65535).astype(np.uint16).transpose(1, 0, 2).copy()  # uma linha por matiz
    base = dict(presets.builtin_values(pid), entrada="slog3")
    plain = _render(gl_engine, base, img)
    np.testing.assert_array_equal(_render(gl_engine, dict(base, proteger_cores=0.0), img), plain)
    out = _render(gl_engine, dict(base, proteger_cores=1.0), img)
    step = np.abs(np.diff(out, axis=1)).max(axis=2)               # (matizes, n − 1)
    for row, st in enumerate(step):
        assert st.max() <= 4.0 * float(np.median(st)) + 4e-3, f"{pid} matiz {row}: degrau {st.max():.4f}"
    # o maior salto fica menor que o de sem proteção (o canal que zerava no meio da varredura)
    assert step.max() <= np.abs(np.diff(plain, axis=1)).max() + 1e-4
    # o começo da varredura (perto do cinza) fica como estava; as mais saturadas mudam
    np.testing.assert_allclose(out[:, :20], plain[:, :20], atol=3.0 / 65535)
    assert np.abs(out - plain).max() > 0.01
    half = _render(gl_engine, dict(base, proteger_cores=0.5), img)
    assert np.abs(half - plain).max() > 0.005 and np.abs(half - out).max() > 0.005
    # desligar depois de ligar volta à cor de sempre (o programa não fica com o último valor)
    np.testing.assert_array_equal(_render(gl_engine, base, img), plain)


@pytest.mark.gpu
def test_exported_lut_follows_the_setting(gl_engine):
    v = dict(presets.builtin_values("vision3_500t"), entrada="slog3")
    lut0 = gl_engine.bake_lut(v, 9)
    np.testing.assert_array_equal(gl_engine.bake_lut(dict(v, proteger_cores=0.0), 9), lut0)
    assert np.abs(gl_engine.bake_lut(dict(v, proteger_cores=1.0), 9) - lut0).max() > 0.01
    # depois de um LUT com proteção, o de 0% volta a ser o de sempre (o programa guarda o último uniform)
    np.testing.assert_array_equal(gl_engine.bake_lut(v, 9), lut0)
    assert math.isfinite(float(lut0.sum()))
