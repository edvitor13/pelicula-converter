"""Fotômetro da película (1.6, módulo Beta "fotometro"): onde a cena cai na curva do negativo escolhido.

Só para a tela, como a zebra e a falsa cor (`exposure.py`): a camada da prévia (`ui/fotometro_ui.py`) e a leitura
de um ponto. A receita do quadro e a exportação não sabem que isto existe.

**O negativo.** O mesmo modelo do Laboratório (`look.lab_paths_for` → `LabPath` do caminho A: o negativo escolhido com
a revelação forçada/puxada, a película vencida e a pré-exposição já aplicadas às curvas e à exposição somada
`add`). Com um processo especial (reversível, cruzado, Technicolor) de força ≥ 50%, mede o filme do processo
(caminho B), que é quem decide a latitude da imagem; no reversível, sem negativo, a imagem final do caminho. Sem o Laboratório ligado, o negativo padrão (`params.defaults()`: Vision3 250D, revelação normal) — a
interface diz isso. Nada aqui muda o Laboratório.

**Contraste da cena no negativo.** Cada camada `k` tem a curva `D(x) = g·w·[sp((x − pé)/w) − sp((x − ombro)/w)]` com
`x = log10(e/0,18)` e `e = luz da cena + add` (no eixo do cinza, `sens · (E, E, E) = E`: as linhas somam 1). Quanto o
negativo separa dois tons vizinhos da **cena** é a inclinação em relação ao log da exposição da cena:

    dD/d(log E) = g · [σ((x − pé)/w) − σ((x − ombro)/w)] · E / (E + add)

e o "contraste relativo" é isso dividido pela gama `g` da própria camada (1 no trecho reto). O fator `E/(E + add)` é
o que a pré-exposição e o véu da película vencida fazem: a luz somada levanta a densidade das sombras, mas tons
vizinhos da cena ficam mais parecidos no negativo (as sombras "enchem" e perdem contraste).

**Zonas** (em stops da cena em relação ao cinza de 18%, no eixo do cinza; a camada mais estreita manda):

- **reta**: contraste relativo ≥ `LINE` (50%): detalhe completo;
- **pé** / **ombro**: entre `DETAIL` (10%) e 50%: sombras ou altas luzes comprimidas, ainda com algum detalhe;
- **sem detalhe** / **estourado**: abaixo de 10% (o negativo quase não separa mais os tons).

Num negativo sem forçar e sem luz somada, o limite de 50% é o próprio pé (σ(0) = ½) e o próprio ombro de cada camada:
o Vision3 250D vai de −5,1 a +6,5 stops (o azul, a camada mais estreita; o verde e o vermelho de −5,3 a +6,6), o
Double-X de −4,7 a +6,0. Forçar 1 stop sobe o pé 0,08 log E (+0,27 stop: −4,9); puxar 1 stop desce (−5,4). A
película vencida tira sensibilidade (pé e ombro sobem, mais no azul) e soma o véu: 20 anos dão −3,3 a +7,1. A
pré-exposição sobe o limite de 50% das sombras (elas ficam mais lisas: a 4 stops abaixo do cinza, −3,8) e não tira
o detalhe fraco: o limite de 10% fica onde estava (−6,9) ou desce (a 6 stops, −7,5).

- `latitude(valores)`: `Latitude` com os quatro limites (e os de cada camada).
- `stops(luz)`: a exposição da cena em stops (a mesma de `exposure.stops`: luminância Rec.709 / 0,18).
- `zone_of(stop, lat)`, `false_color(stops, lat, cobertura)`: a camada RGBA da prévia.
- `spot(luz_rgb, valores)`: a leitura de um ponto (`Reading`), com a posição de cada camada.
- `latitude_text`, `spot_text`: os textos da interface (PT-BR, vírgula decimal).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .i18n import N_

GRAY = 0.18
LOG10_2 = math.log10(2.0)
LINE = 0.5       # contraste relativo da fronteira reta ↔ pé/ombro
DETAIL = 0.1     # abaixo disto, sem detalhe (ou estourado)
GRID = np.arange(-16.0, 16.0 + 1e-9, 0.005)  # stops da cena varridos para achar os limites

# (id, cor RGB, nome). A reta fica em cinza pela própria exposição; o cinza de 18% em verde, como na falsa cor.
ZONES: tuple[tuple[str, tuple[float, float, float] | None, str], ...] = (
    ("sem_detalhe", (0.42, 0.16, 0.62), N_("Sem detalhe: abaixo do pé do negativo")),
    ("pe", (0.12, 0.40, 0.95), N_("Pé: sombras comprimidas")),
    ("reta", None, N_("Trecho reto: detalhe completo")),
    ("ombro", (0.98, 0.62, 0.12), N_("Ombro: altas luzes comprimidas")),
    ("estourado", (0.92, 0.15, 0.12), N_("Estourado: além do ombro do negativo")),
)
ZONE_IDS = tuple(z[0] for z in ZONES)
SHORT = {"sem_detalhe": N_("sem detalhe"), "pe": N_("pé"), "reta": N_("reta"), "ombro": N_("ombro"),
         "estourado": N_("estourado")}
GRAY_BAND = 0.25           # ± stops do cinza de 18% mostrado em verde dentro da reta
GRAY_COLOR = (0.20, 0.78, 0.30)


@dataclass(frozen=True)
class Latitude:
    """Limites do negativo em stops da cena (0 = cinza de 18%). `lo`/`hi`: onde a reta começa e termina (50%);
    `lo_detail`/`hi_detail`: onde o detalhe acaba (10%). `layers`: os quatro de cada camada (R, G, B)."""
    lo: float
    hi: float
    lo_detail: float
    hi_detail: float
    layers: tuple
    negative: str
    default: bool   # True = o Laboratório está desligado e vale o negativo padrão


@dataclass(frozen=True)
class Reading:
    """Leitura de um ponto: exposição em stops da cena, a zona, quanto falta até o pé (50%) e até o ombro (50%), e
    para cada camada (stops na própria camada, zona)."""
    stops: float
    zone: str
    above_toe: float
    below_shoulder: float
    layers: tuple


def negative_values(v: dict | None) -> tuple[dict, bool]:
    """Os ajustes do Laboratório que o fotômetro usa: os do look, ou o padrão sem o Laboratório (True)."""
    from . import params
    if v and v.get("lab_on"):
        return v, False
    base = params.defaults()
    return base, True


def uses_process(v: dict) -> bool:
    """True quando um processo especial (reversível, cruzado, Technicolor) domina a mistura (força ≥ 50%): aí quem
    decide a latitude é o filme do processo (caminho B), não o negativo escolhido."""
    from . import look
    return look.lab_paths_for(v)[1] is not None and float(v.get("lab_processo_forca", 0.0)) >= 0.5


def negative_path(v: dict | None):
    """O filme medido: o caminho A do Laboratório (o negativo escolhido, já com revelação, idade e pré-exposição)
    ou, com um processo especial dominante (`uses_process`), o caminho B (o filme do processo)."""
    from . import look
    vals, _default = negative_values(v)
    a, b = look.lab_paths_for(vals)
    return b if uses_process(vals) else a


def _whole_path(path) -> bool:
    """Caminho sem negativo de verdade (o estágio do negativo é linear, como no reversível): o filme é a imagem final."""
    return float(np.min(path.nt)) <= -5.0 and float(np.max(path.ns)) >= 5.0


def relative_slope(path, stops) -> np.ndarray:
    """Contraste relativo de cada camada (… × 3) para exposições da cena em stops, no eixo do cinza.

    No reversível (`_whole_path`) não há negativo: mede a imagem final do caminho (`path.eval`, sem luzes), a
    inclinação do valor de exibição por stop dividida pela maior inclinação da própria camada."""
    if _whole_path(path):
        s = np.asarray(stops, dtype=np.float64)
        E = GRAY * 2.0 ** s
        y = np.asarray(path.eval(np.repeat(E[:, None], 3, axis=1), (0.0, 0.0, 0.0)), dtype=np.float64)
        d = np.gradient(y, s, axis=0)
        return np.clip(d / np.maximum(d.max(axis=0, keepdims=True), 1e-12), 0.0, None)
    s = np.asarray(stops, dtype=np.float64)[..., None]
    E = GRAY * 2.0 ** s
    add = np.asarray(path.add, dtype=np.float64)
    e = np.maximum(E + add, 1e-12)
    x = np.log10(e / GRAY)
    nt, ns, nw = np.asarray(path.nt), np.asarray(path.ns), float(path.nw)

    def sig(z):
        return 0.5 * (1.0 + np.tanh(0.5 * z))

    return (sig((x - nt) / nw) - sig((x - ns) / nw)) * (E / e)


def _limits(rel: np.ndarray, thr: float) -> tuple[float, float]:
    idx = np.nonzero(rel >= thr)[0]
    if len(idx) == 0:
        return 0.0, 0.0
    return float(GRID[idx[0]]), float(GRID[idx[-1]])


@lru_cache(maxsize=64)
def _latitude_of(path) -> tuple:
    rel = relative_slope(path, GRID)
    out = []
    for k in range(3):
        lo, hi = _limits(rel[:, k], LINE)
        lod, hid = _limits(rel[:, k], DETAIL)
        out.append((round(lo, 3), round(hi, 3), round(lod, 3), round(hid, 3)))
    return tuple(out)


def latitude(v: dict | None) -> Latitude:
    """A latitude do negativo dos ajustes `v` (a camada mais estreita em cada ponta)."""
    vals, default = negative_values(v)
    layers = _latitude_of(negative_path(vals))
    film = ("processo:" + str(vals.get("lab_processo", ""))) if uses_process(vals) else str(vals.get("lab_negativo", ""))
    return Latitude(max(x[0] for x in layers), min(x[1] for x in layers), max(x[2] for x in layers),
                    min(x[3] for x in layers), layers, film, default)


def stops(lin) -> np.ndarray:
    """Exposição da cena em stops (luminância Rec.709 / 0,18), a mesma de `exposure.stops`."""
    from . import exposure
    return exposure.stops(lin)


def zone_index(st, lat: Latitude) -> np.ndarray:
    """Índice em `ZONES` de cada exposição (stops da cena)."""
    st = np.asarray(st, dtype=np.float64)
    z = np.full(st.shape, 2, dtype=np.int8)
    z[st < lat.lo] = 1
    z[st < lat.lo_detail] = 0
    z[st > lat.hi] = 3
    z[st > lat.hi_detail] = 4
    return z


def zone_of(stop: float, lat: Latitude) -> str:
    return ZONE_IDS[int(zone_index(np.asarray([stop]), lat)[0])]


def false_color(st, lat: Latitude, cover=None) -> np.ndarray:
    """RGBA (… × 4): as zonas de `ZONES` em cor, a reta em cinza pela exposição e o cinza de 18% em verde."""
    st = np.asarray(st, dtype=np.float64)
    z = zone_index(st, lat)
    span = max(lat.hi - lat.lo, 1e-6)
    g = np.clip((st - lat.lo) / span, 0.0, 1.0) * 0.7 + 0.15
    rgb = np.repeat(g[..., None], 3, axis=-1)
    for i, (_zid, color, _name) in enumerate(ZONES):
        if color is not None:
            rgb[z == i] = color
    rgb[(z == 2) & (np.abs(st) <= GRAY_BAND)] = GRAY_COLOR
    a = np.ones(st.shape) if cover is None else np.clip(np.asarray(cover, dtype=np.float64), 0.0, 1.0)
    return np.concatenate([rgb, a[..., None]], axis=-1)


def spot(lin_rgb, v: dict | None) -> Reading:
    """Leitura de um ponto (luz linear Rec.709 da cena, 3 valores)."""
    lin = np.asarray(lin_rgb, dtype=np.float64).reshape(3)
    lat = latitude(v)
    s = float(stops(lin[None, :])[0])
    path = negative_path(v)
    e = np.asarray(path.sens) @ lin
    layers = []
    for k in range(3):
        sk = float(np.log2(max(e[k], 1e-9) / GRAY))
        lo, hi, lod, hid = lat.layers[k]
        one = Latitude(lo, hi, lod, hid, (), lat.negative, lat.default)
        layers.append((sk, zone_of(sk, one)))
    return Reading(s, zone_of(s, lat), s - lat.lo, lat.hi - s, tuple(layers))


# ------------------------------------------------------------------ textos
def _num(x: float, decimals: int = 1) -> str:
    from .i18n import fmt_decimal
    return fmt_decimal(abs(x), decimals)


def signed(x: float, decimals: int = 1) -> str:
    """"+2,3" / "−1,5" / "0,0" (sinal de menos de verdade)."""
    r = round(float(x), decimals)
    if r == 0:
        return _num(0.0, decimals)
    return ("+" if r > 0 else "−") + _num(r, decimals)


def negative_name(neg: str) -> str:
    """Nome do filme medido: o negativo (`Latitude.negative`) ou, com o prefixo "processo:", o processo."""
    from . import params
    from .i18n import _
    if neg.startswith("processo:"):
        neg = neg[len("processo:"):]
        return _(dict(params.PARAMS["lab_processo"].choices).get(neg, neg))
    labels = dict(params.PARAMS["lab_negativo"].choices)
    return _(labels.get(neg, neg))


def latitude_text(lat: Latitude) -> str:
    from .i18n import _
    return _("{a} a {b} stops").format(a=signed(lat.lo), b=signed(lat.hi))


def zone_name(zid: str) -> str:
    from .i18n import _
    return next(_(name) for z, _c, name in ZONES if z == zid)


def spot_text(r: Reading) -> str:
    from .i18n import _
    head = _("{s} stops do cinza de 18% · {zona}").format(s=signed(r.stops), zona=zone_name(r.zone))
    if r.zone == "reta":
        head += " · " + _("{a} stops acima do pé, {b} abaixo do ombro").format(a=_num(r.above_toe),
                                                                               b=_num(r.below_shoulder))
    elif r.zone in ("pe", "sem_detalhe"):
        head += " · " + _("{a} stops abaixo da reta").format(a=_num(r.above_toe))
    else:
        head += " · " + _("{b} stops acima da reta").format(b=_num(r.below_shoulder))
    names = (_("R"), _("G"), _("B"))
    odd = [f"{n} {_(SHORT[z])}" for n, (_s, z) in zip(names, r.layers) if z != r.zone]
    if odd:
        head += " · " + _("camadas: {lista}").format(lista=", ".join(odd))
    return head
