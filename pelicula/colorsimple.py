"""Cor simples do modo Edição (1.6, módulo "cor_simples"): ferramentas de um clique sobre os ajustes do clipe.

Tudo aqui é função pura (sem Qt nem GPU); a interface fica em `ui/color_tools.py`. O resultado de cada
ferramenta são **ajustes do clipe** comuns (`editparams`), que continuam editáveis e passam pelo desfazer do
`TimelineModel`:

- **Conta-gotas do balanço** (`white_balance_from`): o pixel clicado (do arquivo, antes dos ajustes) vira neutro:
  a temperatura e a tonalidade saem da mesma mistura por canal de `compositor.wb_gains_ev`, resolvida exatamente.
- **Automático do clipe inteiro** (`sample_frames` + `auto_adjust_frames`): `N_AUTO` quadros espalhados pelo clipe
  (sempre os mesmos para o mesmo clipe) analisados juntos por `compositor.auto_adjust`.
- **Igualar a outro clipe ou a uma imagem** (`match_adjust`): exposição, temperatura, tonalidade, saturação e
  contraste que levam as estatísticas de um quadro às de outro, sem contar a pele (máscara de `masks.py`).
- **Clicar numa cor** (`pick_target`, `nearest_band`): o matiz clicado vira o centro da "Cor escolhida".

E os três ajustes novos do clipe, desenhados pelo `editshaders.CLIP_CS` (`GLSL` abaixo) depois do `colorCorrect`:

1. **Cor escolhida** (`alvo_*`): uma faixa de matiz (HSV, o mesmo círculo do HSL) em volta de `alvo_matiz`, lida
   na cor do arquivo (`cin`, antes dos ajustes: o que foi clicado), muda matiz, saturação e luminância da cor já
   ajustada.
2. **Degradê** (`degrade_*`): exposição, temperatura, tonalidade (em luz) e saturação só no lado marcado do degradê
   (`masks.gradMask`, px@1080 do próprio clipe: ele acompanha o enquadramento). 0° = em cima (o céu).
3. **Pele natural** (`pele_natural`): na pele (`masks.skinMask` da cor do arquivo), a cor volta ao matiz e à
   saturação do arquivo (com a claridade ajustada) e fica mais uniforme (`masks.skinEven`). Só a cor: a
   claridade e a textura ficam como estão.

Sem nenhum deles (`active` falso), `uniforms` devolve `{}` e o clipe é desenhado pelo `CLIP` de sempre.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from . import masks

N_AUTO = 9                   # quadros do "Automático" do clipe inteiro
TARGET_EDGE = 0.5            # a faixa da cor escolhida é cheia até esta fração da largura e some na largura
SAT_GATE = (0.02, 0.2)       # como no HSL do clipe: cores quase cinzas não mudam
W709 = np.array([0.2126, 0.7152, 0.0722])

SKIN_KEYS = ("pele_natural", "pele_centro")
TARGET_KEYS = ("alvo_matiz", "alvo_largura", "alvo_desvio", "alvo_sat", "alvo_luz")
GRADIENT_KEYS = ("degrade_tipo", "degrade_angulo", "degrade_x", "degrade_y", "degrade_raio", "degrade_suavidade",
                 "degrade_inverter", "degrade_exposicao", "degrade_temperatura", "degrade_tonalidade",
                 "degrade_saturacao")
NEW_KEYS = SKIN_KEYS + TARGET_KEYS + GRADIENT_KEYS
MATCH_KEYS = ("exposicao", "temperatura", "tonalidade", "saturacao", "contraste")

_TARGET_FX = ("alvo_desvio", "alvo_sat", "alvo_luz")
_GRADIENT_FX = ("degrade_exposicao", "degrade_temperatura", "degrade_tonalidade", "degrade_saturacao")


def _f(v: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(v.get(key, default))
    except (TypeError, ValueError):
        return default


def target_active(v: dict[str, Any]) -> bool:
    return any(_f(v, k) != 0.0 for k in _TARGET_FX)


def gradient_active(v: dict[str, Any]) -> bool:
    return any(_f(v, k) != 0.0 for k in _GRADIENT_FX)


def skin_active(v: dict[str, Any]) -> bool:
    return _f(v, "pele_natural") > 0.0


def active(v: dict[str, Any]) -> bool:
    """Algum dos três ajustes faz algo (só então o clipe usa o `CLIP_CS`)."""
    return target_active(v) or gradient_active(v) or skin_active(v)


def wb_ev(temp: float, tint: float) -> np.ndarray:
    """Ganhos (EV) por canal: a mesma mistura de `compositor.wb_gains_ev` e do look."""
    t, ti = temp / 100.0, tint / 100.0
    return np.array([0.28 * t + 0.08 * ti, -0.22 * ti, -0.38 * t + 0.08 * ti])


_WB_MIX = np.array([[1.0, 0.28, 0.08], [1.0, 0.0, -0.22], [1.0, -0.38, 0.08]])  # (EV, temp, tint) → EV por canal


def uniforms(v: dict[str, Any]) -> dict[str, Any]:
    """Uniforms `u_cs_*` do `editshaders.CLIP_CS` ({} = nada a fazer)."""
    if not active(v):
        return {}
    tgt = target_active(v)
    grad = gradient_active(v)
    g, k = masks.gradient_uniform(str(v.get("degrade_tipo", "linear")), _f(v, "degrade_x"), _f(v, "degrade_y"),
                                  _f(v, "degrade_angulo"), _f(v, "degrade_raio", 500.0),
                                  _f(v, "degrade_suavidade", 400.0), bool(v.get("degrade_inverter")))
    gains = _f(v, "degrade_exposicao") + wb_ev(_f(v, "degrade_temperatura"), _f(v, "degrade_tonalidade"))
    return {
        "u_cs_on": 1,
        "u_cs_tgt": (_f(v, "alvo_matiz"), max(1.0, _f(v, "alvo_largura", 30.0)), _f(v, "alvo_desvio"),
                     1.0 if tgt else 0.0),
        "u_cs_tgt2": (_f(v, "alvo_sat"), _f(v, "alvo_luz")),
        "u_cs_grad": g,
        "u_cs_gradk": (k[0], k[1], k[2], 1.0 if grad else 0.0),
        "u_cs_gadj": tuple(float(x) for x in gains) + (_f(v, "degrade_saturacao"),),
        "u_cs_skin": (_f(v, "pele_centro", masks.SKIN_HUE), masks.SKIN_WIDTH, max(0.0, _f(v, "pele_natural")), 0.0),
    }


GLSL = masks.GLSL + """
// ---------------------------------------------------------------- 1.6: cor simples (`colorsimple.py`)
uniform int u_cs_on;
uniform vec4 u_cs_tgt;    // cor escolhida: matiz (graus, HSV), largura (graus), giro (graus), 1 = ligada
uniform vec2 u_cs_tgt2;   // saturação e luminância da cor escolhida (-1 a 1)
uniform vec4 u_cs_grad;   // degradê: centro x, y (px@1080 do clipe), ângulo (rad), suavidade (px@1080)
uniform vec4 u_cs_gradk;  // raio, radial, inverter, 1 = ligado
uniform vec4 u_cs_gadj;   // no lado marcado: ganhos por canal (EV: exposição + balanço) e saturação (-1 a 1)
uniform vec4 u_cs_skin;   // pele natural: centro do matiz (OkLCh), meia largura, força, 0

