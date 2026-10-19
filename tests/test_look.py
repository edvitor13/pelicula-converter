"""build_plan e tabelas do look (sem GPU)."""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

from pelicula import look, params, presets, shaders

# ------------------------------------------------------------------ contrato com os shaders
_SHADER_SOURCES = {n: getattr(shaders, n) for n in ("BASE", "EXTRACT", "BLUR", "NOISE", "FINAL", "BAKE")}
_SIZES = {"int": 1, "float": 1, "vec2": 2, "vec3": 3, "vec4": 4, "mat3": 9}


def _declared() -> dict[str, str]:
    out: dict[str, str] = {}
    for src in _SHADER_SOURCES.values():
        for typ, name in re.findall(r"uniform\s+(\w+)\s+(u_\w+)\s*;", src):
            assert out.get(name, typ) == typ, f"{name} declarado com tipos diferentes"
            out[name] = typ
    return out


DECLARED = _declared()
# Uniforms que o próprio Engine preenche em cada passo (não vêm do plano).
ENGINE_SET = {"u_dir", "u_sigma", "u_lod", "u_thr", "u_limit", "u_lum_only", "u_use_alpha", "u_seed"}

ALWAYS = ["u_res", "u_scale", "u_input", "u_gamut", "u_shift", "u_rot", "u_zoom", "u_gain", "u_dist", "u_ca",
          "u_vig", "u_soft_on", "u_soft_mix", "u_sharp", "u_hal_on", "u_bloom_on", "u_mist_on", "u_leak_on",
          "u_film_on", "u_film_mix", "u_slope", "u_mid", "u_black", "u_white", "u_ps", "u_pt", "u_sat", "u_density",
          "u_ch_gamma", "u_ch_offset", "u_shadow_tint", "u_high_tint", "u_balance", "u_hue", "u_bw", "u_bw_w",
          "u_tone_amt", "u_tone_sh", "u_tone_hi", "u_age", "u_print_on", "u_lut_on", "u_grain_on", "u_dust",
          "u_dust_size", "u_dust_type", "u_scratch", "u_scratch_w", "u_hair", "u_stain", "u_cue", "u_splice",
          "u_dmg_on", "u_frame", "u_seed_d", "u_scan_on", "u_text_aspect", "u_frame_on", "u_aspect_t", "u_corner",
          "u_edge_soft", "u_edge_rough", "u_bar_color", "u_mix", "u_dither", "u_lab_on", "u_skin"]


def plan(v=None, w=1920, h=1080, frame=0, fps=24.0, lut=None, dither=True, **over):
    vals = dict(v if v is not None else params.defaults())
    vals.update(over)
    return look.build_plan(vals, w, h, frame, fps, lut, dither)


def everything_on() -> dict:
    v = params.defaults()
    for k, p in params.PARAMS.items():
        if p.kind == "bool":
            v[k] = True
    v.update(copia="k2383", vazamento=0.6, nevoa_forca=0.4, virada="sepia", maciez=0.5, nitidez=0.5, aberracao=2.0,
             distorcao=0.1, cabelo=1.0, manchas=1.0, queima=1.0, emenda=1.0, cor_instavel=0.8, lut_arquivo="x.cube")
    return v


def assert_matches_shaders(U: dict):
    for k, val in U.items():
        assert k in DECLARED, f"{k} não existe em nenhum shader"
        typ = DECLARED[k]
        n = len(val) if isinstance(val, (tuple, list)) else 1
        assert n == _SIZES[typ], f"{k}: {typ} recebeu {val!r}"
        assert not isinstance(val, list), f"{k}: use tupla (o motor reaproveita o dict)"
        flat = val if isinstance(val, tuple) else (val,)
        for x in flat:
            if typ == "int":
                assert isinstance(x, int), f"{k}: int recebeu {type(x).__name__}"
            else:
                assert isinstance(x, (int, float)) and math.isfinite(x), f"{k}: {x!r}"


def test_required_uniform_keys_present_for_defaults():
    U = plan().uniforms
    missing = [k for k in ALWAYS if k not in U]
    assert not missing


