"""Ajusta as curvas do Laboratório da 1.6 (M8) e as matrizes de corante (M6) aos pontos lidos dos datasheets.

Os pontos ficam em `pelicula/data/datasheets/<publicação>.json` (blocos `sensitometria` e `densidade_espectral`,
com a fonte: publicação, revisão, página, figura, SHA-256 do PDF lido e o método da leitura). Este script só usa
numpy e roda offline; o app usa as constantes já calculadas (`look.NEGATIVES`, `look.LAB_PRINTS` e
`labx.SCAN_WHITE`), e `tests/test_lab_datasheet.py` confere que elas são as deste ajuste.

    python tools/ajustar_lab.py        # mostra as constantes e os erros do ajuste

**Negativo.** A curva do modelo (`look.lab_curve`, duas softplus) de cada camada, depois do efeito entre camadas
(`interimage`, o mesmo do negativo feito à mão), mais a densidade mínima, é ajustada aos pontos de cada canal
(densidade Status M por stop de câmera; 0 stop = cartão cinza de 18%, log E relativo = stops · log10 2) por
Levenberg–Marquardt: gama, pé e ombro por camada e uma largura comum. A densidade mínima (base + véu + máscara)
fica fora do modelo (a densidade do modelo é acima da base).

**Cópia.** As três camadas recebem a mesma exposição (log E absoluto do gráfico); cada canal medido (Status A,
um densitômetro de bandas estreitas) é a densidade mínima mais as curvas das camadas vistas por bandas estreitas no
pico de cada corante (`densitometer`: a densidade de cada corante no pico dos outros). Ajusta-se gama, densidade
máxima e posição por camada e uma largura comum (a posição sai do modelo: a calibração do cinza a escolhe). O gama
fica limitado a `PRINT_GAMMA_MAX`: acima dele a curva do modelo vira uma logística e o ajuste não melhora.

**Matrizes de corante.** Cada canal de cor é a resposta Rec.709 do observador padrão CIE 1931 2° (ajuste
analítico de Wyman, Sloan e Shirley, JCGT 2013), só a parte positiva, sob uma luz branca de corpo negro
(`T_LUZ`). A absorção de cada camada k vista no canal c é `A_ck = ∫S_c·I·D_k / ∫S_c·I` (D_k = densidade espectral
do corante). Na cópia, a diafonia é `A` com cada coluna dividida pela diagonal (o canal da própria camada = 1).
No scan de luz branca do negativo (M6), cada canal recebe a mistura das transmitâncias das camadas, com pesos
proporcionais à absorção (`M = A` com cada linha somando 1): `T_c = Σ_k M_ck · 10^(−d_k)`.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "pelicula" / "data" / "datasheets"
LOG10_2 = math.log10(2.0)
T_LUZ = 5500.0                 # K: luz branca (projeção de xenônio, LED de scanner), corpo negro de aproximação
NM_STEP = 5.0
NM_RANGE = (400.0, 750.0)      # fora disto o observador quase não enxerga (e os gráficos acabam)

# Negativos calibrados: (publicação, id no app, matriz de sensibilidade e efeito entre camadas do negativo à mão).
NEG_FITS = (("H-1-5207", "vision3_250d_v2", "vision3_250d"),
            ("H-1-5219", "vision3_500t_v2", "vision3_500t"),
            ("H-1-5213", "vision3_200t_v2", "vision3_200t"))
PRINT_FITS = (("H-1-2383", "2383_v2"),)
PRINT_GAMMA_MAX = 6.0
# O erro máximo aceito em cada ajuste (densidade) fica no próprio JSON: `sensitometria.tolerancia_ajuste` (0,03 nos
# negativos; 0,10 na cópia, cujo pé longo a curva simétrica do modelo não segue).


def load(pub: str) -> dict:
    return json.loads((DATA / f"{pub}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ modelo (o mesmo de look.lab_curve)
def _softplus(z):
    return np.maximum(z, 0.0) + np.log1p(np.exp(-np.abs(z)))


def curve(x, gamma, toe, shoulder, width):
    return gamma * width * (_softplus((x - toe) / width) - _softplus((x - shoulder) / width))


def _lm(fun, p0, iters: int = 400) -> np.ndarray:
    """Levenberg–Marquardt com jacobiano numérico (mínimos quadrados de `fun(p)`)."""
    p = np.asarray(p0, dtype=np.float64).copy()
    r = fun(p)
    cost = float(r @ r)
    lam = 1e-3
    for _ in range(iters):
        J = np.empty((r.size, p.size))
        for i in range(p.size):
            h = 1e-6 * max(1.0, abs(p[i]))
            q = p.copy()
            q[i] += h
            J[:, i] = (fun(q) - r) / h
        A = J.T @ J
        g = J.T @ r
        done = False
        while True:
            step = np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-12), -g)
            q = p + step
            rq = fun(q)
            cq = float(rq @ rq)
            if np.isfinite(cq) and cq < cost:
                done = abs(cost - cq) < 1e-14 * max(cost, 1e-30)
                p, r, cost = q, rq, cq
                lam = max(lam / 3.0, 1e-12)
                break
            lam *= 4.0
            if lam > 1e12:
                return p
        if done:
            break
    return p


def _ii(interimage: float) -> np.ndarray:
    k = float(interimage)
    return np.eye(3) * (1.0 + k) - k / 3.0


# ------------------------------------------------------------------ negativo
def fit_negative(sens: dict, interimage: float) -> dict:
    stops = np.asarray(sens["stops"], dtype=np.float64)
    D = np.array([[np.nan if v is None else v for v in sens[c]] for c in "RGB"], dtype=np.float64)
    ok = np.isfinite(D)
    le = stops * LOG10_2
    ii = _ii(interimage)

    def model(p):
        g, t, s, w, dmin = p[0:3], p[3:6], p[6:9], p[9], p[10:13]
        f = curve(le[None, :], g[:, None], t[:, None], s[:, None], w)
        return dmin[:, None] + ii @ f

    def res(p):
        if p[9] <= 0.02:
            return np.full(int(ok.sum()), 1e3)
        return (model(p) - D)[ok]

    p0 = np.r_[[0.6] * 3, [-1.6] * 3, [2.0] * 3, 0.25, D[:, 0]]
    p = _lm(res, p0)
    err = np.abs(res(p))
    return dict(gamma=tuple(round(float(x), 3) for x in p[0:3]), toe=tuple(round(float(x), 3) for x in p[3:6]),
                shoulder=tuple(round(float(x), 3) for x in p[6:9]), width=round(float(p[9]), 3),
                dmin=tuple(round(float(x), 3) for x in p[10:13]),
                erro_max=round(float(err.max()), 4), erro_rms=round(float(np.sqrt(np.mean(err ** 2))), 4))


def negative_mid(sens: dict) -> tuple:
    """Densidade (com base) de cada canal no cartão cinza (0 stop), lida dos pontos."""
    stops = np.asarray(sens["stops"], dtype=np.float64)
    i = int(np.argmin(np.abs(stops)))
    return tuple(float(sens[c][i]) for c in "RGB")


# ------------------------------------------------------------------ cópia
def fit_print(sens: dict, dye: np.ndarray) -> dict:
    Ls, Ds, ch = [], [], []
    for i, c in enumerate("RGB"):
        Ls += sens[c]["log_e"]
        Ds += sens[c]["densidade"]
        ch += [i] * len(sens[c]["densidade"])
    L, D, ch = np.asarray(Ls), np.asarray(Ds), np.asarray(ch)

    def gam(u):
        return 1.0 + (PRINT_GAMMA_MAX - 1.0) / (1.0 + np.exp(-u))

    def model(p, L):
        g, t, dmax, w, dmin = gam(p[0:3]), p[3:6], p[6:9], p[9], p[10:13]
        dl = curve(L[None, :], g[:, None], t[:, None], (t + dmax / g)[:, None], w)
        return dmin[:, None] + dye @ dl

    def res(p):
        if p[9] <= 0.02 or np.any(p[6:9] <= 0.5):
            return np.full(L.size, 1e3)
        m = model(p, L)
        return m[ch, np.arange(L.size)] - D

    t0 = [float(np.interp(0.3, sens[c]["densidade"], sens[c]["log_e"])) for c in "RGB"]
    p0 = np.r_[[0.0] * 3, t0, [4.0] * 3, 0.2, [0.05] * 3]
    p = _lm(res, p0)
    err = np.abs(res(p))
    return dict(gamma=tuple(round(float(x), 3) for x in gam(p[0:3])), dmax=tuple(round(float(x), 3) for x in p[6:9]),
                width=round(float(p[9]), 3), dmin=tuple(round(float(x), 3) for x in p[10:13]),
                erro_max=round(float(err.max()), 4), erro_rms=round(float(np.sqrt(np.mean(err ** 2))), 4))


# ------------------------------------------------------------------ espectros
def _g(lam, mu, s1, s2):
    s = np.where(lam < mu, s1, s2)
    return np.exp(-0.5 * ((lam - mu) / s) ** 2)


def cie1931(lam) -> np.ndarray:
    """Observador padrão CIE 1931 2° pelo ajuste analítico de várias gaussianas (Wyman, Sloan e Shirley 2013)."""
    lam = np.asarray(lam, dtype=np.float64)
    x = 1.056 * _g(lam, 599.8, 37.9, 31.0) + 0.362 * _g(lam, 442.0, 16.0, 26.7) - 0.065 * _g(lam, 501.1, 20.4, 26.2)
    y = 0.821 * _g(lam, 568.8, 46.9, 40.5) + 0.286 * _g(lam, 530.9, 16.3, 31.1)
    z = 1.217 * _g(lam, 437.0, 11.8, 36.0) + 0.681 * _g(lam, 459.0, 26.0, 13.8)
    return np.stack([x, y, z], axis=-1)


XYZ_TO_709 = np.array([[3.2404542, -1.5371385, -0.4985314],
                       [-0.9692660, 1.8760108, 0.0415560],
                       [0.0556434, -0.2040259, 1.0572252]])


def planck(lam, T: float = T_LUZ) -> np.ndarray:
    lam = np.asarray(lam, dtype=np.float64)
    return lam ** -5.0 / np.expm1(1.4388e7 / (lam * T))


def channel_weights(lam) -> np.ndarray:
    """(n, 3) resposta R, G, B (Rec.709, parte positiva) vezes a luz branca."""
    rgb = cie1931(lam) @ XYZ_TO_709.T
    return np.maximum(rgb, 0.0) * planck(lam)[:, None]


def absorption(dens: dict) -> np.ndarray:
    """A[c, k]: densidade média do corante k (colunas: C, M, Y) vista pelo canal c (linhas: R, G, B)."""
    lam = np.arange(NM_RANGE[0], NM_RANGE[1] + 1e-9, NM_STEP)
    nm = np.asarray(dens["nm"], dtype=np.float64)
    Dk = np.stack([np.interp(lam, nm, np.asarray(dens[k], dtype=np.float64)) for k in "CMY"], axis=1)
    W = channel_weights(lam)
    return (W.T @ Dk) / W.sum(axis=0)[:, None]


def densitometer(dens: dict) -> np.ndarray:
    """Densitômetro de bandas estreitas (aproximação do Status A): cada canal lê no pico do corante dele."""
    nm = np.asarray(dens["nm"], dtype=np.float64)
    Dk = {k: np.asarray(dens[k], dtype=np.float64) for k in "CMY"}
    peak = {k: nm[int(np.argmax(Dk[k]))] for k in "CMY"}
    return np.array([[np.interp(peak[r], nm, Dk[k]) / Dk[k].max() for k in "CMY"] for r in "CMY"])


def print_dye(dens: dict) -> tuple:
    """Diafonia da cópia: cada coluna dividida pela diagonal (a camada no próprio canal = 1)."""
    A = absorption(dens)
    m = A / np.diag(A)[None, :]
    return tuple(tuple(round(float(x), 3) for x in row) for row in m)


def scan_mix(dens: dict) -> tuple:
    """Scanner de luz branca: pesos da transmitância de cada camada em cada canal (linhas somam 1)."""
    A = np.maximum(absorption(dens), 0.0)
    m = A / A.sum(axis=1, keepdims=True)
    m = np.round(m, 3)
    m[:, 0] = np.round(1.0 - m[:, 1] - m[:, 2], 3)  # cada linha soma exatamente 1 (cinza continua cinza)
    return tuple(tuple(float(x) for x in row) for row in m)


# ------------------------------------------------------------------ constantes do app
def constants() -> dict:
    sys.path.insert(0, str(ROOT))
    from pelicula import look  # só para reaproveitar o efeito entre camadas dos negativos feitos à mão

    out: dict = {"negativos": {}, "copias": {}}
    for pub, new_id, base in NEG_FITS:
        d = load(pub)
        fit = fit_negative(d["sensitometria"], look.NEGATIVES[base]["interimage"])
        fit["cinza"] = tuple(round(v, 3) for v in negative_mid(d["sensitometria"]))
        out["negativos"][new_id] = fit
    for pub, new_id in PRINT_FITS:
        d = load(pub)
        fit = fit_print(d["sensitometria"], densitometer(d["densidade_espectral"]))
        fit["dye"] = print_dye(d["densidade_espectral"])
        out["copias"][new_id] = fit
    neg = load("H-1-5207")
    out["scan_luz_branca"] = scan_mix(neg["densidade_espectral"])
    out["scan_dmin"] = out["negativos"]["vision3_250d_v2"]["dmin"]
    return out


def main() -> int:
    c = constants()
    for k, v in c["negativos"].items():
        print(f"{k}: {v}")
    for k, v in c["copias"].items():
        print(f"{k}: {v}")
    print(f"scan_luz_branca = {c['scan_luz_branca']}")
    print(f"scan_dmin = {c['scan_dmin']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
