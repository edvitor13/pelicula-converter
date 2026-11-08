"""1.9, pilha de efeitos do clipe (VFX, #68; ARQUITETURA §49). Sem GPU nem Qt.

Um efeito de clipe é uma lista de passos de GPU que roda **no espaço da textura do clipe**, entre a leitura (e o perfil
de câmera do clipe) e o `editshaders.CLIP`, que continua o mesmo: o `CLIP` amostra a saída da pilha no lugar da imagem
do clipe. `Engine._canvas` monta a pilha com `plan(ctx)` e a roda em `Engine._fx_stack`; a prévia, o "Salvar quadro", a
exportação e o terminal passam todos por aí (a receita única de `frame.py`).

- **Efeito** (`Effect`, registrado com `register`): id ASCII, o módulo dele (`modules.MODULES`, só para a interface e o
  aviso de `modules.used_by`; a renderização nunca consulta módulos), a ordem na pilha (`order`), `active(valores)`,
  `passes(ctx)` → `[Pass]`, `alpha(valores)` (o efeito recorta: a saída tem cobertura) e `radius(valores)` (quantos
  quadros vizinhos do arquivo ele lê, até `MAX_RADIUS`). Efeito inativo não gera passo nenhum: o quadro sai bit a bit
  o de antes. Ordem canônica (`ORDER`): recorte → máscara → tempo → desfoque de lente → listra/flare/raios → névoa →
  partículas.
- **Passo** (`Pass`): `kind="glsl"` (o código depois de `editshaders.FX_HEAD`: funções e `void main()`), `"blur"`
  (gaussiano separável, com mipmaps para raios grandes) ou `"streak"` (desfoque numa direção). Entradas por nome do
  sampler: `"prev"` (saída do passo anterior; no primeiro, a imagem do clipe), `"orig"` (a imagem do clipe antes dos
  efeitos), `"below"` (a tela embaixo do clipe, levada ao espaço do clipe por `fxBelow`), `"n-2"`…`"n+2"` (quadros
  vizinhos do arquivo, `LayerImage.neighbors`) e `"pass:<nome>"` (um passo anterior do mesmo efeito; também
  `"pass:<índice>"`). `t_prev`, `t_orig` e `t_below` vêm sempre.
- **Imagem nos passos**: RGBA de **cor direta e cobertura** (como a tela), nos valores que o `CLIP` lê (o código do
  vídeo ou, com perfil de câmera, a entrada do look). `fxDec`/`fxEnc` levam à luz linear da curva do look e de volta
  (`light`, a mesma das transições). No fim, `Engine` grava a textura que o `CLIP` amostra: pré-multiplicada (com a
  conta inversa das "pontas firmes" do `clipAlpha`) quando o clipe tem transparência ou um efeito recorta, opaca
  senão.
- **px@1080 no espaço do clipe**: `Ctx.px(v)` = `v × altura da textura / 1080` (no GLSL, `u_fx_scale`).
- **Tempo e sorte**: `Ctx.frame`/`Ctx.seconds` (`u_fx_frame`, `u_fx_time`) são o tempo do clipe das chaves
  (`Sequence.clip_time`): não mudam ao cortar ou aparar. Sorte só por hash de inteiros (`rnd`/`pcg` do GLSL) com a
  semente do ajuste e o quadro; nada de `random` ou `time`.
- **Geometria e janelas**: `GEOMETRY[id] = fn(seq, layer, M) -> M` muda a matriz tela → uv do clipe
  (`compositor.clip_uniforms`; a estabilização); `WINDOWS[id] = fn(seq, clip, t) -> [(quadro, peso)] | None` dá os
  quadros do arquivo misturados num quadro (`Sequence.frame_window`; a câmera lenta por mistura).
- **Camada de ajuste** (fonte do tipo `"ajuste"`, `is_adjustment`): a textura dela é a tela embaixo; a cor do clipe e
  a pilha valem para tudo o que está embaixo, no tempo dela.
- **Sem efeitos** (`neutral`: "Desligar todos os efeitos" e o "Original" da comparação): `plan` dá `[]`, a geometria
  dos provedores não vale e a camada de ajuste não desenha (decisão 4 do coordenador).
- **Análises** guardadas na fonte (`Source.analysis`, JSON `"analise"`): `pack`/`unpack` (numpy ↔ base64 compacto) e
  `stamp`/`stale` (o arquivo mudou depois da análise).
"""

