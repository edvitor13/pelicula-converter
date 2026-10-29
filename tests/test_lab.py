"""Laboratório: modelo de densidade negativo → cópia, Technicolor, prata retida, luzes da copiadora e pele."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from pelicula import look, params, presets, shaders

NEGS = list(look.NEGATIVES)
PRINTS = list(look.LAB_PRINTS)
PROCS = list(look.LAB_PROCESSES)
W709 = np.array([0.2126, 0.7152, 0.0722])


def lab_values(**over) -> dict:
    v = params.defaults()
    v.update(lab_on=True, bitola="nenhuma", cor_on=False, copia="nenhuma")
    v.update(over)
    return params.sanitize(v)


def display_to_lin(code) -> np.ndarray:
    """Inversa da curva neutra em numpy (mesma conta de look.display_to_lin, vetorizada)."""
    y = np.asarray(code, dtype=np.float64)
    r = np.where(y >= look.D_MID, 1.0 - look.D_MID, look.D_MID)
    vv = np.minimum(np.abs((y - look.D_MID) / r), 0.99995)
    u = vv / (1 - vv ** look.D_P) ** (1 / look.D_P)
    t = np.sign(y - look.D_MID) * u * r / look.D_SLOPE
    return 0.18 * 2.0 ** np.clip(t, -12, 12)


def stops(n) -> np.ndarray:
    """Cinza a n stops do cinza médio, em luz linear (shape (..., 3))."""
    n = np.asarray(n, dtype=np.float64)
    return np.stack([0.18 * 2.0 ** n] * 3, axis=-1)


def sat(y: np.ndarray) -> np.ndarray:
    lum = y @ W709
    return np.abs(y - lum[..., None]).sum(-1) / lum


PATCHES = np.array([[0.4, 0.05, 0.05], [0.05, 0.3, 0.05], [0.05, 0.08, 0.4], [0.35, 0.2, 0.12],
                    [0.3, 0.3, 0.05], [0.1, 0.2, 0.3], [0.25, 0.15, 0.1]])


# ------------------------------------------------------------------ esquema e plano
def test_lab_is_off_and_neutral_by_default():
    d = params.defaults()
    assert d["lab_on"] is False
    U = look.build_plan(d, 640, 360, 0, 24.0).uniforms
    assert U["u_lab_on"] == 0
    assert not any(k.startswith(("u_la_", "u_lb_")) for k in U)
    assert U["u_skin"] == (0.0, 0.0)
    for k in ("pele_matiz", "pele_luz", "lab_luz_r", "lab_luz_g", "lab_luz_b", "lab_densidade", "lab_revelacao"):
        assert d[k] == 0.0
    assert d["lab_diafonia"] == 1.0


def test_every_choice_has_a_table():
    ch = {k: [c[0] for c in p.choices] for k, p in params.PARAMS.items() if p.kind == "choice"}
    assert set(ch["lab_negativo"]) == set(look.NEGATIVES)
    assert set(ch["lab_copia"]) == set(look.LAB_PRINTS)
    assert set(ch["lab_processo"]) == set(look.LAB_PROCESSES)


@pytest.mark.parametrize("neg", NEGS)
def test_sensitivity_rows_sum_to_one_and_are_not_negative(neg):
    m = np.asarray(look.NEGATIVES[neg]["sens"])
    np.testing.assert_allclose(m.sum(axis=1), 1.0, atol=1e-9)
    assert (m >= 0).all()


@pytest.mark.parametrize("proc", [p for p in PROCS if look.LAB_PROCESSES[p]])
def test_process_tables_are_well_formed(proc):
    t = look.LAB_PROCESSES[proc]
    np.testing.assert_allclose(np.asarray(t["sens"]).sum(axis=1), 1.0, atol=1e-9)
    assert (np.asarray(t["sens"]) >= 0).all()
    assert len(t["key"]) == 3


@pytest.mark.parametrize("proc", PROCS)
@pytest.mark.parametrize("copia", PRINTS)
def test_plan_sets_every_lab_uniform(proc, copia):
    U = look.build_plan(lab_values(lab_processo=proc, lab_copia=copia), 320, 180, 5, 24.0).uniforms
    declared = dict(re_find(shaders.FINAL))
    lab_keys = [k for k in declared if k.startswith(("u_la_", "u_lb_", "u_lab_"))]
    assert lab_keys and all(k in U for k in lab_keys)
    assert U["u_lab_b_on"] == (1 if look.LAB_PROCESSES[proc] else 0)
    for k in lab_keys:
        val = U[k] if isinstance(U[k], tuple) else (U[k],)
        assert all(math.isfinite(x) for x in val), k


def re_find(src: str):
    import re
    return [(n, t) for t, n in re.findall(r"uniform\s+(\w+)\s+(u_\w+)\s*;", src)]


def test_lab_is_inside_the_color_pipe_so_luts_get_it():
    pipe = shaders.COMMON[shaders.COMMON.index("vec3 colorPipe"):]
    assert "labPipe(lin)" in pipe
    assert "labPipe" in shaders.BAKE  # BAKE = COMMON + ...


# ------------------------------------------------------------------ curvas
def test_characteristic_curve_is_monotonic_and_saturates():
    x = np.linspace(-6, 6, 4001)
    d = look.lab_curve(x, 0.6, -1.6, 2.0, 0.24)
    assert (np.diff(d) >= -1e-12).all()
    assert d[0] == pytest.approx(0.0, abs=1e-6)
    assert d[-1] == pytest.approx(0.6 * 3.6, rel=1e-6)
    mid = look.lab_curve(np.array([0.0, 0.1]), 0.6, -1.6, 2.0, 0.24)
    assert (mid[1] - mid[0]) / 0.1 == pytest.approx(0.6, rel=3e-3)  # trecho reto com inclinação = gama


# ------------------------------------------------------------------ calibração (Python)
@pytest.mark.parametrize("neg, copia, proc", list(itertools.product(NEGS, PRINTS, PROCS)))
def test_mid_grey_is_neutral_for_every_combination(neg, copia, proc):
    v = lab_values(lab_negativo=neg, lab_copia=copia, lab_processo=proc)
    y = look.lab_eval(v, np.full(3, 0.18))
    if proc == "tech2":
        # Duas cores, três canais: a calibração por mínimos quadrados deixa um leve tom no cinza.
        assert np.max(np.abs(y - 0.45)) < 0.006
    else:
        np.testing.assert_allclose(y, 0.45, atol=1e-6)


@pytest.mark.parametrize("neg, copia, proc", list(itertools.product(NEGS, PRINTS, PROCS)))
def test_grey_ramp_is_monotonic_and_inside_0_1(neg, copia, proc):
    v = lab_values(lab_negativo=neg, lab_copia=copia, lab_processo=proc)
    y = look.lab_eval(v, stops(np.linspace(-14, 14, 561)))
    assert np.isfinite(y).all() and (y >= 0).all() and (y <= 1.0 + 1e-9).all()
    assert (np.diff(y, axis=0) >= -1e-9).all()
    # Os negativos "(datasheet)" têm o gama medido (menor que o feito à mão): com a cópia P&B o preto fica em 0,10–0,11.
    assert y[-1].min() > 0.9 and y[0].max() < (0.11 if neg.endswith("_v2") else 0.1)


@pytest.mark.parametrize("proc", PROCS)
def test_extreme_and_saturated_inputs_stay_finite(proc):
    v = lab_values(lab_processo=proc)
    lin = np.array([[0, 0, 0], [1e-12, 1e-12, 1e-12], [5000, 0, 0], [0, 5000, 0], [0, 0, 5000], [800, 300, 2],
                    [1e6, 1e6, 1e6]], dtype=np.float64)
    y = look.lab_eval(v, lin)
    assert np.isfinite(y).all() and (y >= 0).all() and (y <= 1.0 + 1e-9).all()
    # Mais luz nunca escurece uma cor, por mais saturada que seja (sem anéis escuros em volta de luzes
    # estouradas — o problema clássico de matriz com termos negativos).
    k = 2.0 ** np.linspace(-8, 16, 97)
    for c in ([1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0.5, 0], [1, 0, 1], [0.9, 0.6, 0.02]):
        ramp = look.lab_eval(v, k[:, None] * np.asarray(c, dtype=np.float64) * 0.18)
        lum = ramp @ W709
        assert (np.maximum.accumulate(lum) - lum).max() < 0.002, c  # nenhuma queda visível


def test_printer_lights_follow_the_lab():
    base = look.lab_eval(lab_values(), np.full(3, 0.18))
    red = look.lab_eval(lab_values(lab_luz_r=6), np.full(3, 0.18))
    assert red[0] < base[0] - 0.02                      # mais luz vermelha → menos vermelho (mais ciano)
    assert abs(red[1] - base[1]) < 0.02 and abs(red[2] - base[2]) < 0.02
    blue = look.lab_eval(lab_values(lab_luz_b=-6), np.full(3, 0.18))
    assert blue[2] > base[2] + 0.02                     # menos luz azul → mais azul
    dark = look.lab_eval(lab_values(lab_densidade=12), np.full(3, 0.18))
    bright = look.lab_eval(lab_values(lab_densidade=-12), np.full(3, 0.18))
    assert (dark < base - 0.05).all() and (bright > base + 0.05).all()
    np.testing.assert_allclose(dark, dark.mean(), atol=0.01)  # a densidade não muda a cor do cinza


def test_printer_lights_also_work_without_a_print():
    base = look.lab_eval(lab_values(lab_copia="nenhuma"), np.full(3, 0.18))
    np.testing.assert_allclose(base, 0.45, atol=1e-9)
    twelve = look.lab_eval(lab_values(lab_copia="nenhuma", lab_densidade=12), np.full(3, 0.18))
    # 12 pontos = 0,3 log E ≈ 1 stop mais escuro na curva neutra
    np.testing.assert_allclose(twelve, look._stops_to_disp(np.array(-12 * look.LAB_POINT / look.LOG10_2)), atol=1e-9)


@pytest.mark.parametrize("copia", ["2383", "nenhuma"])
def test_push_raises_contrast_and_pull_lowers_it(copia):
    def spread(push):
        y = look.lab_eval(lab_values(lab_revelacao=push, lab_copia=copia), stops(np.array([-2.0, 2.0])))
        return float(y[1, 1] - y[0, 1])
    assert spread(2) > spread(0) + 0.01 > spread(-2) + 0.02


def test_push_changes_grain_only_with_the_lab_on():
    v = params.defaults()
    v.update(grao_on=True, lab_revelacao=2.0)
    off = look.build_plan(v, 1920, 1080, 0, 24.0).uniforms["u_grain_amt"]
    v["lab_on"] = True
    on = look.build_plan(v, 1920, 1080, 0, 24.0).uniforms["u_grain_amt"]
    assert on == pytest.approx(off * 1.15 ** 2)


def test_process_strength_mixes_normal_and_technicolor():
    lin = PATCHES
    normal = look.lab_eval(lab_values(lab_copia="2383"), lin)
    zero = look.lab_eval(lab_values(lab_copia="2383", lab_processo="tech3", lab_processo_forca=0.0), lin)
    np.testing.assert_allclose(zero, normal, atol=1e-12)
    half = look.lab_eval(lab_values(lab_copia="2383", lab_processo="tech3", lab_processo_forca=0.5), lin)
    full = look.lab_eval(lab_values(lab_copia="2383", lab_processo="tech3", lab_processo_forca=1.0), lin)
    np.testing.assert_allclose(half, (normal + full) / 2, atol=1e-9)


def test_technicolor_saturates_and_silver_retention_desaturates():
    neu = look._stops_to_disp(np.log2(PATCHES / 0.18))
    normal = sat(look.lab_eval(lab_values(lab_copia="2383"), PATCHES)) / sat(neu)
    tech3 = sat(look.lab_eval(lab_values(lab_processo="tech3"), PATCHES)) / sat(neu)
    prata = sat(look.lab_eval(lab_values(lab_copia="2383", lab_processo="prata"), PATCHES)) / sat(neu)
    assert tech3.mean() > normal.mean() + 0.15
    assert prata.mean() < normal.mean() - 0.1
    # Prata retida: pretos mais profundos que a cópia normal.
    lo = stops(np.array([-4.0]))
    assert look.lab_eval(lab_values(lab_processo="prata", lab_copia="2383"), lo)[0, 1] < \
        look.lab_eval(lab_values(lab_copia="2383"), lo)[0, 1]


def test_black_key_deepens_technicolor_shadows():
    lo = stops(np.array([-3.0]))
    a = look.lab_eval(lab_values(lab_processo="tech3", lab_chave=0.0), lo)[0, 1]
    b = look.lab_eval(lab_values(lab_processo="tech3", lab_chave=1.0), lo)[0, 1]
    assert b < a


def test_two_strip_has_no_pure_blue_or_green():
    y = look.lab_eval(lab_values(lab_processo="tech2"), PATCHES)
    green, blue = y[1], y[2]
    assert green[1] - max(green[0], green[2]) < 0.02   # verde vira verde-azulado acinzentado
    assert blue[2] - blue[1] < 0.1                     # azul vira ciano


def test_crosstalk_multiplier_changes_saturation():
    neu = look._stops_to_disp(np.log2(PATCHES / 0.18))
    s0 = sat(look.lab_eval(lab_values(lab_copia="2383", lab_diafonia=0.0), PATCHES)) / sat(neu)
    s2 = sat(look.lab_eval(lab_values(lab_copia="2383", lab_diafonia=2.0), PATCHES)) / sat(neu)
    assert s0.mean() > s2.mean() + 0.05


@pytest.mark.parametrize("copia", ["2302", "2383", "nenhuma"])
def test_black_and_white_negative_is_neutral(copia):
    y = look.lab_eval(lab_values(lab_negativo="double_x", lab_copia=copia), PATCHES)
    if copia == "2383":
        assert np.ptp(y, axis=1).max() < 0.03  # a diafonia da cópia colorida deixa só um leve tom
    else:
        np.testing.assert_allclose(np.ptp(y, axis=1), 0.0, atol=1e-9)


def test_calibration_is_cached():
    look.lab_paths.cache_clear()
    look.lab_eval(lab_values(), PATCHES)
    look.lab_eval(lab_values(lab_luz_r=3), PATCHES)  # as luzes não entram na chave do cache
    info = look.lab_paths.cache_info()
    assert info.misses == 1 and info.hits >= 1


# ------------------------------------------------------------------ presets
LAB_PRESETS = [p["id"] for p in presets.BUILTIN if p["grupo"] == "Laboratório"]


def test_lab_group_exists_with_presets():
    assert "Laboratório" in presets.GROUPS
    assert len(LAB_PRESETS) >= 8


@pytest.mark.parametrize("pid", LAB_PRESETS)
def test_lab_presets_use_only_the_density_model(pid):
    v = presets.builtin_values(pid)
    assert v["lab_on"] is True and v["cor_on"] is False and v["copia"] == "nenhuma"


def test_technicolor_preset_uses_three_strip():
    assert presets.builtin_values("lab_technicolor3")["lab_processo"] == "tech3"
    assert presets.builtin_values("lab_technicolor2")["lab_processo"] == "tech2"


# ------------------------------------------------------------------ GPU
def _render(engine, v, img, depth=16):
    h, w = img.shape[:2]
    engine.set_input(img)
    return engine.render(look.build_plan(v, w, h, 0, 24.0, None, dither=False), depth)


def _flat(code: float, w=64, h=32) -> np.ndarray:
    return np.full((h, w, 3), int(round(code * 65535)), dtype=np.uint16)


@pytest.mark.gpu
@pytest.mark.parametrize("neg, copia, proc", [(n, "2383", "normal") for n in NEGS]
                         + [("vision3_250d", c, p) for c in PRINTS for p in PROCS])
def test_gpu_mid_grey_is_neutral(gl_engine, neg, copia, proc):
    v = lab_values(lab_negativo=neg, lab_copia=copia, lab_processo=proc, grao_on=False, hal_on=False,
                   bloom_on=False, lente_on=False, bitola_vinheta=0.0)
    out = _render(gl_engine, v, _flat(0.45)).reshape(-1, 3).mean(axis=0) / 65535.0
    tol = 0.008 if proc == "tech2" else 0.003
    np.testing.assert_allclose(out, 0.45, atol=tol)


@pytest.mark.gpu
@pytest.mark.parametrize("proc", PROCS)
@pytest.mark.parametrize("copia", ["2383", "3513", "nenhuma"])
def test_gpu_matches_numpy_reference(gl_engine, proc, copia):
    rng = np.random.default_rng(7)
    img = rng.integers(0, 65536, size=(48, 64, 3), dtype=np.uint16)
    img[0, :8] = [[0, 0, 0], [65535, 65535, 65535], [65535, 0, 0], [0, 65535, 0], [0, 0, 65535],
                  [29491, 29491, 29491], [65535, 40000, 2000], [1000, 1000, 1000]]
    v = lab_values(lab_processo=proc, lab_copia=copia, lab_luz_r=2.5, lab_luz_b=-1.5, lab_densidade=1.0,
                   lab_revelacao=0.5, grao_on=False, hal_on=False, bloom_on=False, lente_on=False,
                   bitola_vinheta=0.0)
    out = _render(gl_engine, v, img).astype(np.float64) / 65535.0
    ref = look.lab_eval(v, display_to_lin(img.astype(np.float64) / 65535.0))
    ref = look._stops_to_disp(np.clip(np.log2(display_to_lin(ref) / 0.18), -12, 12))  # volta pela curva neutra
    err = np.abs(out - ref)
    assert err.max() < 0.006, f"diferença máxima {err.max():.4f} em {np.unravel_index(err.argmax(), err.shape)}"


@pytest.mark.gpu
def test_gpu_grey_ramp_is_monotonic(gl_engine):
    ramp = np.linspace(0, 65535, 256).astype(np.uint16)
    img = np.repeat(np.repeat(ramp[None, :, None], 4, axis=0), 3, axis=2)
    for proc in PROCS:
        v = lab_values(lab_processo=proc, lab_copia="2383", grao_on=False, hal_on=False, bloom_on=False,
                       lente_on=False, bitola_vinheta=0.0)
        out = _render(gl_engine, v, img)[0].astype(np.int64)
        assert (np.diff(out[:, 1]) >= -2).all(), proc  # ±2 níveis de 16 bits (meia precisão no caminho)


@pytest.mark.gpu
def test_gpu_baked_lut_contains_the_lab(gl_engine):
    v = lab_values(lab_processo="tech3", lab_luz_g=2.0)
    n = 9
    lut = gl_engine.bake_lut(v, n)
    axis = np.linspace(0, 1, n)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    grid = np.stack([r, g, b], axis=-1).reshape(-1, 3)  # ordem .cube: R mais rápido
    ref = look.lab_eval(v, display_to_lin(grid))
    ref = look._stops_to_disp(np.clip(np.log2(display_to_lin(ref) / 0.18), -12, 12))
    assert np.abs(lut - ref).max() < 0.004


@pytest.mark.gpu
def test_gpu_lab_off_ignores_lab_settings(gl_engine, test_rgb):
    v = presets.builtin_values("vision3_250d")
    v["grao_animado"] = False
    a = _render(gl_engine, v, test_rgb, 8)
    v2 = dict(v, lab_negativo="ecn2_5247", lab_copia="nenhuma", lab_processo="tech3", lab_luz_r=7, lab_densidade=-4,
              lab_revelacao=2.0)
    b = _render(gl_engine, v2, test_rgb, 8)
    np.testing.assert_array_equal(a, b)


@pytest.mark.gpu
def test_gpu_skin_controls(gl_engine):
    skin = (np.array([0.8, 0.55, 0.45]) * 65535).astype(np.uint16)
    blue = (np.array([0.2, 0.35, 0.8]) * 65535).astype(np.uint16)
    img = np.zeros((16, 32, 3), np.uint16)
    img[:, :16] = skin
    img[:, 16:] = blue
    base = params.defaults()
    base.update(bitola="nenhuma", cor_on=True, grao_on=False)
    a = _render(gl_engine, base, img).astype(np.int64)
    b = _render(gl_engine, dict(base, pele_matiz=25.0), img).astype(np.int64)
    c = _render(gl_engine, dict(base, pele_luz=-1.0), img).astype(np.int64)
    assert np.abs(b[:, :16] - a[:, :16]).max() > 600       # a pele muda de matiz...
    assert np.abs(b[:, 16:] - a[:, 16:]).max() < 64        # ...o azul não
    assert (c[:, :16] @ W709).mean() < (a[:, :16] @ W709).mean() - 600  # luz da pele: mais densa
    d = _render(gl_engine, base, img)
    np.testing.assert_array_equal(a, d.astype(np.int64))   # padrão é neutro e determinístico


# ------------------------------------------------------------------ controles do fluxo do tutorial (SumerFade)
NEW_DEFAULTS = {"lab_separacao": 0.0, "lab_separacao_eixo": 35.0, "lab_saturacao_filme": 1.0, "lab_saturacao": 1.0,
                "lab_dens_r": 1.0, "lab_dens_g": 1.0, "lab_dens_b": 1.0, "lab_pe": 0.0, "lab_sombras_rolagem": 0.0,
                "lab_luzes_rolagem": 0.0, "lab_pele_matiz": 0.0, "lab_pele_sat": 0.0, "lab_bypass_negativo": 0.0,
                "lab_bypass_copia": 0.0, "lab_neutro_negativo": 0.0, "lab_neutro_copia": 0.0}
EXTREMES = [dict(lab_separacao=1.0), dict(lab_separacao=0.7, lab_separacao_eixo=210.0),
            dict(lab_saturacao_filme=2.0), dict(lab_saturacao_filme=0.0), dict(lab_saturacao=0.0),
            dict(lab_dens_r=2.0, lab_dens_g=0.0, lab_dens_b=2.0), dict(lab_pe=1.0), dict(lab_pe=-1.0),
            dict(lab_sombras_rolagem=1.0, lab_luzes_rolagem=1.0), dict(lab_pele_matiz=30.0, lab_pele_sat=1.0),
            dict(lab_bypass_negativo=1.0), dict(lab_bypass_copia=1.0),
            dict(lab_neutro_negativo=1.0, lab_neutro_copia=1.0)]
SKIN = np.array([0.30, 0.17, 0.11])   # pele em luz linear
SKY = np.array([0.08, 0.16, 0.32])    # céu


def test_new_lab_controls_are_neutral_by_default():
    d = params.defaults()
    for k, val in NEW_DEFAULTS.items():
        assert d[k] == val, k
    assert d["mtf"] == "nenhum" and d["mtf_forca"] == 0.5
    U = look.build_plan(lab_values(), 320, 180, 0, 24.0).uniforms
    assert U["u_lab_ops"] == 0
    for pid in [p["id"] for p in presets.BUILTIN if p["valores"] and p["valores"].get("lab_on")]:
        if pid in ("lab_technicolor_hue_split", "lab_teal_orange_5201"):
            continue
        v = presets.builtin_values(pid)
        assert look.build_plan(v, 64, 36, 0, 24.0).uniforms["u_lab_ops"] == 0, pid


@pytest.mark.parametrize("over", EXTREMES, ids=[",".join(o) for o in EXTREMES])
@pytest.mark.parametrize("neg, copia, proc", [("vision3_250d", "2383", "normal"), ("ecn2_5297", "e5386", "normal"),
                                              ("vision2_5229", "nenhuma", "normal"), ("vision3_500t", "2393", "tech3"),
                                              ("vision2_5201", "e5385", "prata"), ("double_x", "2302", "normal")])
def test_mid_grey_stays_neutral_with_every_new_control(neg, copia, proc, over):
    v = lab_values(lab_negativo=neg, lab_copia=copia, lab_processo=proc, **over)
    np.testing.assert_allclose(look.lab_eval(v, np.full(3, 0.18)), 0.45, atol=1e-6)
    y = look.lab_eval(v, stops(np.linspace(-12, 12, 241)))
    assert np.isfinite(y).all() and (y >= 0).all()
    assert (np.diff(y @ W709) >= -1e-6).all()  # o cinza continua subindo


GREEN = np.array([0.08, 0.20, 0.07])
MAGENTA = np.array([0.25, 0.08, 0.22])


def split_coords(y, hue_deg=35.0):
    """Cor em log, sem o neutro, nos eixos da separação: u (laranja ↔ azul) e v (verde ↔ magenta)."""
    u, v = look.split_axes(hue_deg)
    c = np.log(np.maximum(np.asarray(y, dtype=np.float64), 1e-9))
    c = c - c.mean(axis=-1, keepdims=True)
    return c @ u, c @ v


def test_hue_split_pushes_warm_and_cool_apart_and_squeezes_the_rest():
    lin = np.stack([SKIN, SKY, GREEN, MAGENTA])
    u0, v0 = split_coords(look.lab_eval(lab_values(), lin))
    u1, v1 = split_coords(look.lab_eval(lab_values(lab_separacao=0.69), lin))
    u2, v2 = split_coords(look.lab_eval(lab_values(lab_separacao=1.0), lin))
    assert u0[0] > 0 > u0[1]                                 # pele no polo quente, céu no frio
    assert u0[0] - u0[1] < u1[0] - u1[1] < u2[0] - u2[1]     # e se afastam com a quantidade
    assert u1[0] - u1[1] > 1.2 * (u0[0] - u0[1])
    for i in (2, 3):                                         # verde e magenta: comprimidos
        assert abs(v2[i]) < abs(v1[i]) < abs(v0[i]) * 0.85
    # mesmo efeito em qualquer exposição (é feito na densidade, em log)
    for k in (0.25, 4.0):
        a, _ = split_coords(look.lab_eval(lab_values(), lin[:2] * k))
        b, _ = split_coords(look.lab_eval(lab_values(lab_separacao=0.69), lin[:2] * k))
        assert b[0] - b[1] > 1.15 * (a[0] - a[1])
    # o eixo gira a separação: a 215° o polo "quente" passa a ser o azul
    ua, _ = split_coords(look.lab_eval(lab_values(lab_separacao=1.0, lab_separacao_eixo=215.0), lin), 215.0)
    assert ua[1] > 0 > ua[0]


def test_hue_split_matrix_keeps_neutral_and_mean():
    for amount, hue_deg in ((0.69, 35.0), (1.0, 200.0), (0.3, 300.0)):
        m = look.split_matrix(amount, hue_deg)
        np.testing.assert_allclose(m @ np.ones(3), np.ones(3), atol=1e-12)
        np.testing.assert_allclose(np.ones(3) @ m, np.ones(3), atol=1e-12)
    np.testing.assert_array_equal(look.split_matrix(0.0, 35.0), np.eye(3))
    u, v = look.split_axes(35.0)
    assert abs(u @ v) < 1e-12 and abs(u.sum()) < 1e-12 and abs(v.sum()) < 1e-12


def test_density_per_color_only_touches_that_color():
    lin = np.stack([SKY, np.array([0.30, 0.05, 0.04]), np.full(3, 0.18)])
    base = look.lab_eval(lab_values(), lin)
    blue = look.lab_eval(lab_values(lab_dens_b=1.8), lin)
    assert blue[0] @ W709 < base[0] @ W709 - 0.01            # o céu fica mais denso
    np.testing.assert_allclose(blue[1:], base[1:], atol=1e-9)  # vermelho e cinza iguais
    light = look.lab_eval(lab_values(lab_dens_r=0.2), lin)
    assert light[1] @ W709 > base[1] @ W709 + 0.005            # menos densidade clareia


def test_black_toe_and_roll_offs():
    lo, hi = stops(np.array([-6.0])), stops(np.array([5.0]))
    base_lo = look.lab_eval(lab_values(), lo)[0, 1]
    assert look.lab_eval(lab_values(lab_pe=0.8), lo)[0, 1] > base_lo + 0.01      # pé positivo lava o preto
    assert look.lab_eval(lab_values(lab_pe=-0.8), lo)[0, 1] <= base_lo           # negativo aprofunda
    s0 = look.lab_eval(lab_values(), stops(np.array([-3.0])))[0, 1]
    s1 = look.lab_eval(lab_values(lab_sombras_rolagem=1.0), stops(np.array([-3.0])))[0, 1]
    h0 = look.lab_eval(lab_values(), hi)[0, 1]
    h1 = look.lab_eval(lab_values(lab_luzes_rolagem=1.0), hi)[0, 1]
    assert s1 > s0 + 0.01 and h1 < h0 - 0.01


def test_saturations():
    neu = look._stops_to_disp(np.log2(PATCHES / 0.18))
    base = sat(look.lab_eval(lab_values(), PATCHES)) / sat(neu)
    film = sat(look.lab_eval(lab_values(lab_saturacao_filme=1.6), PATCHES)) / sat(neu)
    assert film.mean() > base.mean() + 0.1
    grey = look.lab_eval(lab_values(lab_saturacao=0.0), PATCHES)
    np.testing.assert_allclose(np.ptp(grey, axis=1), 0.0, atol=1e-9)  # saturação final 0 = preto e branco


def test_bleach_bypass_on_negative_and_print():
    neu = look._stops_to_disp(np.log2(PATCHES / 0.18))
    base = sat(look.lab_eval(lab_values(), PATCHES)) / sat(neu)
    for k in ("lab_bypass_negativo", "lab_bypass_copia"):
        s = sat(look.lab_eval(lab_values(**{k: 1.0}), PATCHES)) / sat(neu)
        assert s.mean() < base.mean() - 0.05, k

    def spread(**over):
        y = look.lab_eval(lab_values(**over), stops(np.array([-2.0, 2.0])))
        return float(y[1, 1] - y[0, 1])

    assert spread(lab_bypass_negativo=1.0) > spread() + 0.01                 # prata no negativo: mais contraste
    lo = stops(np.array([-4.0]))
    assert look.lab_eval(lab_values(lab_bypass_copia=1.0), lo)[0, 1] < look.lab_eval(lab_values(), lo)[0, 1]


def test_neutral_curves_remove_the_stock_crossover():
    ramp = stops(np.array([-5.0, -3.0, 3.0, 5.0]))
    v = dict(lab_negativo="ecn2_5247", lab_copia="e5385")
    a = np.ptp(look.lab_eval(lab_values(**v), ramp), axis=1).max()
    b = np.ptp(look.lab_eval(lab_values(lab_neutro_negativo=1.0, lab_neutro_copia=1.0, **v), ramp), axis=1).max()
    assert b < a * 0.5


def test_lab_skin_controls_only_touch_skin():
    lin = np.stack([SKIN, SKY])
    a = look.lab_eval(lab_values(), lin)
    b = look.lab_eval(lab_values(lab_pele_matiz=25.0, lab_pele_sat=0.6), lin)
    assert np.abs(b[0] - a[0]).max() > 0.01
    np.testing.assert_allclose(b[1], a[1], atol=1e-3)


def test_new_controls_enter_the_cache_key_rounded():
    look.lab_paths.cache_clear()
    look.lab_eval(lab_values(lab_separacao=0.5), PATCHES)
    look.lab_eval(lab_values(lab_separacao=0.50000001), PATCHES)   # arredondado: mesma calibração
    look.lab_eval(lab_values(lab_separacao=0.5, lab_saturacao=1.4, lab_dens_b=1.3), PATCHES)  # depois da cópia
    assert look.lab_paths.cache_info().misses == 1
    look.lab_eval(lab_values(lab_separacao=0.6), PATCHES)
    assert look.lab_paths.cache_info().misses == 2


def test_new_stocks_exist_and_are_calibrated():
    for k in ("vision2_5201", "ecn2_5297", "vision_5246", "vision_5263", "vision2_5229"):
        assert k in look.NEGATIVES and k in dict(params.NEGATIVOS)
    for k in ("e5386", "e5385"):
        assert k in look.LAB_PRINTS and k in dict(params.COPIAS_LAB)


def test_video_presets():
    v = presets.builtin_values("lab_technicolor_hue_split")
    assert (v["lab_negativo"], v["lab_copia"]) == ("ecn2_5297", "e5386")
    assert v["lab_separacao"] == pytest.approx(0.69) and v["lab_saturacao_filme"] == pytest.approx(1.3)
    assert v["mtf"] == "close"
    w = presets.builtin_values("lab_teal_orange_5201")
    assert (w["lab_negativo"], w["lab_copia"]) == ("vision2_5201", "2393") and w["lab_dens_b"] > 1


def test_mtf_softens_through_the_soft_blur():
    v = params.defaults()
    v["bitola"] = "nenhuma"
    assert look.build_plan(v, 1920, 1080, 0, 24.0).soft_sigma == 0.0
    v.update(mtf="close", mtf_forca=0.5)
    assert look.build_plan(v, 1920, 1080, 0, 24.0).soft_sigma == pytest.approx(look.MTF_SIGMA["close"])
    assert look.build_plan(v, 3840, 2160, 0, 24.0).soft_sigma == pytest.approx(2 * look.MTF_SIGMA["close"])
    v["mtf_forca"] = 1.0
    assert look.build_plan(v, 1920, 1080, 0, 24.0).soft_sigma == pytest.approx(2 * look.MTF_SIGMA["close"])
    v.update(bitola="16mm")
    want = math.hypot(look.GAUGES["16mm"]["blur"], 2 * look.MTF_SIGMA["close"])
    assert look.build_plan(v, 1920, 1080, 0, 24.0).soft_sigma == pytest.approx(want)


@pytest.mark.gpu
@pytest.mark.parametrize("over", EXTREMES[:6] + [dict(lab_separacao=0.69, lab_saturacao_filme=1.3, lab_pe=0.3,
                                                      lab_dens_b=1.5, lab_pele_matiz=10.0, lab_luzes_rolagem=0.5)],
                         ids=[str(i) for i in range(7)])
def test_gpu_new_controls_match_numpy(gl_engine, over):
    rng = np.random.default_rng(11)
    img = rng.integers(0, 65536, size=(32, 48, 3), dtype=np.uint16)
    v = lab_values(lab_negativo="ecn2_5297", lab_copia="e5386", grao_on=False, hal_on=False, bloom_on=False,
                   lente_on=False, bitola_vinheta=0.0, **over)
    out = _render(gl_engine, v, img).astype(np.float64) / 65535.0
    ref = look.lab_eval(v, display_to_lin(img.astype(np.float64) / 65535.0))
    ref = look._stops_to_disp(np.clip(np.log2(display_to_lin(ref) / 0.18), -12, 12))  # volta pela curva neutra
    assert np.abs(out - ref).max() < 0.006


@pytest.mark.gpu
def test_gpu_mtf_removes_fine_detail(gl_engine):
    rng = np.random.default_rng(3)
    img = (rng.random((540, 960, 3)) * 65535).astype(np.uint16)  # meia resolução: σ do "close" ≈ 1,6 px
    v = params.defaults()
    v.update(bitola="nenhuma")
    a = _render(gl_engine, v, img).astype(np.float64)
    b = _render(gl_engine, dict(v, mtf="close", mtf_forca=1.0), img).astype(np.float64)

    def hf(x):
        return np.abs(np.diff(x, axis=1)).mean()

    assert hf(b) < hf(a) * 0.6
