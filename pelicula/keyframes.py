"""Chaves de animação (keyframes): ajustes que mudam no tempo. Puro (sem Qt nem GPU) e determinístico.

Uma **chave** é (tempo, valor, curva). Entre duas chaves o valor é interpolado com a curva da chave da
esquerda (a que "sai" para a próxima); antes da primeira e depois da última, vale a ponta. Curvas
(`EASINGS`, ids ASCII gravados nos projetos — nunca renomear):

- `linear` — velocidade constante;
- `suavizar_entrada` — começa devagar e acelera (s²);
- `suavizar_saida` — sai rápido e chega devagar (1 − (1 − s)²);
- `suavizar` — devagar nas duas pontas (3s² − 2s³).

Valores: números (`float`/`int`), cores [r, g, b] e rodas [x, y] são interpolados componente a componente;
escolhas e liga/desliga não têm meio-termo e mudam de degrau na chave (a curva não importa). Só ajustes
marcados com `Param.animatable` aceitam chaves (veja `animatable()`).

Onde fica o tempo de uma chave:

- **clipe do modo Edição** (`timeline.Clip.keys`): quadros da sequência medidos a partir da âncora do clipe,
  `τ = t − clip.start + clip.key_off` (`timeline.Sequence.clip_time`). Mover o clipe não mexe em nada; aparar
  o começo e dividir só somam um inteiro a `key_off` (a animação fica onde estava em relação à imagem, e as
  duas metades de um corte seguem exatamente como antes); mudar a velocidade ou o fps reescala os tempos
  (`rescale`), e a animação acompanha a imagem. A avaliação é uma só: `Sequence.values_at` →
  `Layer.values` (lida por `compositor.clip_uniforms`) e, para o volume, `audiomix` (com `ffmpeg_expr`, a
  mesma conta escrita para o ffmpeg).
- **look de película** (`look_values_at`): quadros do arquivo (modo Película) ou da montagem que entra no look,
  avaliados por quadro pela receita (`frame.Recipe.look_values`).

JSON (`to_json`/`from_json`): `{"chave_do_ajuste": [[tempo, valor], [tempo, valor, "curva"], …]}` — a curva só
aparece quando não é `linear`; tempos inteiros saem como inteiros.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, NamedTuple

from .i18n import N_

EASINGS = ("linear", "suavizar_entrada", "suavizar_saida", "suavizar")
EASING_LABELS: dict[str, str] = {"linear": N_("Linear"), "suavizar_entrada": N_("Suavizar entrada"),
                                 "suavizar_saida": N_("Suavizar saída"), "suavizar": N_("Suavizar")}
LINEAR = "linear"
NUMERIC_KINDS = ("float", "int")
LIST_KINDS = ("color", "wheel")
MAX_KEYS = 2000          # por ajuste (proteção contra arquivos quebrados)
TIME_LIMIT = 1e9         # |tempo| aceito (quadros)


class Key(NamedTuple):
    t: float            # tempo (quadros; veja o cabeçalho)
    v: Any              # valor já limpo pelo esquema do ajuste
    e: str = LINEAR     # curva até a próxima chave


# ------------------------------------------------------------------ curvas e interpolação
def ease(e: str, s: float) -> float:
    """Peso (0 a 1) da chave seguinte na fração `s` (0 a 1) do caminho, para a curva `e`."""
    s = min(max(float(s), 0.0), 1.0)
    if e == "suavizar_entrada":
        return s * s
    if e == "suavizar_saida":
        return 1.0 - (1.0 - s) * (1.0 - s)
    if e == "suavizar":
        return s * s * (3.0 - 2.0 * s)
    return s


def interpolable(kind: str) -> bool:
    return kind in NUMERIC_KINDS or kind in LIST_KINDS


def mix(kind: str, a: Any, b: Any, w: float) -> Any:
    """Valor entre `a` (w = 0) e `b` (w = 1) para um ajuste do tipo `kind`."""
    if kind == "float":
        return a + (b - a) * w
    if kind == "int":
        return int(round(a + (b - a) * w))
    if kind in LIST_KINDS:
        return [x + (y - x) * w for x, y in zip(a, b)]
    return b if w >= 1.0 else a  # escolhas e liga/desliga: degrau na chave seguinte


def value_at(keys: list[Key] | None, t: float, kind: str = "float", default: Any = None) -> Any:
    """O valor no tempo `t`. Sem chaves, `default`; antes da primeira e depois da última, a ponta."""
    if not keys:
        return default
    if t <= keys[0].t:
        return _copy(keys[0].v)
    if t >= keys[-1].t:
        return _copy(keys[-1].v)
    lo, hi = 0, len(keys) - 1
    while hi - lo > 1:  # busca binária: a última chave com tempo <= t
        mid = (lo + hi) // 2
        if keys[mid].t <= t:
            lo = mid
        else:
            hi = mid
    a, b = keys[lo], keys[lo + 1]
    if not interpolable(kind):
        return _copy(a.v)
    return mix(kind, a.v, b.v, ease(a.e, (t - a.t) / (b.t - a.t)))


def _copy(v: Any) -> Any:
    return list(v) if isinstance(v, (list, tuple)) else v


def max_value(keys: list[Key] | None, default: float) -> float:
    """Maior valor numérico que o ajuste chega a ter (as curvas ficam entre as chaves vizinhas)."""
    if not keys:
        return float(default)
    return max(float(k.v) for k in keys)


# ------------------------------------------------------------------ limpeza e JSON
def animatable(schema) -> dict[str, Any]:
    """Os ajustes do esquema que aceitam chaves (`Param.animatable`): {chave: Param}."""
    return {k: p for k, p in schema.params.items() if getattr(p, "animatable", False)}


def clean_track(p, raw: Any) -> list[Key]:
    """Chaves de um ajuste vindas de um arquivo: valores limpos pelo esquema, tempos finitos, em ordem e sem
    tempos repetidos (vale a última). Entradas inválidas são descartadas."""
    from .params import _clean
    out: dict[float, Key] = {}
    items = raw if isinstance(raw, (list, tuple)) else []
    for item in list(items)[:MAX_KEYS]:
        if isinstance(item, Key):
            item = list(item)
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            t = float(item[0])
            if not math.isfinite(t) or abs(t) > TIME_LIMIT:
                continue
            v = _clean(p, item[1])
        except (TypeError, ValueError):
            continue
        e = item[2] if len(item) > 2 and item[2] in EASINGS else LINEAR
        out[t] = Key(t, v, e)
    return [out[t] for t in sorted(out)]


def clean_keys(schema, raw: Any) -> dict[str, list[Key]]:
    """Todas as chaves de um clipe ou do look: só ajustes animáveis do esquema, sem trilhas vazias."""
    if not isinstance(raw, dict) or not raw:
        return {}
    allowed = animatable(schema)
    out = {}
    for k, track in raw.items():
        p = allowed.get(k)
        if p is None:
            continue
        keys = clean_track(p, track)
        if keys:
            out[k] = keys
    return out


def _num(t: float) -> float | int:
    return int(t) if float(t).is_integer() else float(t)


def to_json(keys: dict[str, list[Key]]) -> dict[str, list]:
    """JSON compacto: [tempo, valor] ou [tempo, valor, curva] (a curva só quando não é linear)."""
    out = {}
    for k in sorted(keys):
        rows = []
        for key in keys[k]:
            v = list(key.v) if isinstance(key.v, (list, tuple)) else key.v
            rows.append([_num(key.t), v] if key.e == LINEAR else [_num(key.t), v, key.e])
        if rows:
            out[k] = rows
    return out


def from_json(schema, d: Any) -> dict[str, list[Key]]:
    return clean_keys(schema, d)


# ------------------------------------------------------------------ edição (funções puras)
def set_key(keys: list[Key] | None, t: float, v: Any, e: str = LINEAR) -> list[Key]:
    """Chaves com (t, v, e) acrescentada ou trocada (mesmo tempo = mesma chave)."""
    e = e if e in EASINGS else LINEAR
    rest = [k for k in (keys or []) if k.t != t]
    return sorted(rest + [Key(float(t), v, e)], key=lambda k: k.t)


def remove_key(keys: list[Key] | None, t: float) -> list[Key]:
    return [k for k in (keys or []) if k.t != t]


def move_key(keys: list[Key] | None, t_from: float, t_to: float) -> list[Key]:
    """A chave em `t_from` vai para `t_to` (substitui a que estiver lá). Sem chave em `t_from`, nada muda."""
    found = [k for k in (keys or []) if k.t == t_from]
    if not found:
        return list(keys or [])
    k = found[0]
    rest = [x for x in (keys or []) if x.t not in (t_from, t_to)]
    return sorted(rest + [Key(float(t_to), k.v, k.e)], key=lambda x: x.t)


def move_keys(keys: list[Key] | None, moves: Iterable[tuple[float, float]]) -> list[Key]:
    """Várias chaves da mesma trilha andando juntas (arrastar uma seleção): [(de, para)]. A ordem evita que
    uma chave que ainda vai andar seja coberta por outra da própria seleção."""
    moves = list(moves)
    track = list(keys or [])
    for a, b in sorted(moves, key=lambda m: m[0], reverse=any(b > a for a, b in moves)):
        track = move_key(track, float(a), float(b))
    return track


def shift(keys: dict[str, list[Key]], delta: float) -> dict[str, list[Key]]:
    """Todos os tempos somados de `delta`."""
    return {k: [Key(x.t + delta, x.v, x.e) for x in track] for k, track in keys.items()}


def rescale(keys: dict[str, list[Key]], pivot: float, ratio: float) -> dict[str, list[Key]]:
    """Tempos esticados em volta de `pivot`: t → (t − pivot) × ratio. Velocidade e fps (o ponto `pivot` vira 0)."""
    return {k: [Key((x.t - pivot) * ratio, x.v, x.e) for x in track] for k, track in keys.items()}


# ------------------------------------------------------------------ avaliação
def values_at(schema, values: dict[str, Any], keys: dict[str, list[Key]] | None, t: float) -> dict[str, Any]:
    """Os ajustes no tempo `t`: os valores com cada ajuste animado trocado pelo valor das chaves.
    Sem chaves, devolve o próprio `values` (o mesmo objeto: nada muda)."""
    if not keys:
        return values
    out = dict(values)
    for k, track in keys.items():
        p = schema.params.get(k)
        if p is None or not track:
            continue
        out[k] = value_at(track, t, p.kind, values.get(k))
    return out


def look_values_at(values: dict[str, Any], keys: dict[str, list[Key]] | None, frame: float) -> dict[str, Any]:
    """Os ajustes do look de película no quadro `frame` (do arquivo ou da montagem que entra no look)."""
    if not keys:
        return values
    from . import params
    return values_at(params.FILM, values, keys, frame)


# ------------------------------------------------------------------ ffmpeg (volume do som)
def _f(x: float) -> str:
    return f"{float(x):.9g}"


def _ease_expr(e: str, s: str) -> str:
    if e == "suavizar_entrada":
        return f"({s})*({s})"
    if e == "suavizar_saida":
        return f"(1-(1-({s}))*(1-({s})))"
    if e == "suavizar":
        return f"({s})*({s})*(3-2*({s}))"
    return f"({s})"


def ffmpeg_expr(keys: list[Key], var: str) -> str:
    """A mesma conta de `value_at` (números) como expressão do ffmpeg na variável `var` (o tempo das chaves).
    Sem vírgulas fora de funções e sem dois-pontos: vai entre aspas simples no grafo de filtros."""
    if not keys:
        return "0"
    expr = _f(keys[-1].v)
    for a, b in reversed(list(zip(keys, keys[1:]))):
        s = f"({var}-{_f(a.t)})/{_f(b.t - a.t)}"
        seg = f"({_f(a.v)}+({_f(b.v)}-{_f(a.v)})*{_ease_expr(a.e, s)})"
        expr = f"if(lt({var},{_f(b.t)}),{seg},{expr})"
    return f"if(lt({var},{_f(keys[0].t)}),{_f(keys[0].v)},{expr})"


def keys_in(keys: dict[str, list[Key]], names: Iterable[str]) -> dict[str, list[Key]]:
    """Só as trilhas de `names`."""
    wanted = set(names)
    return {k: list(v) for k, v in keys.items() if k in wanted and v}
