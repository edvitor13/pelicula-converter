"""1.9, tempo da imagem (#68, frente F5; ARQUITETURA §53): deflicker, ruído temporal e câmera lenta por mistura de
quadros. Sem Qt nem GPU: os efeitos entram na pilha do clipe (`vfx.py`, ordem "tempo") e os passos rodam em
`Engine._fx_stack`; a mistura de quadros é uma janela de `vfx.WINDOWS`. Módulo Beta "tempo_imagem" (só a interface e o
aviso; a renderização nunca consulta módulos).

- **Deflicker** (`deflicker`, `deflicker_janela`): uma análise do arquivo inteiro (`analyze`, num trabalho de CPU, fora
  da GUI) guarda em `Source.analysis["deflicker"]` a média do sinal de luma (Y' com os pesos Rec.709 sobre o código
  R'G'B' que o `CLIP` lê) de cada quadro do arquivo, decodificado pequeno. No quadro, o alvo é a média móvel dessas
  médias numa janela de `deflicker_janela` segundos (`smooth`, em cache); o passo leva as duas médias à luz linear pela
  curva do próprio clipe (o perfil de câmera dele ou a entrada do look; numa curva de potência ou de log, uma mudança
  de exposição do quadro inteiro dá exatamente a razão da luz) e multiplica a luz do quadro pela razão elevada à força.
  Só o quadro do arquivo decide (`Layer.src_frame`): cortar ou aparar o clipe não muda nada. Sem análise, nenhum passo.
  Nenhum quadro a mais é decodificado no render.
- **Ruído temporal** (`ruido_temporal`, `ruido_temporal_quadros`): média dos quadros vizinhos do arquivo (n−2 … n+2, os
  vizinhos da base, `Effect.radius`) na luz linear, cada um pesado pela semelhança com o quadro atual pixel a pixel
  (como o atadenoise do ffmpeg, sem compensação de movimento): onde algo se mexe o vizinho não entra (sem fantasma).
- **Mistura de quadros** (`mistura_quadros`, por clipe, desligada): quando o clipe mostra menos de um quadro do arquivo
  por quadro da sequência (velocidade abaixo de 1×, rampas e fps da fonte abaixo do da sequência), o quadro é a mistura
  dos dois quadros do arquivo em volta da posição fracionária u (`blend_window`: [(⌊u⌋, 1 − f), (⌊u⌋ + 1, f)]), pelo
  mesmo caminho do obturador (`LayerImage.stack` → `Engine.temporal_blend`, na luz da curva do clipe). f = 0 e clipes
  a 1× ou mais rápidos: nenhuma janela (o quadro de sempre, bit a bit; o obturador continua valendo nos rápidos). O
  reverso usa a mesma posição de `Sequence.src_frame` (o espelho exato). O som não muda; sem fluxo óptico.
"""

from __future__ import annotations

import functools
import math
import threading
from typing import Any, Callable

import numpy as np

from . import vfx

MODULE = "tempo_imagem"
SECTION = "tempo_imagem"           # seção de `editparams.VIDEO_SECTIONS` (bloco "# 1.9 F5")
DEFLICKER = "deflicker"            # id do efeito e tipo da análise em `Source.analysis`
NOISE = "ruido_temporal"
BLEND = "mistura_quadros"          # id da janela (`vfx.WINDOWS`) e do efeito sem passo que só serve ao aviso do módulo
DEFLICKER_KEYS = ("deflicker", "deflicker_janela")
NOISE_KEYS = ("ruido_temporal", "ruido_temporal_quadros")
ANALYSIS_W = 64                    # largura dos quadros da análise (px)
WINDOW_DEFAULT = 0.5               # s: janela do deflicker
GAIN_LIMIT = 2.0                   # o deflicker corrige no máximo 1 stop para cada lado (um corte para o preto não vira cinza)
NOISE_TAU = 0.1                    # diferença de código (0–1) que pesa 1/e com 100% de força
BLEND_MIN = 1e-4                   # f abaixo disto (ou acima de 1 − isto): o quadro de sempre


def _num(v: dict, key: str, default: float) -> float:
    try:
        return float(v.get(key, default))
    except (TypeError, ValueError):
        return float(default)