from __future__ import annotations

import base64
import math
import os
import threading
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

# Ordem canônica na pilha (`Effect.order`): números com folga para encaixar efeitos novos sem mexer nos outros.
ORDER = {"recorte": 100, "mascara": 200, "tempo": 300, "desfoque_lente": 400, "luz": 500, "nevoa": 600,
         "particulas": 700}
MAX_RADIUS = 2                    # quadros vizinhos do arquivo: n−2 … n+2
ADJUSTMENT_KIND = "ajuste"        # `timeline.SOURCE_KINDS` (reservado desde a 1.5)
ADJUSTMENT_MODULE = "efeitos_clipe"
NEIGHBOR_REFS = {f"n{k:+d}": k for k in range(-MAX_RADIUS, MAX_RADIUS + 1) if k}  # "n-2" … "n+2"


# ------------------------------------------------------------------ passos e efeitos
@dataclass(frozen=True)
class Pass:
    """Um passo da pilha. `size`: "clip" (a textura do clipe), "canvas" (a tela), (largura, altura) em px ou um número
    (fração do clipe, ex.: 0.5). `dtype`: "f4" (padrão, sem perder os 16 bits) ou "f2" (intermediários leves, como
    máscaras e brilhos). `mip`: monta os mipmaps da saída (para `textureLod` num passo seguinte). `sigma` (blur e
    streak): em texels da entrada (use `Ctx.px` para px@1080); `angle` (streak): graus, 0 = horizontal, positivo
    gira no sentido horário da tela (y para baixo)."""
    name: str
    glsl: str = ""
    uniforms: dict = field(default_factory=dict)
    inputs: dict = field(default_factory=dict)
    size: Any = "clip"
    dtype: str = "f4"
    mip: bool = False
    kind: str = "glsl"
    sigma: float = 0.0
    angle: float = 0.0


def _never(_values: dict) -> bool:
    return False


def _zero(_values: dict) -> int:
    return 0


@dataclass(frozen=True)
class Effect:
    """Um efeito de clipe. `keys`: as chaves de ajuste dele (o aviso do módulo também olha as chaves de animação)."""
    id: str
    module: str
    order: int
    active: Callable[[dict], bool]
    passes: Callable[["Ctx"], list[Pass]]
    alpha: Callable[[dict], bool] = _never
    radius: Callable[[dict], int] = _zero
    keys: tuple[str, ...] = ()


EFFECTS: dict[str, Effect] = {}
# Módulos dos efeitos (`pelicula.<nome>`), um por frente: cada um chama `register` (e põe seus provedores em `GEOMETRY` e
# `WINDOWS`) ao ser importado. `load_effects` os importa antes do primeiro uso. Frente nova: **uma linha** aqui.
EFFECT_PACKAGES: tuple[str, ...] = (
    "recorte",  # 1.9 F2: recorte por cor ou brilho (§50)
)
_LOADED = False
_LOAD_LOCK = threading.Lock()
# módulo → ids dos efeitos dele (preenchido por `register`)
EFFECT_MODULES: dict[str, list[str]] = {}
# Provedores de geometria: id → fn(seq, layer, M) -> M, com M a matriz 3×3 (numpy) tela → uv do clipe. Aplicados na
# ordem do registro. Sem provedor (ou sem nada ativo no clipe) devolvem M como veio: os uniforms ficam os de antes.
GEOMETRY: dict[str, Callable[[Any, Any, np.ndarray], np.ndarray]] = {}
# Janelas de tempo: id → fn(seq, clip, t) -> [(quadro do arquivo, peso)] | None. A primeira que devolve uma janela vale
# (`Sequence.frame_window`); a mistura é a do obturador (`frame.Recipe._blend_layer`, na luz da curva do clipe).
WINDOWS: dict[str, Callable[[Any, Any, int], list[tuple[int, float]] | None]] = {}


