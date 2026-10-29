"""Laboratório calibrado pelos datasheets (M8 da 1.6): os filmes "(datasheet)" são o ajuste de `tools/ajustar_lab.py`.

Os pontos lidos dos gráficos públicos da Kodak ficam em `pelicula/data/datasheets/` com a fonte (publicação,
revisão, página, figura, SHA-256 do PDF e o método da leitura) e com o erro máximo aceito no ajuste.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from pelicula import look, params

NEG_IDS = ("vision3_250d_v2", "vision3_500t_v2", "vision3_200t_v2")
PRINT_IDS = ("2383_v2",)
PUBS = ("H-1-5207", "H-1-5219", "H-1-5213", "H-1-2383")
W709 = np.array([0.2126, 0.7152, 0.0722])


def _tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "ajustar_lab.py"
    spec = importlib.util.spec_from_file_location("ajustar_lab", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fit():
    return _tool().constants()


def lab_values(**over) -> dict:
    v = params.defaults()
    v.update(lab_on=True, bitola="nenhuma", cor_on=False, copia="nenhuma")
    v.update(over)
    return params.sanitize(v)


# ------------------------------------------------------------------ fonte e pontos
@pytest.mark.parametrize("pub", PUBS)
def test_points_carry_their_source(pub):
    d = _tool().load(pub)
    assert d["publicacao"] == pub and d["revisao"] and len(d["sha256"]) == 64 and d["endereco"].startswith("https://")
    s = d["sensitometria"]
    assert s["pagina"] and s["figura"] and s["condicoes"] and s["unidade"]
    assert s["leitura"]["metodo"] and s["leitura"]["erro"] and 0 < s["tolerancia_ajuste"] <= 0.1
    if pub == "H-1-2383":
        for c in "RGB":
            assert len(s[c]["densidade"]) == len(s[c]["log_e"]) >= 30
    else:
        assert len(s["stops"]) == len(s["R"]) == len(s["G"]) == len(s["B"]) >= 60


@pytest.mark.parametrize("pub", ("H-1-5207", "H-1-2383"))
def test_dye_spectra_carry_their_source(pub):
    e = _tool().load(pub)["densidade_espectral"]
    assert e["pagina"] and e["figura"] and e["condicoes"] and e["leitura"]["metodo"] and e["leitura"]["erro"]
    assert len(e["nm"]) == len(e["Y"]) == len(e["M"]) == len(e["C"]) >= 30
    for k, lo, hi in (("Y", 430, 470), ("M", 530, 555), ("C", 640, 700)):  # picos dos corantes no lugar certo
        assert lo <= e["nm"][int(np.argmax(e[k]))] <= hi, k


# ------------------------------------------------------------------ ajuste
@pytest.mark.parametrize("neg_id", NEG_IDS)
def test_negative_constants_are_the_datasheet_fit(fit, neg_id):
    f, n = fit["negativos"][neg_id], look.NEGATIVES[neg_id]
    for k in ("gamma", "toe", "shoulder"):
        assert tuple(n[k]) == pytest.approx(f[k], abs=1e-9), k
    assert n["width"] == pytest.approx(f["width"], abs=1e-9)


@pytest.mark.parametrize("print_id", PRINT_IDS)
def test_print_constants_are_the_datasheet_fit(fit, print_id):
    f, p = fit["copias"][print_id], look.LAB_PRINTS[print_id]
    assert tuple(p["gamma"]) == pytest.approx(f["gamma"], abs=1e-9)
    assert tuple(p["dmax"]) == pytest.approx(f["dmax"], abs=1e-9)
    assert p["width"] == pytest.approx(f["width"], abs=1e-9)
    np.testing.assert_allclose(p["dye"], f["dye"], atol=1e-9)


def test_fit_errors_are_inside_the_recorded_tolerance(fit):
    tool = _tool()
    pubs = {"vision3_250d_v2": "H-1-5207", "vision3_500t_v2": "H-1-5219", "vision3_200t_v2": "H-1-5213"}
    for neg_id, pub in pubs.items():
        tol = tool.load(pub)["sensitometria"]["tolerancia_ajuste"]
        assert fit["negativos"][neg_id]["erro_max"] <= tol, neg_id  # medido: 0,018 a 0,019 (rms 0,006)
    tol = tool.load("H-1-2383")["sensitometria"]["tolerancia_ajuste"]
    assert fit["copias"]["2383_v2"]["erro_max"] <= tol               # medido: 0,083 (rms 0,021), no pé longo


def test_negative_fit_reads_the_datasheet_mid_grey(fit):
    """O modelo + densidade mínima passa pelo cinza lido (0 stop) dentro de 0,02 em cada canal."""
    for neg_id in NEG_IDS:
        f = fit["negativos"][neg_id]
        n = look.NEGATIVES[neg_id]
        k = n["interimage"]
        ii = np.eye(3) * (1 + k) - k / 3
        d = np.asarray(f["dmin"]) + ii @ look.lab_curve(np.zeros(3), n["gamma"], n["toe"], n["shoulder"], n["width"])
        np.testing.assert_allclose(d, f["cinza"], atol=0.02)


def test_dye_crosstalk_is_physical(fit):
    """Diafonia tirada dos espectros: diagonal 1, absorções indesejadas positivas e menores que a principal; o
    magenta é o corante mais impuro (absorve no vermelho e no azul)."""
    m = np.asarray(fit["copias"]["2383_v2"]["dye"])
    np.testing.assert_allclose(np.diag(m), 1.0)
    off = m[~np.eye(3, dtype=bool)]
    assert (off > 0).all() and (off < 0.4).all()
    assert m[0, 1] > m[0, 2] and m[2, 1] > m[2, 0]


# ------------------------------------------------------------------ no app
def test_new_ids_are_appended_at_the_end():
    """Ids novos só no fim (o plugin do Resolve guarda o índice da lista)."""
    negs = [k for k, _l in params.NEGATIVOS]
    prints = [k for k, _l in params.COPIAS_LAB]
    assert negs[-3:] == list(NEG_IDS) and negs[13] == "double_x"
    assert prints[-1] == "2383_v2" and prints[-2] == "nenhuma"
    assert list(look.NEGATIVES)[-3:] == list(NEG_IDS) and list(look.LAB_PRINTS)[-1] == "2383_v2"
    labels = dict(params.NEGATIVOS) | dict(params.COPIAS_LAB)
    for k in NEG_IDS + PRINT_IDS:
        assert labels[k].endswith("(datasheet)")


@pytest.mark.parametrize("neg_id", NEG_IDS)
def test_datasheet_pair_keeps_grey_and_grey_scale(neg_id):
    """Negativo e cópia do datasheet juntos: cinza médio calibrado e escala de cinza do LAD com pouca virada
    (medido: até 0,03 no vermelho e 0,125 no azul no preto de 2,5%, o pé longo do azul da 2383)."""
    v = lab_values(lab_negativo=neg_id, lab_copia="2383_v2")
    np.testing.assert_allclose(look.lab_eval(v, np.full(3, 0.18)), 0.45, atol=1e-6)
    scale = np.asarray((0.025, 0.031, 0.066, 0.10, 0.16, 0.20, 0.40, 0.79, 0.90))
    d = -2.6 * np.log10(np.maximum(look.lab_eval(v, np.stack([scale] * 3, axis=-1)), 1e-6))
    spread = np.ptp(d, axis=1)
    assert spread[4] < 0.012 and spread[5] < 0.012
    assert spread.max() < 0.14, spread.round(3)


def test_datasheet_negative_is_softer_in_red_like_the_datasheet():
    """No Status M o vermelho do Vision3 tem menos gama que o verde e o azul (≈ 0,49 contra 0,55)."""
    for neg_id in NEG_IDS:
        g = look.NEGATIVES[neg_id]["gamma"]
        assert g[0] < g[1] - 0.04 and g[0] < g[2] - 0.03