def test_defaults_plan_matches_shader_declarations():
    assert_matches_shaders(plan().uniforms)


def test_everything_on_plan_sets_every_shader_uniform():
    p = plan(everything_on(), frame=37, lut=(33, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
    assert_matches_shaders(p.uniforms)
    missing = set(DECLARED) - ENGINE_SET - set(p.uniforms)
    assert not missing, f"uniforms que nunca recebem valor: {sorted(missing)}"


@pytest.mark.parametrize("pid", [p["id"] for p in presets.BUILTIN])
def test_every_preset_plan_matches_shaders(pid):
    v = presets.builtin_values(pid)
    for frame in (0, 1, 47, 1000):
        for w, h in ((1920, 1080), (320, 180), (1080, 1920)):
            assert_matches_shaders(plan(v, w, h, frame).uniforms)


@pytest.mark.parametrize("entrada", [c[0] for c in params.PARAMS["entrada"].choices])
def test_every_input_profile(entrada):
    U = plan(entrada=entrada).uniforms
    assert U["u_input"] == look.INPUT_IDS[entrada]
    assert_matches_shaders(U)


@pytest.mark.parametrize("lut_entrada", [c[0] for c in params.PARAMS["lut_entrada"].choices])
def test_every_lut_input(lut_entrada):
    U = plan(lut_on=True, lut_arquivo="a.cube", lut_entrada=lut_entrada, lut=(17, (0, 0, 0), (1, 1, 1))).uniforms
    assert U["u_lut_in"] == look.INPUT_IDS[lut_entrada]
    assert_matches_shaders(U)


# ------------------------------------------------------------------ tabelas
def test_tables_cover_every_choice():
    ch = {k: [c[0] for c in p.choices] for k, p in params.PARAMS.items() if p.kind == "choice"}
    assert set(ch["entrada"]) <= set(look.INPUT_IDS) and set(ch["entrada"]) <= set(look.INPUT_GAMUT)
    assert set(ch["lut_entrada"]) <= set(look.INPUT_IDS) and set(ch["lut_entrada"]) <= set(look.INPUT_GAMUT)
    assert set(ch["bitola"]) == set(look.GAUGES) and set(ch["bitola"]) <= set(look.GAUGE_SCAN)
    assert set(ch["copia"]) == set(look.PRINTS)
    assert set(ch["pb_filtro"]) == set(look.BW_WEIGHTS)
    assert set(ch["virada"]) - {"nenhuma"} == set(look.TONES)
    assert set(ch["scan_formato"]) - {"bitola"} <= set(look.SCAN_FORMATS)
    assert set(look.GAUGE_SCAN.values()) <= set(look.SCAN_FORMATS)
    assert set(ch["scan_texto"]) - {"auto", "nenhum"} == set(look.EDGE_TEXTS)
    assert set(ch["lab_negativo"]) == set(look.NEGATIVES)
    assert set(ch["lab_copia"]) == set(look.LAB_PRINTS)
    assert set(ch["lab_processo"]) == set(look.LAB_PROCESSES)
    for k in ("bitola", "proporcao"):
        assert ch[k]
    for prop in ch["proporcao"]:
        if prop not in ("original", "bitola"):
            assert float(prop) > 1.0
    assert len(set(look.INPUT_IDS.values())) == len(look.INPUT_IDS)
    assert set(look.INPUT_GAMUT.values()) <= set(look._PRIMARIES)


@pytest.mark.parametrize("filtro", list(look.BW_WEIGHTS))
def test_bw_weights_sum_to_one(filtro):
    assert sum(look.BW_WEIGHTS[filtro]) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("gamut", list(look._PRIMARIES))
def test_gamut_matrices_preserve_white(gamut):
    m = look.gamut_to_709(gamut)
    np.testing.assert_allclose(m @ np.ones(3), np.ones(3), atol=1e-9)


def test_gamut_709_is_identity_and_known_2020_matrix():
    np.testing.assert_allclose(look.gamut_to_709("709"), np.eye(3), atol=1e-12)
    # BT.2020 -> BT.709 (valores de referência da ITU-R BT.2087)
    ref = np.array([[1.6605, -0.5876, -0.0728], [-0.1246, 1.1329, -0.0083], [-0.0182, -0.1006, 1.1187]])
    np.testing.assert_allclose(look.gamut_to_709("2020"), ref, atol=2e-3)


def test_mat3_uniform_is_column_major():
    m = np.arange(9).reshape(3, 3)
    assert look.mat3_uniform(m) == (0.0, 3.0, 6.0, 1.0, 4.0, 7.0, 2.0, 5.0, 8.0)
    assert all(isinstance(x, float) for x in look.mat3_uniform(m))


def test_hash_and_value_noise_ranges():
    hs = [look._hash(i, s) for i in range(-50, 500) for s in (0, 1, 999)]
    assert min(hs) >= 0.0 and max(hs) <= 1.0
    assert len(set(hs)) > len(hs) * 0.99
    ns = [look._vnoise(x * 0.137, 5) for x in range(-300, 3000)]
    assert min(ns) >= -1.0 and max(ns) <= 1.0
    # contínuo: passos pequenos mudam pouco
    assert max(abs(a - b) for a, b in zip(ns, ns[1:])) < 0.45


@pytest.mark.parametrize("hue", [0, 35, 120, 200, 300, 359])
def test_hsv_tint_is_luma_neutral(hue):
    t = look._hsv_tint(hue, 1.0)
    assert 0.2126 * t[0] + 0.7152 * t[1] + 0.0722 * t[2] == pytest.approx(0.0, abs=1e-12)
    assert look._hsv_tint(hue, 0.0) == (0.0, 0.0, 0.0)


def test_softness_p_mapping():
    assert look._softness_p(0) == 4.0
    assert look._softness_p(1) == pytest.approx(1.15)


# ------------------------------------------------------------------ curva neutra
def neutral_forward(lin: float) -> float:
    """Mesma curva do shader (stopsToDisp(linToStops(lin)))."""
    t = max(min(math.log2(max(lin, 1e-7) / 0.18), 12.0), -12.0)
    r = (1.0 - look.D_MID) if t >= 0 else look.D_MID
    u = t * look.D_SLOPE / r
    return look.D_MID + r * u / (1.0 + abs(u) ** look.D_P) ** (1.0 / look.D_P)


def test_display_to_lin_mid_grey():
    assert look.display_to_lin((0.45, 0.45, 0.45)) == pytest.approx((0.18, 0.18, 0.18), rel=1e-9)


@pytest.mark.parametrize("y", list(np.linspace(0.02, 0.98, 25)))
def test_display_to_lin_inverts_neutral_curve(y):
    (lin,) = look.display_to_lin((y,))
    assert lin > 0
    assert neutral_forward(lin) == pytest.approx(y, abs=1e-6)


def test_display_to_lin_monotonic_and_clamped():
    ys = np.linspace(0.0, 1.0, 101)
    lins = [look.display_to_lin((y,))[0] for y in ys]
    assert all(b > a for a, b in zip(lins, lins[1:]))
    assert lins[0] >= 0.18 * 2 ** -12 - 1e-12
    assert lins[-1] <= 0.18 * 2 ** 8 + 1e-9


# ------------------------------------------------------------------ build_plan
def test_build_plan_is_deterministic():
    v = presets.builtin_values("8mm_caseiro")
    a = plan(v, frame=123)
    b = plan(dict(v), frame=123)
    assert a.uniforms == b.uniforms
    assert (a.grain_size, a.grain_seed, a.soft_sigma, a.chains, a.edge_text) == \
           (b.grain_size, b.grain_seed, b.soft_sigma, b.chains, b.edge_text)


def test_build_plan_does_not_mutate_values():
    v = presets.builtin_values("super8_kodachrome")
    before = {k: (list(x) if isinstance(x, list) else x) for k, x in v.items()}
    plan(v, frame=10)
    assert v == before


def test_basic_geometry_and_scale():
    U = plan(w=3840, h=2160).uniforms
    assert U["u_res"] == (3840.0, 2160.0)
    assert U["u_scale"] == 2.0
    assert plan(w=640, h=360).uniforms["u_scale"] == pytest.approx(1 / 3)


def test_zero_fps_falls_back_to_24():
    assert plan(fps=0, frame=48, proj_on=True).uniforms == plan(fps=24.0, frame=48, proj_on=True).uniforms


def test_projector_off_means_no_motion():
    for f in range(0, 200, 7):
        U = plan(frame=f).uniforms
        assert U["u_shift"] == (0.0, 0.0)
        assert U["u_rot"] == 0.0
        assert U["u_zoom"] == 1.0
        assert U["u_gain"] == (0.0, 0.0, 0.0)


def test_projector_on_moves_but_stays_bounded():
    v = presets.builtin_values("8mm_caseiro")
    assert v["proj_on"]
    w, h = 1920, 1080
    gauge = look.GAUGES[v["bitola"]]
    bx = v["tremor_x"] * gauge["weave"] * (h / 1080)
    by = v["tremor_y"] * gauge["weave"] * (h / 1080)
    rmax = math.radians(v["tremor_rot"] * gauge["weave"])
    shifts = []
    for f in range(96):
        U = plan(v, w, h, f).uniforms
        dx, dy = U["u_shift"]
        shifts.append((dx, dy))
        assert abs(dx) <= bx + 1e-9 and abs(dy) <= by + 1e-9
        assert abs(U["u_rot"]) <= rmax + 1e-12
        assert U["u_zoom"] > 1.0
        # o zoom esconde as bordas mesmo no maior deslocamento
        margin = (U["u_zoom"] - 1.0) * min(w, h) / 2.0
        assert margin >= max(abs(dx), abs(dy))
    assert len(set(shifts)) > 90
    assert np.std([s[0] for s in shifts]) > 0.1 * bx


def test_flicker_changes_gain_per_frame():
    gains = {plan(frame=f, proj_on=True, cintilacao=0.2).uniforms["u_gain"] for f in range(48)}
    assert len(gains) > 40
    for g in gains:
        assert max(abs(x) for x in g) <= 0.2 + 1e-9
    # sem cintilação o ganho fica fixo
    assert {plan(frame=f, proj_on=True, cintilacao=0.0).uniforms["u_gain"] for f in range(10)} == {(0.0, 0.0, 0.0)}


def test_exposure_and_white_balance():
    assert plan(exposicao=1.5).uniforms["u_gain"] == (1.5, 1.5, 1.5)
    r, g, b = plan(temperatura=100).uniforms["u_gain"]
    assert r > 0 > b and g == 0
    r, g, b = plan(tint=100).uniforms["u_gain"]
    assert g < 0 and r > 0 and b > 0


def test_grain_size_scales_with_resolution():
    v = params.defaults()
    v.update(grao_on=True, bitola="8mm")
    p1080 = plan(v, 1920, 1080)
    p2160 = plan(v, 3840, 2160)
    assert p1080.grain_size > 1.0
    assert p2160.grain_size == pytest.approx(2 * p1080.grain_size)
    # nunca menor que 1 px
    assert plan(v, 320, 180).grain_size == 1.0
    # na prévia pequena a intensidade é compensada para baixo
    assert plan(v, 320, 180).uniforms["u_grain_amt"] < p1080.uniforms["u_grain_amt"]


def test_grain_depends_on_iso_gauge_and_toggle():
    base = params.defaults()
    base.update(grao_on=True)
    lo = plan(base, iso="50")
    hi = plan(base, iso="3200")
    assert hi.grain_size > lo.grain_size
    assert hi.uniforms["u_grain_amt"] > lo.uniforms["u_grain_amt"]
    assert plan(base, bitola="8mm").grain_size > plan(base, bitola="imax").grain_size
    off = plan(base, grao_on=False)
    assert off.grain_size == 0.0 and off.uniforms["u_grain_on"] == 0
    zero = plan(base, grao_forca=0.0)
    assert zero.grain_size == 0.0 and zero.uniforms["u_grain_on"] == 0


def test_grain_seed_animation():
    v = params.defaults()
    v.update(grao_on=True)
    assert len({plan(v, frame=f).grain_seed for f in range(10)}) == 10
    v["grao_animado"] = False
    assert len({plan(v, frame=f).grain_seed for f in range(10)}) == 1
    assert plan(v, grao_semente=1).grain_seed != plan(v, grao_semente=2).grain_seed


def test_softness_from_gauge_and_lens():
    assert plan(bitola="nenhuma").soft_sigma == 0.0
    assert plan(bitola="nenhuma").uniforms["u_soft_on"] == 0
    p = plan(bitola="8mm")
    assert p.soft_sigma == pytest.approx(look.GAUGES["8mm"]["blur"])
    assert p.uniforms["u_soft_on"] == 1 and p.uniforms["u_soft_mix"] == 1.0
    assert plan(bitola="8mm", w=3840, h=2160).soft_sigma == pytest.approx(2 * look.GAUGES["8mm"]["blur"])
    assert plan(bitola="8mm", bitola_resolucao=0.0).soft_sigma == 0.0
    # só nitidez: desfoca para extrair detalhe, mas não mistura o desfoque
    sh = plan(bitola="nenhuma", lente_on=True, nitidez=1.0)
    assert sh.uniforms["u_soft_on"] == 1 and sh.uniforms["u_soft_mix"] == 0.0 and sh.soft_sigma > 0
    assert sh.uniforms["u_sharp"] == 1.0
    # lente desligada ignora os ajustes da lente
    off = plan(bitola="nenhuma", lente_on=False, nitidez=1.0, maciez=1.0, distorcao=0.2, aberracao=5.0)
    assert off.uniforms["u_sharp"] == 0.0 and off.soft_sigma == 0.0
    assert off.uniforms["u_dist"] == 0.0 and off.uniforms["u_ca"] == 0.0


def test_lens_uniforms():
    U = plan(lente_on=True, distorcao=0.1, aberracao=4.0, w=1920, h=1080).uniforms
    assert U["u_dist"] == 0.1
    assert U["u_ca"] == pytest.approx(4.0 / 540.0)


def test_vignette_from_gauge_even_without_lens():
    assert plan(bitola="nenhuma").uniforms["u_vig"][0] == 0.0
    assert plan(bitola="8mm").uniforms["u_vig"][0] == pytest.approx(look.GAUGES["8mm"]["vignette"])
    assert plan(bitola="8mm", bitola_vinheta=0.0).uniforms["u_vig"][0] == 0.0
    assert plan(bitola="8mm", lente_on=True, vinheta=1.0).uniforms["u_vig"][0] <= 1.5


def test_glow_chains():
    v = params.defaults()
    v.update(hal_on=True, bloom_on=True, nevoa_forca=0.5, bitola="16mm")
    p = plan(v)
    names = [c.name for c in p.chains]
    assert names == ["hal", "bloom", "mist"]
    hal = p.chains[0]
    assert hal.threshold == pytest.approx(0.18 * 2 ** v["hal_limiar"])
    assert hal.sigma == pytest.approx(v["hal_raio"] * look.GAUGES["16mm"]["hal"])
    assert hal.lum_only and not hal.alpha_mask
    assert plan(v, w=3840, h=2160).chains[0].sigma == pytest.approx(2 * hal.sigma)
    assert p.chains[2].threshold == 0.0
    U = p.uniforms
    assert U["u_hal_on"] == U["u_bloom_on"] == U["u_mist_on"] == 1
    assert U["u_hal_color"] == tuple(v["hal_cor"])
    # forças zeradas desligam as cadeias
    q = plan(v, hal_forca=0.0, bloom_forca=0.0, nevoa_forca=0.0)
    assert q.chains == [] and q.uniforms["u_hal_on"] == q.uniforms["u_bloom_on"] == q.uniforms["u_mist_on"] == 0


def test_print_stage():
    assert plan(copia="nenhuma").uniforms["u_print_on"] == 0
    U = plan(copia="k2393", copia_forca=0.5).uniforms
    assert U["u_print_on"] == 1 and U["u_print_amt"] == 0.5
    assert U["u_pr_slope"] == pytest.approx(look.D_SLOPE * look.PRINTS["k2393"]["slope"])


def test_lut_requires_file_info():
    assert plan(lut_on=True, lut_arquivo="a.cube", lut=None).uniforms["u_lut_on"] == 0
    p = plan(lut_on=True, lut_arquivo="a.cube", lut_posicao="lugar", lut=(33, (0, 0, 0), (1, 1, 1)))
    assert p.uniforms["u_lut_on"] == 1 and p.uniforms["u_lut_pos"] == 1 and p.uniforms["u_lut_size"] == 33.0
    assert p.lut_path == "a.cube"
    assert plan(lut_on=False, lut_arquivo="a.cube", lut=(33, (0, 0, 0), (1, 1, 1))).uniforms["u_lut_on"] == 0


def test_bw_and_toning():
    U = plan(pb=True, pb_filtro="vermelho", virada="sepia", virada_forca=0.7).uniforms
    assert U["u_bw"] == 1 and U["u_bw_w"] == look.BW_WEIGHTS["vermelho"]
    assert U["u_tone_amt"] == 0.7 and (U["u_tone_sh"], U["u_tone_hi"]) == look.TONES["sepia"]
    # viragem só vale no P&B
    assert plan(pb=False, virada="sepia").uniforms["u_tone_amt"] == 0.0


def test_mix_and_dither_flags():
    assert plan(mix_geral=0.3).uniforms["u_mix"] == 0.3
    assert plan(dither=True).uniforms["u_dither"] == 1
    assert plan(dither=False).uniforms["u_dither"] == 0


# ------------------------------------------------------------------ defeitos
def damage_values(**over):
    v = params.defaults()
    v.update(desg_on=True, poeira_on=True, poeira=0.5, riscos_on=True, riscos=0.5)
    v.update(over)
    return v


def test_damage_toggles_gate_uniforms():
    on = plan(damage_values()).uniforms
    assert on["u_dust"] == 0.5 and on["u_scratch"] == 0.5 and on["u_dmg_on"] == 1
    no_dust = plan(damage_values(poeira_on=False)).uniforms
    assert no_dust["u_dust"] == 0.0 and no_dust["u_scratch"] == 0.5
    no_scratch = plan(damage_values(riscos_on=False)).uniforms
    assert no_scratch["u_scratch"] == 0.0
    off = plan(damage_values(desg_on=False)).uniforms
    assert off["u_dust"] == 0.0 and off["u_scratch"] == 0.0 and off["u_dmg_on"] == 0
    assert off["u_leak_on"] == 0 and off["u_hair"][0] == 0.0 and off["u_cue"] == 0.0
    nothing = plan(damage_values(poeira_on=False, riscos_on=False)).uniforms
    assert nothing["u_dmg_on"] == 0


@pytest.mark.parametrize("tipo, code", [("escura", 0), ("clara", 1), ("mista", 2)])
def test_dust_type(tipo, code):
    assert plan(damage_values(poeira_tipo=tipo)).uniforms["u_dust_type"] == code


def test_light_leak_gating_and_motion():
    v = damage_values(vazamento_on=True, vazamento=0.5)
    U = plan(v, frame=10).uniforms
    assert U["u_leak_on"] == 1 and U["u_leak_amt"] == 0.5 and U["u_leak_color"] == tuple(v["vazamento_cor"])
    assert plan(v, frame=10).uniforms["u_leak0"] != plan(v, frame=200).uniforms["u_leak0"]
    assert plan(damage_values(vazamento_on=False, vazamento=0.5)).uniforms["u_leak_on"] == 0
    assert plan(damage_values(vazamento_on=True, vazamento=0.0)).uniforms["u_leak_on"] == 0


def test_reel_change_cue_marks():
    v = damage_values(poeira_on=False, riscos_on=False, marcas_on=True, marcas_intervalo=4)
    per = 4 * 24
    cues = [f for f in range(0, 3 * per + 10) if plan(v, frame=f).uniforms["u_cue"] > 0]
    assert cues == [per, per + 1, per + 2, per + 3, 2 * per, 2 * per + 1, 2 * per + 2, 2 * per + 3,
                    3 * per, 3 * per + 1, 3 * per + 2, 3 * per + 3]
    assert plan(v, frame=per).uniforms["u_dmg_on"] == 1


def test_splice_jumps_frame():
    v = damage_values(poeira_on=False, riscos_on=False, emenda_on=True, emenda=1.0)
    hits = [f for f in range(24 * 30) if plan(v, frame=f).uniforms["u_splice"][0] > 0]
    assert hits, "com emenda=1 deveria haver emendas em 30 s"
    for f in hits:
        U = plan(v, frame=f).uniforms
        assert U["u_shift"][1] == pytest.approx(14.0)
        assert plan(v, frame=f + 1).uniforms["u_shift"][1] == pytest.approx(6.0)
        assert 0.15 <= U["u_splice"][1] <= 0.85


def test_hair_stain_and_flash_appear_with_full_frequency():
    v = damage_values(poeira_on=False, riscos_on=False, cabelo_on=True, cabelo=1.0, manchas_on=True, manchas=1.0,
                      queima_on=True, queima=1.0)
    frames = range(0, 24 * 60, 3)
    us = [plan(v, frame=f).uniforms for f in frames]
    assert any(u["u_hair"][0] > 0 for u in us)
    assert any(u["u_stain"][0] > 0 for u in us)
    assert any(max(u["u_gain"]) > 0.5 for u in us), "clarão de fim de rolo deveria subir a exposição"
    for u in us:
        if u["u_hair"][0] > 0 or u["u_stain"][0] > 0:
            assert u["u_dmg_on"] == 1


# ------------------------------------------------------------------ moldura e scan
@pytest.mark.parametrize("over, expected", [
    (dict(mold_on=False, proporcao="2.39"), 0.0),
    (dict(mold_on=True, proporcao="original"), 0.0),
    (dict(mold_on=True, proporcao="2.39"), 2.39),
    (dict(mold_on=True, proporcao="bitola", bitola="super8"), look.GAUGES["super8"]["aspect"]),
    (dict(mold_on=True, proporcao="bitola", bitola="nenhuma"), 0.0),
])
def test_aspect_target(over, expected):
    v = params.defaults()
    v.update(over)
    assert look.aspect_target(v, look.GAUGES[v["bitola"]]) == pytest.approx(expected)
    assert plan(v).uniforms["u_aspect_t"] == pytest.approx(expected)


def test_frame_mask_flag():
    assert plan(mold_on=True).uniforms["u_frame_on"] == 1
    assert plan(mold_on=False).uniforms["u_frame_on"] == 0


def test_scan_on_sets_scan_uniforms_and_disables_frame_mask():
    v = params.defaults()
    v.update(scan_on=True, mold_on=True, proporcao="2.39", hal_on=True)
    p = plan(v)
    U = p.uniforms
    assert U["u_scan_on"] == 1
    assert U["u_frame_on"] == 0
    for k in ("u_scan_view", "u_scan_img", "u_scan_perf", "u_scan_perf2", "u_scan_text", "u_scan_base",
              "u_scan_light", "u_scan_outside", "u_scan_textcol", "u_scan_rough", "u_scan_fill", "u_scan_neighbors"):
        assert k in U
    # halação usa a máscara alfa do quadro no scan
    assert p.chains[0].name == "hal" and p.chains[0].alpha_mask
    off = plan(v, scan_on=False)
    assert off.uniforms["u_scan_on"] == 0 and off.edge_text == "" and off.uniforms["u_frame_on"] == 1


def test_scan_zoom_and_type():
    v = params.defaults()
    v.update(scan_on=True, scan_formato="35mm")
    z1 = plan(v, scan_zoom=1.0).uniforms["u_scan_view"]
    z2 = plan(v, scan_zoom=1.6).uniforms["u_scan_view"]
    assert z2[2] < z1[2]
    assert z1[2] == pytest.approx(35.0 * 1.05)
    neg = plan(v, scan_tipo="negativo").uniforms
    pos = plan(v, scan_tipo="copia").uniforms
    assert max(neg["u_scan_light"]) < 0.01 < min(pos["u_scan_light"])
    assert plan(v, scan_luz=2.0).uniforms["u_scan_light"][0] == pytest.approx(2 * pos["u_scan_light"][0])
    assert plan(v, scan_ajuste="preencher").uniforms["u_scan_fill"] == 1
    assert plan(v, scan_vizinhos=False).uniforms["u_scan_neighbors"] == 0


@pytest.mark.parametrize("bitola, fmt", [("8mm", "super8"), ("super8", "super8"), ("16mm", "16mm"),
                                         ("super16", "super16"), ("35mm", "35mm"), ("65mm", "35mm"),
                                         ("imax", "35mm"), ("nenhuma", "35mm")])
def test_scan_format_follows_gauge(bitola, fmt):
    assert look.scan_format({"bitola": bitola, "scan_formato": "bitola"}) == fmt
    assert look.scan_format({"bitola": bitola, "scan_formato": "16mm"}) == "16mm"


@pytest.mark.parametrize("iso, code, name", [("50", "5203", "50D"), ("200", "5213", "200T"), ("250", "5207", "250D"),
                                             ("500", "5219", "500T"), ("3200", "5219", "500T")])
def test_edge_text_auto_depends_on_iso(iso, code, name):
    t = look.edge_text({"scan_texto": "auto", "bitola": "35mm", "scan_formato": "bitola", "iso": iso, "pb": False})
    assert t.startswith(f"KODAK  {code}  VISION3  {name}")


def test_edge_text_variants():
    base = {"scan_texto": "auto", "bitola": "35mm", "scan_formato": "bitola", "iso": "500", "pb": False}
    assert "5222" in look.edge_text({**base, "pb": True}) and "DOUBLE-X" in look.edge_text({**base, "pb": True})
    t16 = look.edge_text({**base, "bitola": "16mm"})
    assert t16.startswith("KODAK  7219  VISION3  500T")
    assert look.edge_text({**base, "bitola": "super8"}) == ""
    assert look.edge_text({**base, "scan_formato": "super16"}) == ""
    assert look.edge_text({**base, "scan_texto": "nenhum"}) == ""
    for key, txt in look.EDGE_TEXTS.items():
        assert look.edge_text({**base, "scan_texto": key}) == txt


def test_plan_edge_text_only_when_scanning():
    v = params.defaults()
    v.update(scan_on=True, iso="500")
    assert "500T" in plan(v).edge_text
    v["pb"] = True
    assert "DOUBLE-X" in plan(v).edge_text


# ------------------------------------------------------------------ desfoque da bitola
def test_gauge_blur_can_be_turned_off_and_scaled():
    v = presets.builtin_values("super8_kodachrome")
    assert v["bitola_desfoque_on"] is True and v["lente_on"] and v["maciez"] == 0 and v["nitidez"] == 0
    blur = look.GAUGES["super8"]["blur"]
    on = look.build_plan(v, 1920, 1080, 0, 24.0, None)
    assert on.soft_sigma == pytest.approx(blur)
    assert look.build_plan(v, 3840, 2160, 0, 24.0, None).soft_sigma == pytest.approx(blur * 2)  # px@1080
    half = look.build_plan({**v, "bitola_resolucao": 0.5}, 1920, 1080, 0, 24.0, None)
    assert half.soft_sigma == pytest.approx(blur / 2)
    off = look.build_plan({**v, "bitola_desfoque_on": False}, 1920, 1080, 0, 24.0, None)
    assert off.soft_sigma == 0.0 and off.uniforms.get("u_soft_on", 0) == 0


def test_gauge_blur_tip_matches_the_gauges():
    """A dica do "Desfoque da bitola" cita o desfoque de cada bitola; os números têm de bater com GAUGES."""
    tip = params.PARAMS["bitola_desfoque_on"].tip
    for key, label in (("8mm", "8 mm"), ("super8", "Super 8"), ("16mm", "16 mm"), ("super16", "Super 16"),
                       ("35mm", "35 mm")):
        value = f"{look.GAUGES[key]['blur']:g}".replace(".", ",")
        assert f"{label} {value} px" in tip, (label, value)
    assert look.GAUGES["65mm"]["blur"] == 0 and look.GAUGES["imax"]["blur"] == 0 and "IMAX nenhum" in tip