def load_effects() -> None:
    """Importa os módulos de `EFFECT_PACKAGES` (uma vez; seguro entre threads)."""
    global _LOADED
    if _LOADED:
        return
    with _LOAD_LOCK:
        if _LOADED:
            return
        import importlib
        for name in EFFECT_PACKAGES:
            importlib.import_module(f"{__package__}.{name}")
        _LOADED = True


def register(effect: Effect) -> Effect:
    """Registra (ou troca) um efeito. Chame onde o recurso é importado; fica registrado com o módulo desligado."""
    old = EFFECTS.get(effect.id)
    if old is not None and effect.id in EFFECT_MODULES.get(old.module, []):
        EFFECT_MODULES[old.module].remove(effect.id)
    EFFECTS[effect.id] = effect
    EFFECT_MODULES.setdefault(effect.module, []).append(effect.id)
    return effect


def unregister(effect_id: str) -> None:
    """Tira um efeito do registro (os testes registram efeitos só deles)."""
    old = EFFECTS.pop(effect_id, None)
    if old is not None and effect_id in EFFECT_MODULES.get(old.module, []):
        EFFECT_MODULES[old.module].remove(effect_id)


def _ordered() -> list[Effect]:
    load_effects()
    return sorted(EFFECTS.values(), key=lambda e: (e.order, e.id))


def active_effects(values: dict | None) -> list[Effect]:
    """Os efeitos ligados com estes valores, na ordem da pilha."""
    v = values or {}
    return [e for e in _ordered() if e.active(v)]


def makes_alpha(values: dict | None) -> bool:
    """Algum efeito ligado recorta (a textura que o `CLIP` lê ganha cobertura)."""
    v = values or {}
    return any(e.alpha(v) for e in active_effects(v))


def neighbor_radius(values: dict | None) -> int:
    """Quantos quadros vizinhos do arquivo os efeitos ligados leem (0 = nenhum; no máximo `MAX_RADIUS`)."""
    v = values or {}
    return min(MAX_RADIUS, max([int(e.radius(v)) for e in active_effects(v)] + [0]))


# ------------------------------------------------------------------ camada de ajuste e módulos
def is_adjustment(seq, clip) -> bool:
    """O clipe é uma camada de ajuste (fonte do tipo "ajuste")."""
    src = seq.sources.get(clip.src) if seq is not None else None
    return src is not None and src.kind == ADJUSTMENT_KIND


def new_adjustment(seq):
    """Uma fonte de camada de ajuste do tamanho e do fps da sequência (sem fim, como uma imagem: entra com a duração
    padrão e estica à vontade). Media › Novo › "Camada de ajuste" (`ui/vfx_ui.py`)."""
    from .i18n import _
    from .timeline import Source
    return Source.virtual(ADJUSTMENT_KIND, seq.width, seq.height, seq.fps_str, None, {"nome": _("Camada de ajuste")},
                          alpha=False)


def modules_used(seq) -> set[str]:
    """Módulos dos efeitos visuais que esta montagem usa (`modules.used_by` passa por cada sequência do projeto): a
    camada de ajuste e os efeitos ligados (ou com chaves de animação) em algum clipe. Só para o aviso."""
    load_effects()
    used: set[str] = set()
    for c in getattr(seq, "clips", []) if seq is not None else []:
        if c.kind != "video":
            continue
        if is_adjustment(seq, c):
            used.add(ADJUSTMENT_MODULE)
        for e in list(EFFECTS.values()):
            if e.active(c.values) or any(k in c.keys for k in e.keys):
                used.add(e.module)
    return used