# ------------------------------------------------------------------ deflicker: análise (CPU, num trabalho da fila)
def analyze(src, cancel: threading.Event | None = None,
            report: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """A análise do deflicker de um arquivo (`timeline.Source` de vídeo): a média do luma de cada quadro, decodificado
    com `ANALYSIS_W` px de largura em 16 bits. Devolve o dicionário de `Source.analysis["deflicker"]`:
    {"carimbo": `vfx.stamp`, "fps", "quadros", "media": `vfx.pack` (float32)}. `cancel` interrompe (RuntimeError)."""
    from . import media
    from .i18n import _
    if src is None or not src.is_file or src.is_image or not src.has_video:
        raise ValueError(_("O deflicker precisa de um clipe de vídeo de um arquivo."))
    w = ANALYSIS_W
    h = max(2, int(round(w * src.height / max(1, src.width) / 2.0)) * 2)
    reader = media.FrameReader(src.to_info(), w, h, 16)
    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
    means: list[float] = []
    total = int(src.frames or 0)
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise RuntimeError(_("Cancelado."))
            img = reader.read()
            if img is None:
                break
            a = np.asarray(img, dtype=np.float64)[..., :3]
            if img.dtype == np.uint16:
                a = a / 65535.0
            elif img.dtype == np.uint8:
                a = a / 255.0
            means.append(float((a @ weights).mean()))
            if report is not None and len(means) % 25 == 0:
                report(len(means), total)
    finally:
        reader.close()
    if not means:
        raise RuntimeError(reader.error or _("Nenhum quadro lido do arquivo."))
    arr = np.asarray(means, dtype=np.float32)
    return {"carimbo": vfx.stamp(src.path), "fps": float(src.fps), "quadros": int(arr.size), "media": vfx.pack(arr)}


def means_of(entry: Any) -> np.ndarray | None:
    """As médias guardadas por `analyze` (float32, uma por quadro do arquivo), ou None."""
    if not isinstance(entry, dict):
        return None
    arr = vfx.unpack(entry.get("media"))
    if arr is None or arr.ndim != 1 or arr.size == 0:
        return None
    return arr


def window_frames(seconds: float, fps: float) -> int:
    """Quadros da janela do deflicker (ímpar, pelo menos 1)."""
    n = max(1, int(round(float(seconds) * float(fps or 0.0))))
    return n if n % 2 else n + 1


def smooth(means: np.ndarray, n: int) -> np.ndarray:
    """Média móvel centrada de `n` quadros (ímpar); nas pontas do arquivo, só os quadros que existem."""
    m = np.asarray(means, dtype=np.float64)
    half = max(0, int(n) // 2)
    if half == 0 or m.size <= 1:
        return m.astype(np.float32)
    cs = np.concatenate([[0.0], np.cumsum(m)])
    i = np.arange(m.size)
    lo = np.maximum(i - half, 0)
    hi = np.minimum(i + half + 1, m.size)
    return ((cs[hi] - cs[lo]) / (hi - lo)).astype(np.float32)


@functools.lru_cache(maxsize=16)
def _targets(data: str, dtype: str, shape: str, n: int) -> np.ndarray:
    arr = vfx.unpack({"dados": data, "tipo": dtype, "forma": [int(x) for x in shape.split(",") if x]})
    out = smooth(arr, n)
    out.setflags(write=False)
    return out


def targets_of(entry: dict, fps: float, seconds: float) -> np.ndarray | None:
    """O alvo de cada quadro (a média móvel), em cache pelo texto da análise e pela janela."""
    pk = entry.get("media") if isinstance(entry, dict) else None
    if means_of(entry) is None:
        return None
    return _targets(pk["dados"], str(pk.get("tipo")), ",".join(str(int(x)) for x in pk.get("forma", [])),
                    window_frames(seconds, fps))


def frames_of(ctx: vfx.Ctx) -> list[tuple[int, float]]:
    """Os quadros do arquivo neste quadro (e os pesos): a janela de um efeito de tempo (a mistura de quadros) ou o
    `src_frame` da camada."""
    win = ctx.seq.frame_window(ctx.clip, ctx.t) if ctx.clip is not None else None
    return list(win) if win else [(int(ctx.layer.src_frame), 1.0)]


def _gain_curve(ctx: vfx.Ctx) -> tuple[int, bool]:
    """A curva em que a análise foi medida: o perfil de câmera do clipe (com a faixa do arquivo), senão a do look."""
    from . import camera, media, tempo_camera
    clip = ctx.clip
    if camera.clip_profile(clip.values) is not None and ctx.src is not None:
        return tempo_camera.curve_of(camera.clip_values(clip.values), media.legal_range(ctx.src.to_info()))
    return ctx.light_curve


DEFLICKER_GLSL = """
uniform float u_df_mean;     // média do luma deste quadro (código)
uniform float u_df_target;   // a média móvel (código)
uniform float u_df_amount;   // força (0–1)
uniform float u_df_limit;    // ganho máximo (e 1/limite o mínimo)
uniform int u_df_curve;      // curva da análise (o perfil do clipe ou a entrada do look)
uniform int u_df_cv;
float dfLight(float m) { return dot(toLinear(vec3(m), u_df_curve, u_df_cv == 1), W709); }
void main() {
    vec4 c = texture(t_prev, v_uv);
    float a = dfLight(u_df_mean);
    float b = dfLight(u_df_target);
    float g = (a > 1e-6 && b > 1e-6) ? clamp(pow(b / a, u_df_amount), 1.0 / u_df_limit, u_df_limit) : 1.0;
    vec3 lin = fxDec(c.rgb);
    f_out = vec4(c.rgb + (fxEnc(lin * g) - fxEnc(lin)), c.a);  // só o que o ganho muda (fxEnc∘fxDec não é exato)
}
"""


def deflicker_uniforms(ctx: vfx.Ctx) -> dict[str, Any] | None:
    """Os uniforms do passo do deflicker neste quadro, ou None (sem análise)."""
    v = ctx.values
    entry = ctx.analysis(DEFLICKER)
    means = means_of(entry)
    if means is None:
        return None
    src = ctx.src
    fps = float(entry.get("fps") or getattr(src, "fps", 0.0) or 24.0)
    tg = targets_of(entry, fps, max(0.0, _num(v, "deflicker_janela", WINDOW_DEFAULT)))
    last = means.size - 1
    m = t = 0.0
    for k, wt in frames_of(ctx):
        i = min(max(int(k), 0), last)
        m += float(means[i]) * wt
        t += float(tg[i]) * wt
    curve, cv = _gain_curve(ctx)
    return {"u_df_mean": m, "u_df_target": t, "u_df_amount": max(0.0, min(1.0, _num(v, "deflicker", 0.0))),
            "u_df_limit": GAIN_LIMIT, "u_df_curve": int(curve), "u_df_cv": int(bool(cv))}


def _deflicker_active(v: dict) -> bool:
    return _num(v, "deflicker", 0.0) > 0.0


def _deflicker_passes(ctx: vfx.Ctx) -> list[vfx.Pass]:
    U = deflicker_uniforms(ctx)
    return [] if U is None else [vfx.Pass("ganho", DEFLICKER_GLSL, uniforms=U)]


# ------------------------------------------------------------------ ruído temporal
NOISE_GLSL = """
uniform sampler2D t_m2;
uniform sampler2D t_m1;
uniform sampler2D t_p1;
uniform sampler2D t_p2;
uniform int u_nr_radius;     // 1 ou 2 quadros de cada lado
uniform float u_nr_tau;      // diferença de código que pesa 1/e
vec4 nrC0;
vec3 nrAcc;
float nrW;
void nrAdd(sampler2D t) {
    vec4 c = texture(t, v_uv);
    vec4 d = c - nrC0;
    float w = exp(-dot(d, d) / (u_nr_tau * u_nr_tau));
    nrAcc += fxDec(c.rgb) * w;
    nrW += w;
}
void main() {
    nrC0 = texture(t_prev, v_uv);
    vec3 lin0 = fxDec(nrC0.rgb);
    nrAcc = lin0;
    nrW = 1.0;
    nrAdd(t_m1);
    nrAdd(t_p1);
    if (u_nr_radius > 1) {
        nrAdd(t_m2);
        nrAdd(t_p2);
    }
    f_out = vec4(nrC0.rgb + (fxEnc(nrAcc / nrW) - fxEnc(lin0)), nrC0.a);
}
"""


def noise_radius(v: dict) -> int:
    """Quadros vizinhos de cada lado que o ruído temporal lê (0 = desligado)."""
    if _num(v, "ruido_temporal", 0.0) <= 0.0:
        return 0
    return max(1, min(vfx.MAX_RADIUS, int(round(_num(v, "ruido_temporal_quadros", 2)))))


def _noise_passes(ctx: vfx.Ctx) -> list[vfx.Pass]:
    v = ctx.values
    r = noise_radius(v)
    if r <= 0:
        return []
    inputs = {"t_m1": "n-1", "t_p1": "n+1", "t_m2": "n-2" if r > 1 else "orig", "t_p2": "n+2" if r > 1 else "orig"}
    tau = NOISE_TAU * max(0.0, min(1.0, _num(v, "ruido_temporal", 0.0)))
    return [vfx.Pass("media", NOISE_GLSL, uniforms={"u_nr_radius": int(r), "u_nr_tau": max(1e-4, tau)},
                     inputs=inputs)]


# ------------------------------------------------------------------ mistura de quadros (câmera lenta)
def _blend_on(v: dict | None) -> bool:
    return bool((v or {}).get("mistura_quadros", False))


def blend_window(seq, clip, t: int) -> list[tuple[int, float]] | None:
    """A janela da mistura de quadros no quadro t (`vfx.WINDOWS`): [(k, 1 − f), (k + 1, f)] com u = k + f a posição no
    arquivo que `Sequence.src_frame` usa (no reverso, a fronteira seguinte; com a manivela, a oscilação), ou None quando
    o clipe mostra pelo menos um quadro do arquivo por quadro da sequência, f ≈ 0, no último quadro do arquivo,
    congelado, imagem ou sem arquivo."""
    from .timeline import EPS, VIDEO
    if clip.kind != VIDEO or not _blend_on(clip.values) or clip.frozen:
        return None
    src = seq.sources.get(clip.src)
    if src is None or src.is_image or not src.is_file or src.fps <= 0 or src.frames < 2:
        return None
    a, b = seq.src_time(clip, t), seq.src_time(clip, t + 1)
    if abs(b - a) * src.fps >= 1.0 - 1e-6:  # um quadro do arquivo (ou mais) por quadro da sequência
        return None
    s = b if clip.reverse else a
    if clip.values.get("manivela", "nenhuma") != "nenhuma":
        s += seq.crank_offset(clip, t)
    u = s * src.fps
    k = int(math.floor(u + EPS))
    f = round(u - k, 9)  # sem o resto de ponto flutuante: o reverso dá os mesmos pesos que o clipe para a frente
    if k < 0 or k >= src.frames - 1 or f <= BLEND_MIN or f >= 1.0 - BLEND_MIN:
        return None
    return [(k, 1.0 - f), (k + 1, f)]


# ------------------------------------------------------------------ registro
# O ruído temporal vem antes do deflicker: os vizinhos que ele lê são os quadros do arquivo, sem o ganho.
vfx.register(vfx.Effect(NOISE, MODULE, vfx.ORDER["tempo"], active=lambda v: noise_radius(v) > 0,
                        passes=_noise_passes, radius=noise_radius, keys=NOISE_KEYS))
vfx.register(vfx.Effect(DEFLICKER, MODULE, vfx.ORDER["tempo"] + 10, active=_deflicker_active,
                        passes=_deflicker_passes, keys=DEFLICKER_KEYS))
# A mistura não tem passo na pilha (é a janela abaixo); o efeito sem passo só leva o clipe ao aviso do módulo.
vfx.register(vfx.Effect(BLEND, MODULE, vfx.ORDER["tempo"] + 20, active=_blend_on, passes=lambda ctx: [],
                        keys=(BLEND,)))
vfx.WINDOWS[BLEND] = blend_window
