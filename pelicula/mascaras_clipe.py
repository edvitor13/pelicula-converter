"""1.9, máscara de forma do clipe (#68, ARQUITETURA §50). Sem GPU nem Qt.

Um efeito da pilha de clipe (`vfx.py`, ordem "mascara": logo depois do recorte), módulo Beta `recorte_mascaras`. Uma
máscara por clipe: retângulo, elipse ou polígono (até `MAX_POINTS` pontos), **no espaço do clipe**: acompanha o
enquadramento, a rotação e o espelhamento do clipe (e a estabilização, que mexe na mesma matriz). Os ajustes ficam na
seção "mascara" de `editparams` (bloco `# 1.9 F2`); `mascara_forma = "nenhuma"` (o padrão) não gera passo nenhum.

- **Coordenadas**: px@1080 do clipe a partir do centro da imagem do clipe, y para baixo (`clip_px`/`clip_uv`). O
  centro da forma é (`mascara_x`, `mascara_y`) e a rotação `mascara_rotacao` (graus, positivo = sentido horário na
  tela). Retângulo e elipse: `mascara_largura` × `mascara_altura`. Polígono: os pontos de `Clip.fx["mascara"]["pontos"]`
  (JSON `"efeitos"`, `[[x, y], …]`), relativos ao centro e antes da rotação: animar o centro e a rotação move o
  polígono inteiro (um rastreio pode levar a forma junto).
- **Distância com sinal** (`distance`, GLSL `mkDist`): exata no retângulo e no polígono (a de Inigo Quilez, MIT),
  aproximada na elipse (`k0·(k0 − 1)/k1`, exata na borda). `mascara_expandir` desloca a borda; `mascara_suavidade` é a
  largura da passagem, centrada na borda (no mínimo um texel do clipe); `mascara_inverter` troca dentro e fora.
- **Uso** (`mascara_uso`): "recortar" multiplica a cobertura do clipe pela máscara (`Effect.alpha`: as faixas de baixo
  aparecem fora); "desfocar" mistura com o clipe desfocado (σ = `mascara_forca` px@1080) e "pixelar" com quadradinhos
  de `mascara_forca` px@1080 (a média de cada um pelos mipmaps, grade presa ao centro da forma) só dentro.

**Para as outras frentes** (o desfoque de lente da F4 dentro ou fora da forma, o rastreio da F3 levando o centro): o
GLSL `GLSL` (inclua depois do `FX_HEAD`; `mkMask(uv)` = 1 dentro) e `uniforms(ctx)` (None sem forma) servem qualquer
passo; o centro da forma são os ajustes animáveis `mascara_x`/`mascara_y` (px@1080 do clipe).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from . import vfx

MODULE = "recorte_mascaras"
EFFECT_ID = "mascara"
FX_KEY = "mascara"          # `Clip.fx[FX_KEY]` = {"pontos": [[x, y], …]}
POINTS_KEY = "pontos"
MAX_POINTS = 32
SHAPES = {"retangulo": 1, "elipse": 2, "poligono": 3}
USES = ("recortar", "desfocar", "pixelar")
KEYS = ("mascara_forma", "mascara_x", "mascara_y", "mascara_largura", "mascara_altura", "mascara_rotacao",
        "mascara_suavidade", "mascara_expandir", "mascara_inverter", "mascara_uso", "mascara_forca")

GLSL = """
// ---------------------------------------------------------------- máscara de forma do clipe (mascaras_clipe.py)
uniform int u_mk_shape;       // 1 retângulo, 2 elipse, 3 polígono
uniform vec2 u_mk_center;     // px@1080 do clipe, a partir do centro (y para baixo)
uniform vec2 u_mk_half;       // meia largura e meia altura (px@1080)
uniform float u_mk_rot;       // radianos, positivo = sentido horário na tela
uniform float u_mk_soft;      // largura da passagem (px@1080, no mínimo um texel)
uniform float u_mk_grow;      // expandir (px@1080)
uniform int u_mk_invert;
uniform int u_mk_n;           // pontos do polígono
uniform vec2 u_mk_pts[%(n)d];  // relativos ao centro, antes da rotação (px@1080)