# ------------------------------------------------------------------ contexto de um clipe num quadro
@dataclass
class Ctx:
    """O que um efeito sabe ao montar os passos: a sequência, a camada (`timeline.Layer`, com os valores do quadro), o
    quadro `t` da sequência, o tamanho da textura do clipe e da tela, a luz (`transitions.light_of`) e se é uma camada de
    ajuste. `neutral`: "Desligar todos os efeitos" ou o "Original" da comparação."""
    seq: Any
    layer: Any
    t: int
    tex_w: int
    tex_h: int
    canvas_w: int
    canvas_h: int
    light: tuple[int, bool] | None = None
    adjustment: bool = False
    neutral: bool = False

    @property
    def clip(self):
        return self.layer.clip

    @property
    def values(self) -> dict:
        """Os ajustes neste quadro (com as chaves de animação avaliadas)."""
        return self.layer.values if self.layer.values is not None else self.layer.clip.values

    @property
    def src(self):
        return self.seq.sources.get(self.clip.src)

    @property
    def scale(self) -> float:
        """Texels do clipe por px@1080."""
        return self.tex_h / 1080.0

    def px(self, v: float) -> float:
        """Uma distância em px@1080 em texels da textura do clipe."""
        return float(v) * self.scale

    @property
    def frame(self) -> int:
        """Quadro do clipe no tempo das chaves (`Sequence.clip_time`): o mesmo depois de cortar ou aparar."""
        return int(round(self.seq.clip_time(self.clip, self.t)))

    @property
    def seconds(self) -> float:
        return self.seq.clip_time(self.clip, self.t) / self.seq.fps

    @property
    def fx(self) -> dict:
        """Os dados de efeito do clipe (`Clip.fx`, JSON "efeitos"): máscaras, rastros…"""
        return getattr(self.clip, "fx", None) or {}

    def analysis(self, kind: str) -> Any:
        """A análise `kind` guardada na fonte do clipe (`Source.analysis`), ou None."""
        src = self.src
        return (getattr(src, "analysis", None) or {}).get(kind) if src is not None else None

    @property
    def light_curve(self) -> tuple[int, bool]:
        from .transitions import REC709
        return tuple(self.light) if self.light is not None else REC709


def plan(ctx: Ctx) -> list[tuple[Effect, list[Pass]]]:
    """Os passos de cada efeito ligado, na ordem da pilha; [] sem efeitos (ou com `ctx.neutral`). Efeito que devolve
    lista vazia fica de fora."""
    if ctx.neutral:
        return []
    out = []
    for e in active_effects(ctx.values):
        passes = list(e.passes(ctx) or [])
        if passes:
            out.append((e, passes))
    return out


def pass_size(size: Any, ctx: Ctx) -> tuple[int, int]:
    """O tamanho em px da saída de um passo (`Pass.size`)."""
    if size == "clip":
        return int(ctx.tex_w), int(ctx.tex_h)
    if size == "canvas":
        return int(ctx.canvas_w), int(ctx.canvas_h)
    if isinstance(size, (int, float)) and not isinstance(size, bool):
        k = float(size)
        return max(1, int(round(ctx.tex_w * k))), max(1, int(round(ctx.tex_h * k)))
    w, h = size
    return max(1, int(w)), max(1, int(h))


def common_uniforms(ctx: Ctx, u_xf: tuple) -> dict[str, Any]:
    """Os uniforms `u_fx_*` de `editshaders.FX_HEAD` (menos `u_fx_size`, que é de cada passo). `u_xf`: a matriz tela →
    uv do clipe do `CLIP` (por coluna), já com a geometria e as transições: `u_fx_below` é a inversa, em uv da tela."""
    curve, cv = ctx.light_curve
    return {"u_fx_clip_px": (float(ctx.tex_w), float(ctx.tex_h)),
            "u_fx_canvas": (float(ctx.canvas_w), float(ctx.canvas_h)),
            "u_fx_scale": float(ctx.scale), "u_fx_below": below_matrix(u_xf, ctx.canvas_w, ctx.canvas_h),
            "u_fx_input": int(curve), "u_fx_cv": int(bool(cv)), "u_fx_frame": int(ctx.frame),
            "u_fx_time": float(ctx.seconds)}


def below_matrix(u_xf: tuple, canvas_w: int, canvas_h: int) -> tuple:
    """uv do clipe → uv da tela (a inversa de `u_xf`, que leva px da tela ao uv do clipe), por coluna para o GLSL."""
    m = np.array(u_xf, dtype=np.float64).reshape(3, 3).T
    try:
        inv = np.linalg.inv(m)
    except np.linalg.LinAlgError:
        inv = np.eye(3)
    out = np.diag([1.0 / max(1, canvas_w), 1.0 / max(1, canvas_h), 1.0]) @ inv
    return tuple(float(x) for x in out.T.flatten())


