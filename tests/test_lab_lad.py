"""Conferências do Laboratório pelo LAD da Kodak (M9 da 1.6): mede o modelo de sempre, sem mudar o visual.

O LAD (*Laboratory Aim Density*) é o método de controle dos laboratórios de cinema (Pytlak e Fleischer, SMPTE
Journal 85, 1976; publicações públicas da Kodak H-61, H-61A e H-61B, 1992):

- o cinza de 16% de refletância (Munsell N 4.5) vira no negativo a mancha do LAD, Status M R 0,80, G 1,20 e
  B 1,60 (H-61A), e na cópia 2383/2393 um cinza de **densidade visual 1,0** (Status A R 1,09, G 1,06, B 1,03;
  H-61B);
- 1 ponto da copiadora = 0,025 log E, que perto do alvo muda a cópia em **cerca de 0,07** de densidade (H-61B);
- ±7 pontos ≈ ±1 stop de câmera; 12 pontos = 0,30 log E = 1 stop da exposição da cópia; o TAPE padrão é
  25-25-25 (H-61);
- uma escala de cinza (2,5% a 90%) que sai com cor mudando ao longo dela é o sintoma de contraste descasado.

O que bate com o modelo vira teste com tolerância; o que não bate fica medido em `docs/ARQUITETURA.md` (§32.1)
— os filmes de sempre nunca mudam. As densidades do app são **acima da base** (a base limpa projeta o branco).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pelicula import look, params

W709 = np.array([0.2126, 0.7152, 0.0722])
LAD_GREY = 0.16                                               # Munsell N 4.5 (H-61A)
LAD_SCALE = (0.025, 0.031, 0.066, 0.10, 0.16, 0.20, 0.40, 0.79, 0.90)  # preto, escala de cinza, LAD, branco
VISION3 = ("vision3_50d", "vision3_250d", "vision3_200t", "vision3_500t")
COLOR_NEGS = [n for n in look.NEGATIVES if n != "double_x"]
COLOR_PRINTS = [p for p, t in look.LAB_PRINTS.items() if t is not None and p != "2302"]


def lab_values(**over) -> dict:
    v = params.defaults()
    v.update(lab_on=True, bitola="nenhuma", cor_on=False, copia="nenhuma")
    v.update(over)
    return params.sanitize(v)


def density(y) -> np.ndarray:
    """Densidade acima da base vista em cada canal: a projeção do app é 10^(−d/2,6)."""
    return -look.LAB_VIEW_GAMMA * np.log10(np.asarray(y, dtype=np.float64))


def grey(lin: float) -> np.ndarray:
    return np.full(3, float(lin))


def print_density(v: dict, lin: float) -> np.ndarray:
    return density(look.lab_eval(v, grey(lin)))


# ------------------------------------------------------------------ cópia: o LAD sai com densidade visual ≈ 1,0
@pytest.mark.parametrize("copia", ["2383", "2393"])
@pytest.mark.parametrize("neg", VISION3)
def test_lad_grey_prints_near_visual_density_one(neg, copia):
    d = print_density(lab_values(lab_negativo=neg, lab_copia=copia), LAD_GREY)
    visual = float(d @ W709)
    # Medido: 0,97–0,99 acima da base; o LAD é 1,0 com a base (a base da cópia fica em torno de 0,05).
    assert 0.95 < visual < 1.05, visual
    assert np.ptp(d) < 0.004  # quase neutro: o app calibra o cinza de 18% nos próprios canais (o Status A do LAD
    # não é neutro); a 16% sobra a virada de cor de cada filme (medido: até 0,0033 no 200T)


def test_mid_grey_target_is_the_lad_grey_seen_from_18_percent():
    # 18% é 0,051 log E mais claro que o LAD: sai ~0,07 menos denso (contraste da cópia × gama do negativo).
    v = lab_values()
    d18, d16 = print_density(v, 0.18), print_density(v, LAD_GREY)
    np.testing.assert_allclose(d18, look.LAB_TARGET_D, atol=1e-9)
    assert look.LAB_TARGET_D == pytest.approx(0.9017, abs=1e-4)
    assert 0.05 < float((d16 - d18).mean()) < 0.10


# ------------------------------------------------------------------ ponto da copiadora
def test_printer_point_is_0_025_log_e_and_twelve_points_are_one_print_stop():
    assert look.LAB_POINT == 0.025
    assert 12 * look.LAB_POINT == pytest.approx(math.log10(2.0), abs=0.002)  # 0,300 × 0,301


@pytest.mark.parametrize("copia", ["2383", "2393"])
def test_one_printer_point_changes_the_print_by_about_0_07(copia):
    v0 = lab_values(lab_copia=copia)
    v1 = lab_values(lab_copia=copia, lab_densidade=1.0)
    dd = print_density(v1, 0.18) - print_density(v0, 0.18)
    # LAD: ≈ 0,07. Medido: 0,059–0,060 na 2383 e 0,064 na 2393 (a reta da cópia do app é um pouco mais suave
    # perto do cinza; veja ARQUITETURA §32.1).
    assert np.ptp(dd) < 0.002
    assert 0.055 < float(dd.mean()) < 0.075


@pytest.mark.parametrize("copia", ["2383", "2393"])
@pytest.mark.parametrize("neg", VISION3)
def test_one_camera_stop_is_about_seven_printer_points(neg, copia):
    """+1 stop de câmera (o dobro da luz) volta ao cinza de antes com ≈ 7 pontos a mais na copiadora."""
    target = print_density(lab_values(lab_negativo=neg, lab_copia=copia), 0.18)[1]

    def err(points: float) -> float:
        v = lab_values(lab_negativo=neg, lab_copia=copia, lab_densidade=points)
        return float(print_density(v, 0.36)[1] - target)

    lo, hi = 0.0, 20.0
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if err(mid) < 0 else (lo, mid)
    assert 6.5 < lo < 8.0, lo  # medido: 7,0 (500T) a 7,5 (50D)


def test_tape_25_25_25_is_the_calibrated_neutral():
    """As luzes do app são relativas ao TAPE 25-25-25: com 0 pontos o cinza sai neutro, e as três luzes juntas
    (a *Densidade da cópia*) escurecem ou clareiam sem dar cor."""
    for neg in VISION3:
        base = print_density(lab_values(lab_negativo=neg), 0.18)
        np.testing.assert_allclose(base, base.mean(), atol=1e-6)
        for pts in (-7, 7):
            d = print_density(lab_values(lab_negativo=neg, lab_densidade=pts), 0.18)
            assert np.ptp(d) < 0.008  # medido: 0,003 (−7) e 0,006 (+7), a virada de cor do filme fora do cinza


# ------------------------------------------------------------------ escala de cinza (contraste descasado)
@pytest.mark.parametrize("copia", COLOR_PRINTS)
@pytest.mark.parametrize("neg", COLOR_NEGS)
def test_lad_grey_scale_has_no_strong_mismatched_contrast(neg, copia):
    """A escala de cinza do LAD (2,5% a 90%) sai quase neutra: o tom muda pouco do preto ao branco."""
    v = lab_values(lab_negativo=neg, lab_copia=copia)
    d = density(look.lab_eval(v, np.stack([np.asarray(LAD_SCALE)] * 3, axis=-1)))
    spread = np.ptp(d, axis=1)
    # Medido (§32.1): ≤ 0,0072 entre 16% e 20%; no preto de 2,5%, até ~0,07 nos Vision3 (sombras um pouco quentes
    # e altas luzes um pouco frias, a virada de cor de cada filme).
    assert spread[4] < 0.008 and spread[5] < 0.008
    # Os negativos antigos têm virada de propósito (5247 dos anos 70: até 0,14 no preto com a 2393); os modernos
    # (Vision3, Eterna) ficam abaixo de 0,08.
    limit = 0.08 if neg.startswith(("vision3", "eterna")) else 0.15
    assert spread.max() < limit, spread.round(3)


# ------------------------------------------------------------------ negativo (só medido)
def test_negative_lad_patch_is_recorded():
    """O negativo do app é densidade acima da base + véu (sem a máscara laranja): o LAD Status M menos a densidade
    mínima do 250D no datasheet dá ≈ R 0,62, G 0,62, B 0,75; o app tem ≈ 0,93/0,93/0,91 no 250D (o pé do negativo
    do app fica mais longe do cinza). Não muda nada na cópia (a calibração das luzes absorve), por isso só fica
    medido em §32.1 — este teste segura o número para a documentação não envelhecer."""
    a, _b = look.lab_paths_for(lab_values())
    le = math.log10(LAD_GREY / 0.18)
    dn = look.lab_curve(np.full(3, le), a.ng, a.nt, a.ns, a.nw) @ np.asarray(a.ii).T
    np.testing.assert_allclose(dn, [0.931, 0.931, 0.911], atol=0.005)