// `cin`: a cor do clipe antes dos ajustes (o que o usuário clicou); `c`: depois do colorCorrect.
vec3 colorSimple(vec3 cin, vec3 c, vec2 uv) {
    if (u_cs_tgt.w > 0.5) {
        vec3 hin = rgb2hsv(max(cin, vec3(0.0)));
        float d = abs(mod(hin.x - u_cs_tgt.x + 540.0, 360.0) - 180.0);
        float w = (1.0 - smoothstep(0.5 * u_cs_tgt.y, u_cs_tgt.y, d)) * smoothstep(0.02, 0.2, hin.y);
        if (w > 0.0) {
            vec3 hsv = rgb2hsv(max(c, vec3(0.0)));
            hsv.x += u_cs_tgt.z * w;
            hsv.y = clamp(hsv.y * (1.0 + u_cs_tgt2.x * w), 0.0, 1.0);
            hsv.z *= 1.0 + 0.5 * u_cs_tgt2.y * w;
            c = hsv2rgb(hsv);
        }
    }
    if (u_cs_gradk.w > 0.5) {
        float g = gradMask(framePoint(uv, u_clip_px.x / u_clip_px.y), u_cs_grad, u_cs_gradk);
        if (g > 0.0) {
            vec3 lin = pow(max(c, vec3(0.0)), vec3(2.2)) * exp2(u_cs_gadj.xyz * g);
            c = pow(lin, vec3(1.0 / 2.2));
            float L = dot(c, W709);
            c = L + (c - L) * (1.0 + u_cs_gadj.w * g);
        }
    }
    if (u_cs_skin.z > 0.0) {
        float m = skinMask(cin, u_cs_skin.xy) * u_cs_skin.z;
        if (m > 0.0) {
            vec3 li = linToOklab(pow(max(cin, vec3(0.0)), vec3(2.2)));
            vec3 lc = linToOklab(pow(max(c, vec3(0.0)), vec3(2.2)));
            vec3 lab = vec3(lc.x, li.yz * (lc.x / max(li.x, 1e-4)));
            lab = skinEven(lab, u_cs_skin.x, u_cs_skin.z);
            vec3 p = pow(max(oklabToLin(lab), vec3(0.0)), vec3(1.0 / 2.2));
            c = mix(c, p, m);
        }
    }
    return c;
}
"""


# ------------------------------------------------------------------ referência numpy (testes)
def rgb2hsv(c) -> np.ndarray:
    """O `rgb2hsv` do `editshaders.CLIP` (matiz em graus, saturação, valor)."""
    c = np.asarray(c, dtype=np.float64)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mx = c.max(axis=-1)
    mn = c.min(axis=-1)
    d = mx - mn
    safe = np.maximum(d, 1e-12)
    h = np.where(mx == r, np.mod((g - b) / safe, 6.0), np.where(mx == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0))
    h = np.where(d > 1e-6, h, 0.0)
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-12), 0.0)
    return np.stack([h * 60.0, s, mx], axis=-1)


def hsv2rgb(c) -> np.ndarray:
    c = np.asarray(c, dtype=np.float64)
    h = np.mod(c[..., 0], 360.0) / 60.0
    C = c[..., 2] * c[..., 1]
    X = C * (1.0 - np.abs(np.mod(h, 2.0) - 1.0))
    m = c[..., 2] - C
    z = np.zeros_like(C)
    i = np.floor(h).astype(int) % 6
    opts = [np.stack(t, axis=-1) for t in ((C, X, z), (X, C, z), (z, C, X), (z, X, C), (X, z, C), (C, z, X))]
    out = np.zeros(c.shape)
    for n, o in enumerate(opts):
        out = np.where((i == n)[..., None], o, out)
    return out + m[..., None]


def apply(cin, c, p, v: dict[str, Any]) -> np.ndarray:
    """`colorSimple` em numpy. `cin`, `c`: vídeo (… × 3); `p`: px@1080 do clipe (… × 2, `masks.frame_points`)."""
    cin = np.asarray(cin, dtype=np.float64)
    c = np.asarray(c, dtype=np.float64).copy()
    if not active(v):
        return c
    U = uniforms(v)
    th, tw, shift, on = U["u_cs_tgt"]
    if on > 0.5:
        hin = rgb2hsv(np.maximum(cin, 0.0))
        d = masks.hue_distance(hin[..., 0], th)
        w = (1.0 - masks.smoothstep(0.5 * tw, tw, d)) * masks.smoothstep(*SAT_GATE, hin[..., 1])
        hsv = rgb2hsv(np.maximum(c, 0.0))
        s2, l2 = U["u_cs_tgt2"]
        hsv[..., 0] += shift * w
        hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + s2 * w), 0.0, 1.0)
        hsv[..., 2] *= 1.0 + 0.5 * l2 * w
        c = np.where((w > 0.0)[..., None], hsv2rgb(hsv), c)
    g4, k4 = U["u_cs_grad"], U["u_cs_gradk"]
    if k4[3] > 0.5:
        kind = "radial" if k4[1] > 0.5 else "linear"
        g = masks.gradient_mask(p, kind, g4[0], g4[1], math.degrees(g4[2]), k4[0], g4[3], k4[2] > 0.5)[..., None]
        adj = np.asarray(U["u_cs_gadj"])
        lin = np.maximum(c, 0.0) ** 2.2 * np.exp2(adj[:3] * g)
        c2 = lin ** (1.0 / 2.2)
        L = (c2 @ W709)[..., None]
        c2 = L + (c2 - L) * (1.0 + adj[3] * g)
        c = np.where(g > 0.0, c2, c)
    hue, width, amount, _z = U["u_cs_skin"]
    if amount > 0.0:
        m = (masks.skin_mask(cin, hue, width) * amount)[..., None]
        li = masks.oklab(masks.code_to_lin(cin))
        lc = masks.oklab(masks.code_to_lin(c))
        lab = np.concatenate([lc[..., :1], li[..., 1:] * (lc[..., :1] / np.maximum(li[..., :1], 1e-4))], axis=-1)
        lab = masks.skin_even(lab, hue, amount)
        pc = np.maximum(masks.oklab_to_lin(lab), 0.0) ** (1.0 / 2.2)
        c = c + (pc - c) * m
    return c


# ------------------------------------------------------------------ amostras do quadro
def to_code(img) -> np.ndarray:
    """Imagem (h × w × 3 ou 4, uint8/uint16/float) → vídeo float de 0 a 1 (h × w × 3); RGBA pré-multiplicado
    volta à cor direta."""
    a = np.asarray(img)
    scale = 65535.0 if a.dtype == np.uint16 else 255.0 if a.dtype == np.uint8 else 1.0
    f = a.astype(np.float64) / scale
    if f.shape[-1] == 4:
        alpha = f[..., 3:4]
        return np.where(alpha > 1e-6, f[..., :3] / np.maximum(alpha, 1e-6), 0.0)
    return f[..., :3]


def clip_point(seq, layer, canvas_w: int, canvas_h: int, fx: float, fy: float) -> tuple[float, float] | None:
    """O uv (0 a 1, y para baixo) do clipe da camada no ponto (fração da tela) — None fora do clipe ou do corte."""
    from . import compositor
    v = layer.values if layer.values is not None else layer.clip.values
    m = compositor.transform(seq, layer.clip, canvas_w, canvas_h, v)
    x, y = fx * canvas_w, fy * canvas_h
    u, w, _ = m @ np.array([x, y, 1.0])
    if not (v["corte_esq"] <= u <= 1.0 - v["corte_dir"] and v["corte_topo"] <= w <= 1.0 - v["corte_base"]):
        return None
    return float(u), float(w)


def sample(img, u: float, v: float, r: int = 2) -> np.ndarray:
    """Média (vídeo de 0 a 1, RGB) de um quadrado de (2r + 1)² pixels em volta do uv."""
    code = to_code(img)
    h, w = code.shape[:2]
    x = min(max(int(u * w), 0), w - 1)
    y = min(max(int(v * h), 0), h - 1)
    return code[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, 3).mean(axis=0)


def _snap(value: float, key: str) -> float:
    from . import editparams
    p = editparams.VIDEO.params[key]
    value = min(max(float(value), p.min), p.max)
    return round(round(value / p.step) * p.step, 4) if p.step else value


# ------------------------------------------------------------------ conta-gotas do balanço
def white_balance_from(rgb) -> dict[str, float] | None:
    """Temperatura e tonalidade que deixam neutra a cor clicada (vídeo de 0 a 1, antes dos ajustes do clipe).

    O balanço do clipe é o primeiro passo da cor (ganho por canal na luz, código^2,2), então trocar os dois
    valores pelos daqui deixa esse pixel cinza. None: a cor é escura ou estourada demais para servir de neutro.
    """
    rgb = np.asarray(rgb, dtype=np.float64).reshape(3)
    if rgb.max() < 0.03 or rgb.min() > 0.995:
        return None
    lin = np.maximum(rgb, 1e-4) ** 2.2
    logs = np.log2(lin)
    want = logs.mean() - logs                      # o ganho (EV) que iguala os canais
    _e, t, ti = np.linalg.solve(_WB_MIX, want)
    return {"temperatura": _snap(t * 100.0, "temperatura"), "tonalidade": _snap(ti * 100.0, "tonalidade")}


# ------------------------------------------------------------------ automático do clipe inteiro
def sample_frames(clip, n: int = N_AUTO) -> list[int]:
    """Quadros da sequência (no meio de `n` partes iguais do clipe) que o "Automático" do clipe inteiro analisa.
    Sempre os mesmos para o mesmo clipe."""
    n = max(1, min(int(n), int(clip.dur)))
    frames = [clip.start + min(clip.dur - 1, int((i + 0.5) * clip.dur / n)) for i in range(n)]
    return sorted(set(frames))


def auto_adjust_frames(images) -> dict[str, float]:
    """`compositor.auto_adjust` sobre vários quadros juntos (um só ajuste para o clipe inteiro)."""
    from . import compositor
    imgs = [np.asarray(i) for i in images if i is not None]
    if not imgs:
        return {}
    w = min(i.shape[1] for i in imgs)
    ch = min(i.shape[2] for i in imgs)
    dtype = imgs[0].dtype
    stack = np.concatenate([i[:, :w, :ch].astype(dtype) for i in imgs], axis=0)
    return compositor.auto_adjust(stack)


# ------------------------------------------------------------------ igualar
def _stats(code: np.ndarray, protect_skin: bool, hue: float) -> dict[str, Any] | None:
    px = code.reshape(-1, 3)
    if len(px) > 40000:
        px = px[:: int(math.ceil(len(px) / 40000))]
    lum = px @ W709
    keep = (lum > 0.04) & (lum < 0.96)
    if protect_skin:
        keep &= masks.skin_mask(px, hue) < 0.3
    if keep.sum() < 50:
        return None
    sel = px[keep]
    lin = np.maximum(sel, 1e-4) ** 2.2
    ylin = lin @ W709
    mid = (lum[keep] > 0.12) & (lum[keep] < 0.88)
    logs = np.log2(np.maximum((lin[mid] if mid.sum() >= 50 else lin).mean(axis=0), 1e-6))
    luma = sel @ W709
    mean = max(float(luma.mean()), 1e-4)
    chroma = np.abs(sel - luma[:, None]).mean(axis=1)
    # Cor e contraste relativos à luminância média: não mudam com a exposição (que é medida à parte).
    return {"ylog": float(np.median(np.log2(np.maximum(ylin, 1e-6)))), "logs": logs,
            "chroma": float(chroma.mean()) / mean, "std": float(np.std(luma)) / mean}


def match_adjust(src, ref, protect_skin: bool = True, skin_hue: float = masks.SKIN_HUE) -> dict[str, float]:
    """Ajustes do clipe que levam o quadro `src` (do arquivo, antes dos ajustes) para perto da imagem `ref`.

    Exposição (mediana da luz), balanço (média dos canais na luz, nos tons médios), saturação (cor média em volta
    da luminância) e contraste (desvio da luminância). Com `protect_skin`, a pele (`masks.skin_mask`) fica fora
    das contas — um rosto não puxa o balanço — e o resultado liga a "Pele natural" pela metade, para a pele não
    acompanhar a troca de cor. Devolve só chaves do clipe (`MATCH_KEYS` e, com a pele, `pele_natural`).
    """
    a = _stats(to_code(src), protect_skin, skin_hue)
    b = _stats(to_code(ref), protect_skin, skin_hue)
    if a is None or b is None:
        return {}
    out: dict[str, float] = {}
    out["exposicao"] = _snap(np.clip(b["ylog"] - a["ylog"], -3.0, 3.0), "exposicao")
    want = (b["logs"] - b["logs"].mean()) - (a["logs"] - a["logs"].mean())
    _e, t, ti = np.linalg.solve(_WB_MIX, want)
    out["temperatura"] = _snap(t * 100.0, "temperatura")
    out["tonalidade"] = _snap(ti * 100.0, "tonalidade")
    if a["chroma"] > 1e-3:
        out["saturacao"] = _snap(np.clip(b["chroma"] / a["chroma"] - 1.0, -0.8, 0.8), "saturacao")
    if a["std"] > 1e-3:
        k = np.clip(b["std"] / a["std"] - 1.0, -0.5, 0.5)       # inclinação no meio da curva em S: 1 + k
        out["contraste"] = _snap(k / 0.8, "contraste")
    if protect_skin:
        out["pele_natural"] = 0.5
    return out


def match_values(values: dict[str, Any], delta: dict[str, float], ref_values: dict[str, Any] | None = None
                 ) -> dict[str, Any]:
    """Os ajustes do clipe depois de "Igualar": os da referência (outro clipe; None = uma imagem) somados à
    diferença medida (`match_adjust`). Só as chaves de `MATCH_KEYS` (e a pele) mudam."""
    out = dict(values)
    base = ref_values if ref_values is not None else {k: 0.0 for k in MATCH_KEYS}
    for k in ("exposicao", "temperatura", "tonalidade", "contraste"):
        out[k] = _snap(float(base.get(k, 0.0)) + float(delta.get(k, 0.0)), k)
    s = (1.0 + float(base.get("saturacao", 0.0))) * (1.0 + float(delta.get("saturacao", 0.0))) - 1.0
    out["saturacao"] = _snap(s, "saturacao")
    if "pele_natural" in delta:
        out["pele_natural"] = max(float(values.get("pele_natural", 0.0)), float(delta["pele_natural"]))
    return out


# ------------------------------------------------------------------ clicar numa cor
def nearest_band(hue: float) -> str:
    """A faixa do HSL do clipe (`editparams.HSL_COLORS`) mais perto de um matiz HSV (graus)."""
    from . import editparams
    return min(editparams.HSL_COLORS, key=lambda b: float(masks.hue_distance(hue, b[2])))[0]


def pick_target(rgb) -> dict[str, Any] | None:
    """A "Cor escolhida" de um clique (vídeo de 0 a 1, antes dos ajustes): o matiz HSV vira o centro e a faixa
    do HSL mais perto acompanha. None: a cor é quase cinza (sem matiz)."""
    hsv = rgb2hsv(np.asarray(rgb, dtype=np.float64).reshape(3))
    if hsv[1] < SAT_GATE[1] * 0.5 or hsv[2] < 0.03:
        return None
    hue = float(hsv[0]) % 360.0
    return {"alvo_matiz": round(hue * 2.0) / 2.0, "band": nearest_band(hue)}