def streak_steps(sigma: float) -> list[float]:
    """Passos (em texels) do desfoque numa direção (`kind="streak"`): cada passo é uma gaussiana de 13 amostras com
    desvio de 2 passos; os passos crescem 3× e o último acerta o desvio total (as variâncias somam)."""
    var = float(sigma) ** 2
    out: list[float] = []
    s = 0.5
    while var > 1e-6 and len(out) < 12:
        k = min(s, math.sqrt(var) / 2.0)
        out.append(k)
        var -= (2.0 * k) ** 2
        s *= 3.0
    return out


# ------------------------------------------------------------------ geometria e janelas
def geometry(seq, layer, m: np.ndarray, canvas_w: int, canvas_h: int, neutral: bool = False) -> np.ndarray:
    """A matriz tela → uv do clipe com a geometria dos efeitos: a camada de ajuste lê a tela pixel a pixel (o cartão
    de enquadramento some na interface) e os provedores de `GEOMETRY` (estabilização) mexem no resto. Com `neutral`
    ("Desligar todos os efeitos"), só a camada de ajuste."""
    load_effects()
    if is_adjustment(seq, layer.clip):
        return np.array([[1.0 / canvas_w, 0.0, 0.0], [0.0, 1.0 / canvas_h, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    if neutral or not GEOMETRY:
        return m
    for fn in list(GEOMETRY.values()):
        m = fn(seq, layer, m)
    return m


def window(seq, clip, t: int) -> list[tuple[int, float]] | None:
    """A primeira janela de `WINDOWS` para o clipe no quadro t, ou None."""
    load_effects()
    for fn in list(WINDOWS.values()):
        got = fn(seq, clip, t)
        if got:
            return got
    return None


# ------------------------------------------------------------------ análises guardadas na fonte
_UNPACKED: dict[tuple, np.ndarray] = {}
_UNPACK_LOCK = threading.Lock()


def pack(arr: np.ndarray) -> dict[str, Any]:
    """Um array numpy em JSON compacto: {"tipo": dtype, "forma": [...], "dados": base64 do zlib dos bytes}. Use float32
    ou int16 (o projeto guarda isto). Os bytes vão em little-endian."""
    a = np.ascontiguousarray(arr)
    a = a.astype(a.dtype.newbyteorder("<"), copy=False)
    data = base64.b64encode(zlib.compress(a.tobytes(), 9)).decode("ascii")
    return {"tipo": a.dtype.str, "forma": list(a.shape), "dados": data}


def unpack(d: Any) -> np.ndarray | None:
    """O array de `pack` (só leitura; o mesmo objeto para o mesmo texto, sem decodificar de novo), ou None se `d` não é
    um pacote válido."""
    if not isinstance(d, dict) or not isinstance(d.get("dados"), str):
        return None
    key = (str(d.get("tipo")), str(d.get("forma")), d["dados"])
    with _UNPACK_LOCK:
        hit = _UNPACKED.get(key)
    if hit is not None:
        return hit
    try:
        raw = zlib.decompress(base64.b64decode(d["dados"].encode("ascii"), validate=True))
        arr = np.frombuffer(raw, dtype=np.dtype(str(d.get("tipo") or "<f4"))).reshape([int(x) for x in d["forma"]])
    except (ValueError, TypeError, KeyError, zlib.error):
        return None
    arr.setflags(write=False)
    with _UNPACK_LOCK:
        if len(_UNPACKED) > 64:
            _UNPACKED.clear()
        _UNPACKED[key] = arr
    return arr


def stamp(path: str) -> dict[str, Any]:
    """Carimbo do arquivo analisado ({"tamanho", "mtime"}): guarde junto da análise para avisar se ele mudou."""
    try:
        st = os.stat(path)
    except OSError:
        return {}
    return {"tamanho": int(st.st_size), "mtime": round(float(st.st_mtime), 3)}


def stale(src, kind: str) -> bool:
    """A análise `kind` da fonte foi feita com outro arquivo (o carimbo guardado não bate com o de agora). Sem carimbo
    guardado ou sem o arquivo, False (nada a avisar)."""
    entry = (getattr(src, "analysis", None) or {}).get(kind)
    if not isinstance(entry, dict) or not isinstance(entry.get("carimbo"), dict) or not entry["carimbo"]:
        return False
    now = stamp(src.path)
    return bool(now) and now != entry["carimbo"]
