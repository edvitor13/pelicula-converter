"""1.6: presets dos processos do Laboratório (slide reversível, revelação cruzada, película vencida, pré-exposição):
ficam no fim da lista (o índice dos antigos no plugin não muda), carregam com o processo certo e, pela cor no eixo
do cinza (LUT 17³), fazem o que a descrição promete em relação ao Vision3 250D → 2383 do laboratório."""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import params, presets

NEW = ["lab_slide_reversivel", "lab_cruzado_slide_c41", "lab_vencida_18_anos", "lab_flashing_suave"]
BASE = "lab_v3_250d_2383"


def test_new_presets_are_appended_after_the_old_ones():
    ids = [p["id"] for p in presets.BUILTIN]
    assert ids[-len(NEW):] == NEW
    assert ids.index("original") == len(ids) - len(NEW) - 1, "os antigos não mudam de posição"
    for pid in NEW:
        p = presets.BY_ID[pid]
        assert p["grupo"] == "Laboratório" and p["nome"] and p["desc"]


def test_new_presets_load_with_their_process():
    v = {pid: presets.builtin_values(pid) for pid in NEW}
    assert all(x["lab_on"] and not x["cor_on"] and x["copia"] == "nenhuma" for x in v.values())
    assert v["lab_slide_reversivel"]["lab_processo"] == "reversivel"
    assert v["lab_cruzado_slide_c41"]["lab_processo"] == "cruzado_e6c41"
    assert 15 <= v["lab_vencida_18_anos"]["lab_vencida"] <= 20
    f = v["lab_flashing_suave"]
    assert f["lab_pre_exposicao"] and f["lab_revelacao"] < 0
    for x in v.values():
        assert x == params.sanitize(x)


def _gray(engine, pid) -> np.ndarray:
    lut = engine.bake_lut(presets.builtin_values(pid), 17, False)
    lut = np.asarray(lut, dtype=np.float64).reshape(-1, 3)  # ordem do .cube: r mais rápido
    return lut[np.arange(17) * (1 + 17 + 17 * 17)]  # (17, 3): o eixo do cinza, do preto ao branco


@pytest.mark.gpu
def test_new_presets_do_what_they_say(gl_engine):
    base = _gray(gl_engine, BASE)
    g = {pid: _gray(gl_engine, pid) for pid in NEW}
    for pid, ramp in g.items():
        assert np.isfinite(ramp).all() and np.abs(ramp - base).max() > 0.02, pid
    mid = slice(5, 10)

    def slope(r):
        return float(np.mean(np.diff(r.mean(1))[mid]))

    assert slope(g["lab_slide_reversivel"]) > slope(base), "o slide tem mais contraste"
    assert slope(g["lab_flashing_suave"]) < slope(base), "a pré-exposição puxada tem menos contraste"
    assert g["lab_flashing_suave"][2].mean() > base[2].mean(), "as sombras sobem com o flashing"
    assert g["lab_vencida_18_anos"][2].mean() > base[2].mean(), "o véu da película vencida levanta as sombras"
    cast = g["lab_cruzado_slide_c41"] - g["lab_cruzado_slide_c41"].mean(1, keepdims=True)
    assert np.abs(cast[3] - cast[13]).max() > np.abs((base - base.mean(1, keepdims=True))[3]
                                                     - (base - base.mean(1, keepdims=True))[13]).max(), \
        "a revelação cruzada vira a cor entre sombras e altas luzes"