float mkPoly(vec2 p) {
    float d = dot(p - u_mk_pts[0], p - u_mk_pts[0]);
    float s = 1.0;
    for (int i = 0; i < %(n)d; i++) {
        if (i >= u_mk_n) break;
        int j = i == 0 ? u_mk_n - 1 : i - 1;
        vec2 vi = u_mk_pts[i];
        vec2 vj = u_mk_pts[j];
        vec2 e = vj - vi;
        vec2 w = p - vi;
        vec2 b = w - e * clamp(dot(w, e) / max(dot(e, e), 1e-12), 0.0, 1.0);
        d = min(d, dot(b, b));
        bool c1 = p.y >= vi.y;
        bool c2 = p.y < vj.y;
        bool c3 = e.x * w.y > e.y * w.x;
        if ((c1 && c2 && c3) || (!c1 && !c2 && !c3)) s = -s;
    }
    return s * sqrt(d);
}
float mkDist(vec2 q) {
    if (u_mk_shape == 1) {
        vec2 a = abs(q) - u_mk_half;
        return length(max(a, 0.0)) + min(max(a.x, a.y), 0.0);
    }
    if (u_mk_shape == 2) {
        vec2 r = max(u_mk_half, vec2(1e-3));
        float k1 = length(q / (r * r));
        if (k1 < 1e-9) return -min(r.x, r.y);
        float k0 = length(q / r);
        return k0 * (k0 - 1.0) / k1;
    }
    return mkPoly(q);
}
// px@1080 do clipe (a partir do centro) de um uv do clipe
vec2 mkPoint(vec2 uv) { return (uv - 0.5) * u_fx_clip_px / u_fx_scale; }
// 1 dentro da forma, 0 fora (com a passagem e o inverter)
float mkMask(vec2 uv) {
    vec2 d = mkPoint(uv) - u_mk_center;
    float c = cos(u_mk_rot);
    float s = sin(u_mk_rot);
    vec2 q = vec2(c * d.x + s * d.y, -s * d.x + c * d.y);
    float sd = mkDist(q) - u_mk_grow;
    float m = 1.0 - smoothstep(-0.5 * u_mk_soft, 0.5 * u_mk_soft, sd);
    return u_mk_invert == 1 ? 1.0 - m : m;
}
""" % {"n": MAX_POINTS}

CUT = GLSL + """
void main() {
    vec4 c = texture(t_prev, v_uv);
    f_out = vec4(c.rgb, c.a * mkMask(v_uv));
}
"""

BLUR_MIX = GLSL + """
uniform sampler2D t_in;     // a entrada da máscara
uniform sampler2D t_soft;   // ela desfocada
void main() {
    f_out = mix(texture(t_in, v_uv), texture(t_soft, v_uv), mkMask(v_uv));
}
"""

PIXEL_MIX = GLSL + """
uniform sampler2D t_in;     // a entrada da máscara
uniform sampler2D t_mip;    // ela com mipmaps (a média de cada quadradinho)
uniform float u_mk_cell;    // lado do quadradinho (px@1080)
void main() {
    vec2 p = mkPoint(v_uv) - u_mk_center;
    vec2 cell = (floor(p / u_mk_cell) + 0.5) * u_mk_cell + u_mk_center;  // centro do quadradinho
    vec2 uv = cell * u_fx_scale / u_fx_clip_px + 0.5;
    float lod = log2(max(u_mk_cell * u_fx_scale, 1.0));
    f_out = mix(texture(t_in, v_uv), textureLod(t_mip, uv, lod), mkMask(v_uv));
}
"""

COPY = """
void main() {
    f_out = texture(t_prev, v_uv);
}
"""


# ------------------------------------------------------------------ dados do clipe
def points_of(fx: Any) -> list[tuple[float, float]]:
    """Os pontos do polígono guardados em `Clip.fx` (ou no próprio `Clip`): até `MAX_POINTS`, só os válidos."""
    if hasattr(fx, "fx"):
        fx = fx.fx
    entry = (fx or {}).get(FX_KEY) if isinstance(fx, dict) else None
    raw = entry.get(POINTS_KEY) if isinstance(entry, dict) else None
    out: list[tuple[float, float]] = []
    for pt in raw if isinstance(raw, list) else []:
        try:
            x, y = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            out.append((x, y))
    return out[:MAX_POINTS]


def set_points(clip, points) -> None:
    """Grava os pontos do polígono em `clip.fx` (arredondados a 0,01 px; vazio tira a entrada)."""
    pts = [[round(float(x), 2), round(float(y), 2)] for x, y in list(points)[:MAX_POINTS]]
    fx = dict(getattr(clip, "fx", None) or {})
    if pts:
        fx[FX_KEY] = {**(fx.get(FX_KEY) if isinstance(fx.get(FX_KEY), dict) else {}), POINTS_KEY: pts}
    else:
        fx.pop(FX_KEY, None)
    clip.fx = fx


# ------------------------------------------------------------------ valores → uniforms e passos
def active(values: dict | None) -> bool:
    return (values or {}).get("mascara_forma", "nenhuma") in SHAPES


def cuts(values: dict | None) -> bool:
    """A máscara recorta (a saída tem cobertura)."""
    return active(values) and (values or {}).get("mascara_uso", "recortar") == "recortar"


def ready(values: dict, points) -> bool:
    """A forma existe: retângulo e elipse sempre; o polígono com 3 pontos ou mais."""
    return active(values) and (values["mascara_forma"] != "poligono" or len(points) >= 3)


def uniforms_for(values: dict, points, scale: float) -> dict[str, Any]:
    """Os uniforms `u_mk_*` de `GLSL`. `scale`: texels do clipe por px@1080 (a passagem tem pelo menos um texel)."""
    pts = [(float(x), float(y)) for x, y in list(points)[:MAX_POINTS]]
    pad = pts + [(0.0, 0.0)] * (MAX_POINTS - len(pts))
    return {"u_mk_shape": SHAPES.get(values["mascara_forma"], 1),
            "u_mk_center": (float(values["mascara_x"]), float(values["mascara_y"])),
            "u_mk_half": (0.5 * float(values["mascara_largura"]), 0.5 * float(values["mascara_altura"])),
            "u_mk_rot": math.radians(float(values["mascara_rotacao"])),
            "u_mk_soft": max(float(values["mascara_suavidade"]), 1.0 / max(scale, 1e-6)),
            "u_mk_grow": float(values["mascara_expandir"]), "u_mk_invert": int(bool(values["mascara_inverter"])),
            "u_mk_n": len(pts), "u_mk_pts": pad}


def uniforms(ctx: vfx.Ctx) -> dict[str, Any] | None:
    """Os uniforms da máscara do clipe neste quadro, ou None se ele não tem forma (para outros efeitos que usam
    `GLSL`, como o desfoque de lente dentro ou fora da forma)."""
    v = ctx.values
    pts = points_of(ctx.fx)
    if not ready(v, pts):
        return None
    return uniforms_for(v, pts, ctx.scale)


def passes(ctx: vfx.Ctx) -> list[vfx.Pass]:
    u = uniforms(ctx)
    if u is None:  # polígono ainda sem pontos: nada a fazer
        return []
    use = ctx.values["mascara_uso"]
    if use == "desfocar":
        return [vfx.Pass("mascara_desfoque", kind="blur", sigma=ctx.px(ctx.values["mascara_forca"]), dtype="f2"),
                vfx.Pass("mascara", BLUR_MIX, uniforms=u, inputs={"t_in": "in", "t_soft": "pass:mascara_desfoque"})]
    if use == "pixelar":
        cell = {"u_mk_cell": max(float(ctx.values["mascara_forca"]), 1.0 / max(ctx.scale, 1e-6))}
        return [vfx.Pass("mascara_mip", COPY, dtype="f2", mip=True),
                vfx.Pass("mascara", PIXEL_MIX, uniforms={**u, **cell},
                         inputs={"t_in": "in", "t_mip": "pass:mascara_mip"})]
    return [vfx.Pass("mascara", CUT, uniforms=u)]


EFFECT = vfx.register(vfx.Effect(EFFECT_ID, MODULE, vfx.ORDER["mascara"], active=active, passes=passes, alpha=cuts,
                                 keys=KEYS))


# ------------------------------------------------------------------ geometria em numpy (referência e alças)
def rot(deg: float) -> np.ndarray:
    """R(θ): leva o espaço da forma ao do clipe (positivo = sentido horário com y para baixo)."""
    t = math.radians(float(deg))
    return np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])


def to_local(p, values: dict) -> np.ndarray:
    """px@1080 do clipe → espaço da forma (centro na origem, sem a rotação)."""
    d = np.asarray(p, dtype=np.float64) - np.array([values["mascara_x"], values["mascara_y"]], dtype=np.float64)
    return d @ rot(values["mascara_rotacao"])  # R(−θ)·d, linha a linha


def to_clip(q, values: dict) -> np.ndarray:
    """Espaço da forma → px@1080 do clipe."""
    q = np.asarray(q, dtype=np.float64)
    return q @ rot(values["mascara_rotacao"]).T + np.array([values["mascara_x"], values["mascara_y"]])


def clip_px(uv, tex_w: int, tex_h: int) -> np.ndarray:
    """uv do clipe (0 a 1) → px@1080 do clipe a partir do centro."""
    uv = np.asarray(uv, dtype=np.float64)
    return (uv - 0.5) * np.array([1080.0 * tex_w / tex_h, 1080.0])


def clip_uv(p, tex_w: int, tex_h: int) -> np.ndarray:
    """px@1080 do clipe a partir do centro → uv do clipe."""
    p = np.asarray(p, dtype=np.float64)
    return p / np.array([1080.0 * tex_w / tex_h, 1080.0]) + 0.5


def _poly_distance(q: np.ndarray, pts: np.ndarray) -> np.ndarray:
    d = np.sum((q - pts[0]) ** 2, axis=-1)
    s = np.ones(q.shape[:-1])
    n = len(pts)
    for i in range(n):
        vi, vj = pts[i], pts[i - 1]
        e = vj - vi
        w = q - vi
        t = np.clip((w @ e) / max(float(e @ e), 1e-12), 0.0, 1.0)
        b = w - t[..., None] * e
        d = np.minimum(d, np.sum(b * b, axis=-1))
        c1 = q[..., 1] >= vi[1]
        c2 = q[..., 1] < vj[1]
        c3 = e[0] * w[..., 1] > e[1] * w[..., 0]
        flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
        s = np.where(flip, -s, s)
    return s * np.sqrt(d)


def distance(q, values: dict, points=()) -> np.ndarray:
    """Distância com sinal (px@1080; negativa dentro) de pontos no espaço da forma (… × 2): a conta do `mkDist`."""
    q = np.asarray(q, dtype=np.float64)
    shape = values["mascara_forma"]
    half = np.array([0.5 * float(values["mascara_largura"]), 0.5 * float(values["mascara_altura"])])
    if shape == "retangulo":
        a = np.abs(q) - half
        return np.linalg.norm(np.maximum(a, 0.0), axis=-1) + np.minimum(np.maximum(a[..., 0], a[..., 1]), 0.0)
    if shape == "elipse":
        r = np.maximum(half, 1e-3)
        k1 = np.linalg.norm(q / (r * r), axis=-1)
        k0 = np.linalg.norm(q / r, axis=-1)
        with np.errstate(divide="ignore", invalid="ignore"):
            d = k0 * (k0 - 1.0) / k1
        return np.where(k1 < 1e-9, -min(r), d)
    return _poly_distance(q, np.asarray(points, dtype=np.float64).reshape(-1, 2))


def mask(values: dict, points, tex_w: int, tex_h: int) -> np.ndarray:
    """A máscara (h × w, 1 dentro) nos centros dos texels de um clipe tex_w × tex_h: a conta do `mkMask`."""
    u = uniforms_for(values, points, tex_h / 1080.0)
    xs = (np.arange(tex_w) + 0.5) / tex_w
    ys = (np.arange(tex_h) + 0.5) / tex_h
    uv = np.stack(np.meshgrid(xs, ys), axis=-1)
    q = to_local(clip_px(uv, tex_w, tex_h), values)
    sd = distance(q, values, points) - u["u_mk_grow"]
    soft = u["u_mk_soft"]
    t = np.clip((sd + 0.5 * soft) / soft, 0.0, 1.0)
    m = 1.0 - t * t * (3.0 - 2.0 * t)
    return 1.0 - m if values["mascara_inverter"] else m


def outline(values: dict, points=(), n: int = 72) -> np.ndarray:
    """O contorno da forma (sem expandir) em px@1080 do clipe (k × 2), para desenhar na prévia."""
    shape = values["mascara_forma"]
    hw, hh = 0.5 * float(values["mascara_largura"]), 0.5 * float(values["mascara_altura"])
    if shape == "retangulo":
        q = np.array([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]])
    elif shape == "elipse":
        t = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
        q = np.stack([hw * np.cos(t), hh * np.sin(t)], axis=-1)
    else:
        q = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    return to_clip(q, values) if len(q) else q
